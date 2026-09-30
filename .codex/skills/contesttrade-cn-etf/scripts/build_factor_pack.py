#!/usr/bin/env python3
"""Build a compact China ETF factor pack from WindDB without model calls."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--lookback-calendar-days", type=int, default=150)
    parser.add_argument("--candidate-limit", type=int, default=40)
    parser.add_argument("--output")
    return parser.parse_args()


def zscore(values: pd.Series) -> pd.Series:
    values = pd.to_numeric(values, errors="coerce")
    std = values.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=values.index)
    return (values - values.mean()) / std


def clean_number(value):
    if value is None or pd.isna(value) or np.isinf(value):
        return None
    return round(float(value), 8)


def serialize_candidates(frame: pd.DataFrame, limit: int) -> list[dict]:
    fields = [
        "code", "name", "asset_class", "market_scope", "strategy_type",
        "close", "amount", "avg_amount_20d", "ret_1d", "ret_5d", "ret_10d",
        "ret_20d", "volatility_20d", "max_drawdown_20d", "volume_ratio_5d",
        "above_ma5", "above_ma10", "above_ma20", "rs_5d", "rs_10d",
        "screen_score",
    ]
    output = []
    for _, row in frame.head(limit).iterrows():
        item = {}
        for field in fields:
            value = row.get(field)
            if isinstance(value, (bool, np.bool_)):
                item[field] = bool(value)
            elif isinstance(value, str):
                item[field] = value
            else:
                item[field] = clean_number(value)
        output.append(item)
    return output


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).resolve()
    sys.path.insert(0, str(root / "contest_trade"))
    os.environ.setdefault("CONTEST_TRADE_MARKET", "CN-Stock")

    from config.config import cfg
    from utils.etf_universe_provider import load_etf_universe
    from utils.wind_jdbc_client import get_wind_client

    as_of = datetime.strptime(args.as_of, "%Y-%m-%d")
    start_dt = (as_of - timedelta(days=args.lookback_calendar_days)).strftime("%Y%m%d")
    end_dt = as_of.strftime("%Y%m%d")

    universe = load_etf_universe(cfg, as_of_date=args.as_of)
    if universe.get("source") != "wind_auto":
        raise RuntimeError(
            "WindDB unavailable; refusing to present the static fallback as full-market data"
        )

    metadata = pd.DataFrame(universe["etfs"])
    eligible_codes = set(metadata["code"].dropna().astype(str))
    client = get_wind_client(cfg)
    # Calculate rolling factors in Oracle and transfer only the latest row per ETF.
    # This avoids moving roughly 100k daily rows through JDBC for each run.
    sql = f"""
    WITH FACTORS AS (
        SELECT
            P.S_INFO_WINDCODE,
            P.TRADE_DT,
            P.S_DQ_CLOSE,
            P.S_DQ_AMOUNT,
            P.S_DQ_VOLUME,
            ROW_NUMBER() OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT DESC
            ) AS RN,
            P.S_DQ_CLOSE / NULLIF(LAG(P.S_DQ_CLOSE, 1) OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT
            ), 0) - 1 AS RET_1D,
            P.S_DQ_CLOSE / NULLIF(LAG(P.S_DQ_CLOSE, 5) OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT
            ), 0) - 1 AS RET_5D,
            P.S_DQ_CLOSE / NULLIF(LAG(P.S_DQ_CLOSE, 10) OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT
            ), 0) - 1 AS RET_10D,
            P.S_DQ_CLOSE / NULLIF(LAG(P.S_DQ_CLOSE, 20) OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT
            ), 0) - 1 AS RET_20D,
            AVG(P.S_DQ_CLOSE) OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT
                ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
            ) AS MA5,
            AVG(P.S_DQ_CLOSE) OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT
                ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
            ) AS MA10,
            AVG(P.S_DQ_CLOSE) OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT
                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
            ) AS MA20,
            STDDEV(P.S_DQ_PCTCHANGE / 100) OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT
                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
            ) AS VOLATILITY_20D,
            AVG(P.S_DQ_AMOUNT) OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT
                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
            ) AS AVG_AMOUNT_20D,
            AVG(P.S_DQ_VOLUME) OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT
                ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
            ) AS AVG_VOLUME_5D,
            MAX(P.S_DQ_CLOSE) OVER (
                PARTITION BY P.S_INFO_WINDCODE ORDER BY P.TRADE_DT
                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
            ) AS PEAK_20D
        FROM WIND.CHINACLOSEDFUNDEODPRICE P
        WHERE P.TRADE_DT >= '{start_dt}'
          AND P.TRADE_DT <= '{end_dt}'
          AND EXISTS (
              SELECT 1 FROM WIND.CHINAMUTUALFUNDDESCRIPTION F
              WHERE F.F_INFO_WINDCODE = P.S_INFO_WINDCODE
                AND F.F_INFO_NAME LIKE '%ETF%'
          )
    )
    SELECT * FROM FACTORS WHERE RN = 1
    """
    latest = client.query_to_df(sql)
    if latest.empty:
        raise RuntimeError("WindDB returned no ETF prices for the requested period")
    latest = latest[latest["S_INFO_WINDCODE"].astype(str).isin(eligible_codes)].copy()
    latest["TRADE_DT"] = pd.to_datetime(latest["TRADE_DT"], format="%Y%m%d")
    numeric_fields = [
        "S_DQ_CLOSE", "S_DQ_AMOUNT", "S_DQ_VOLUME", "RET_1D", "RET_5D",
        "RET_10D", "RET_20D", "MA5", "MA10", "MA20", "VOLATILITY_20D",
        "AVG_AMOUNT_20D", "AVG_VOLUME_5D", "PEAK_20D",
    ]
    for field in numeric_fields:
        latest[field] = pd.to_numeric(latest[field], errors="coerce")
    latest = latest.rename(columns={
        "S_DQ_CLOSE": "close", "S_DQ_AMOUNT": "amount",
        "RET_1D": "ret_1d", "RET_5D": "ret_5d", "RET_10D": "ret_10d",
        "RET_20D": "ret_20d", "MA5": "ma5", "MA10": "ma10", "MA20": "ma20",
        "VOLATILITY_20D": "volatility_20d", "AVG_AMOUNT_20D": "avg_amount_20d",
        "AVG_VOLUME_5D": "avg_volume_5d", "PEAK_20D": "peak_20d",
    })
    latest["volume_ratio_5d"] = latest["S_DQ_VOLUME"] / latest["avg_volume_5d"]
    latest["max_drawdown_20d"] = latest["close"] / latest["peak_20d"] - 1
    cutoff = latest["TRADE_DT"].max()
    latest = latest.merge(metadata, left_on="S_INFO_WINDCODE", right_on="code", how="inner")
    for window in (5, 10, 20):
        latest[f"above_ma{window}"] = latest["close"] > latest[f"ma{window}"]

    benchmark_code = universe.get("benchmark", "510300.SH")
    benchmark = latest[latest["code"] == benchmark_code]
    benchmark_5d = benchmark["ret_5d"].iloc[0] if not benchmark.empty else np.nan
    benchmark_10d = benchmark["ret_10d"].iloc[0] if not benchmark.empty else np.nan
    latest["rs_5d"] = latest["ret_5d"] - benchmark_5d
    latest["rs_10d"] = latest["ret_10d"] - benchmark_10d

    liquid = latest[
        (latest["avg_amount_20d"].fillna(0) > 0) & latest["ret_20d"].notna()
    ].copy()

    momentum = liquid.copy()
    momentum["screen_score"] = (
        0.40 * zscore(momentum["ret_5d"])
        + 0.30 * zscore(momentum["ret_10d"])
        + 0.20 * zscore(momentum["rs_5d"])
        + 0.10 * zscore(momentum["volume_ratio_5d"])
    )
    momentum = momentum.sort_values("screen_score", ascending=False)

    trend = liquid[liquid["above_ma10"] & liquid["above_ma20"]].copy()
    trend["screen_score"] = (
        0.40 * zscore(trend["ret_20d"])
        + 0.30 * zscore(trend["ret_10d"])
        + 0.20 * zscore(trend["rs_10d"])
        - 0.10 * zscore(trend["volatility_20d"])
    )
    trend = trend.sort_values("screen_score", ascending=False)

    defensive = liquid[
        liquid["asset_class"].isin(["债券ETF", "商品ETF", "货币ETF", "多资产ETF"])
        | liquid["strategy_type"].eq("Smart Beta")
    ].copy()
    defensive["screen_score"] = (
        0.35 * zscore(defensive["ret_10d"])
        + 0.25 * zscore(defensive["rs_10d"])
        - 0.25 * zscore(defensive["volatility_20d"])
        + 0.15 * zscore(defensive["max_drawdown_20d"])
    )
    defensive = defensive.sort_values("screen_score", ascending=False)

    reversal = liquid[(liquid["ret_20d"] < 0) & liquid["above_ma5"]].copy()
    reversal["screen_score"] = (
        0.35 * zscore(reversal["ret_5d"])
        - 0.30 * zscore(reversal["ret_20d"])
        + 0.20 * zscore(reversal["volume_ratio_5d"])
        + 0.15 * zscore(reversal["max_drawdown_20d"])
    )
    reversal = reversal.sort_values("screen_score", ascending=False)

    pack = {
        "as_of_date": args.as_of,
        "data_cutoff": cutoff.strftime("%Y-%m-%d"),
        "source": "WindDB",
        "benchmark": benchmark_code,
        "universe": {
            "total": len(universe["etfs"]),
            "eligible_with_20d_history": len(liquid),
            "by_asset_class": dict(
                Counter(item["asset_class"] for item in universe["etfs"])
            ),
        },
        "market_breadth": {
            "above_ma20_ratio": clean_number(liquid["above_ma20"].mean()),
            "positive_5d_ratio": clean_number((liquid["ret_5d"] > 0).mean()),
            "median_5d_return": clean_number(liquid["ret_5d"].median()),
            "median_20d_return": clean_number(liquid["ret_20d"].median()),
        },
        "candidate_screens": {
            "强势动量": serialize_candidates(momentum, args.candidate_limit),
            "趋势确认": serialize_candidates(trend, args.candidate_limit),
            "防御轮动": serialize_candidates(defensive, args.candidate_limit),
            "反转修复": serialize_candidates(reversal, args.candidate_limit),
        },
        "limitations": [
            "Old-date analysis uses the current Wind fund master and may have survivorship bias.",
            "ETF taxonomy is name-derived and should be reviewed for unfamiliar products.",
            "This pack contains price, volume, and classification factors, not news evidence.",
        ],
    }

    output = Path(args.output) if args.output else (
        root / "agents_workspace" / "codex_etf" / args.as_of / "factor_pack.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "data_cutoff": pack["data_cutoff"],
        "universe": pack["universe"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
