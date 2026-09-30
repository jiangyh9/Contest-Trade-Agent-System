"""
ETF 动量筛选工具（Wind JDBC）

根据 trigger_time 上一个交易日的动量指标，对 ETF 池进行排序筛选。
"""

import json
import hashlib
import asyncio
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from utils.wind_jdbc_client import get_wind_client
from utils.date_utils import get_previous_trading_date
from tools.tool_utils import smart_tool
from config.config import cfg
from utils.etf_universe_provider import load_etf_universe

TOOL_HOME = Path(__file__).parent.resolve()
TOOL_CACHE = TOOL_HOME / "etf_selector_wind_cache"
if not TOOL_CACHE.exists():
    TOOL_CACHE.mkdir(parents=True, exist_ok=True)


def _load_universe(as_of_date: str = None) -> dict:
    from config.config import PROJECT_ROOT
    path_attr = getattr(cfg, "etf_universe_path", "config/etf_universe.json")
    path = Path(PROJECT_ROOT) / path_attr
    return load_etf_universe(cfg, as_of_date=as_of_date, static_path=path)


def _query_pool_prices(codes: list, start_dt: str, end_dt: str) -> pd.DataFrame:
    client = get_wind_client(cfg)
    if len(codes) > 300:
        sql = f"""
        SELECT P.S_INFO_WINDCODE, P.TRADE_DT, P.S_DQ_CLOSE,
               P.S_DQ_PCTCHANGE, P.S_DQ_VOLUME, P.S_DQ_AMOUNT
        FROM WIND.CHINACLOSEDFUNDEODPRICE P
        WHERE P.TRADE_DT >= '{start_dt}'
          AND P.TRADE_DT <= '{end_dt}'
          AND EXISTS (
              SELECT 1 FROM WIND.CHINAMUTUALFUNDDESCRIPTION F
              WHERE F.F_INFO_WINDCODE = P.S_INFO_WINDCODE
                AND F.F_INFO_NAME LIKE '%ETF%'
          )
        ORDER BY P.S_INFO_WINDCODE, P.TRADE_DT
        """
        df = client.query_to_df(sql)
        if not df.empty:
            df = df[df["S_INFO_WINDCODE"].isin(set(codes))].copy()
    else:
        frames = []
        for start in range(0, len(codes), 800):
            batch = codes[start:start + 800]
            placeholders = ",".join([f"'{c}'" for c in batch])
            sql = f"""
        SELECT S_INFO_WINDCODE, TRADE_DT, S_DQ_CLOSE,
               S_DQ_PCTCHANGE, S_DQ_VOLUME, S_DQ_AMOUNT
        FROM WIND.CHINACLOSEDFUNDEODPRICE
        WHERE S_INFO_WINDCODE IN ({placeholders})
          AND TRADE_DT >= '{start_dt}'
          AND TRADE_DT <= '{end_dt}'
        ORDER BY S_INFO_WINDCODE, TRADE_DT
        """
            frames.append(client.query_to_df(sql))
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if df.empty:
        return df
    df["TRADE_DT"] = pd.to_datetime(df["TRADE_DT"], format="%Y%m%d")
    for c in ["S_DQ_CLOSE", "S_DQ_PCTCHANGE", "S_DQ_VOLUME", "S_DQ_AMOUNT"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _compute_momentum(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.sort_values(["S_INFO_WINDCODE", "TRADE_DT"])
    close = df["S_DQ_CLOSE"]
    df["ret_5d"] = close.groupby(df["S_INFO_WINDCODE"]).transform(lambda x: x.pct_change(5))
    df["ret_10d"] = close.groupby(df["S_INFO_WINDCODE"]).transform(lambda x: x.pct_change(10))
    df["ret_20d"] = close.groupby(df["S_INFO_WINDCODE"]).transform(lambda x: x.pct_change(20))
    df["ma5"] = close.groupby(df["S_INFO_WINDCODE"]).transform(lambda x: x.rolling(5).mean())
    df["ma20"] = close.groupby(df["S_INFO_WINDCODE"]).transform(lambda x: x.rolling(20).mean())
    df["above_ma5"] = df["S_DQ_CLOSE"] > df["ma5"]
    df["above_ma20"] = df["S_DQ_CLOSE"] > df["ma20"]
    return df


def _format_selector(df: pd.DataFrame, sort_by: str, ascending: bool, limit: int, universe: dict) -> str:
    if df.empty:
        return "未获取到 ETF 动量数据"
    latest = df[df["TRADE_DT"] == df["TRADE_DT"].max()].copy()
    latest = latest.sort_values(sort_by, ascending=ascending).head(limit)

    meta = {e["code"]: e for e in universe.get("etfs", [])}
    lines = [
        f"筛选条件: 按 {sort_by} 排序 ({'升序' if ascending else '降序'}), 取前 {limit} 只",
        f"数据截止日: {latest['TRADE_DT'].max().strftime('%Y-%m-%d') if not latest.empty else 'NA'}",
        "",
    ]
    for _, row in latest.iterrows():
        code = row["S_INFO_WINDCODE"]
        info = meta.get(code, {})
        name = info.get("name", code)
        sector = info.get("sector", "未知")
        theme = info.get("theme", "未知")
        lines.append(
            f"- {name} ({code}, {sector}/{theme}): "
            f"收盘 {row['S_DQ_CLOSE']:.3f}, "
            f"1日 {row['S_DQ_PCTCHANGE']:.2f}%, "
            f"5日 {row['ret_5d']:.2%}, "
            f"10日 {row['ret_10d']:.2%}, "
            f"20日 {row['ret_20d']:.2%}, "
            f"站上MA5 {'是' if row['above_ma5'] else '否'}, "
            f"站上MA20 {'是' if row['above_ma20'] else '否'}"
        )
    return "\n".join(lines)


class ETFSelectorInput(BaseModel):
    trigger_time: str = Field(description="触发时间，格式 YYYY-MM-DD HH:MM:SS")
    sort_by: str = Field(default="ret_5d", description="排序字段：ret_5d / ret_10d / ret_20d / S_DQ_PCTCHANGE")
    ascending: bool = Field(default=False, description="是否升序（False=降序取涨幅最大）")
    limit: int = Field(default=10, description="返回前 N 只 ETF")


@smart_tool(
    description="基于 Wind ETF 池的动量排名筛选，可按 5/10/20 日涨幅排序。",
    args_schema=ETFSelectorInput,
    max_output_len=3000,
    timeout_seconds=60.0,
)
async def etf_selector(trigger_time: str, sort_by: str = "ret_5d", ascending: bool = False, limit: int = 10) -> str:
    cache_key = f"{trigger_time.split(' ')[0]}_{sort_by}_{ascending}_{limit}"
    cache_file = TOOL_CACHE / f"{hashlib.md5(cache_key.encode()).hexdigest()}.txt"
    if cache_file.exists():
        return cache_file.read_text()

    trade_date = get_previous_trading_date(trigger_time)
    trade_date_dt = datetime.strptime(trade_date, "%Y%m%d")
    universe_data = _load_universe(trade_date_dt.strftime("%Y-%m-%d"))
    universe = universe_data.get("etfs", [])
    codes = [e["code"] for e in universe]
    benchmark = universe_data.get("benchmark", "510300.SH")
    if benchmark not in codes:
        codes.append(benchmark)

    start_dt = (trade_date_dt - timedelta(days=120)).strftime("%Y%m%d")
    end_dt = trade_date_dt.strftime("%Y%m%d")

    df = _query_pool_prices(codes, start_dt, end_dt)
    df = _compute_momentum(df)
    result = _format_selector(
        df, sort_by=sort_by, ascending=ascending, limit=limit, universe=universe_data
    )
    cache_file.write_text(result)
    return result


if __name__ == "__main__":
    r = asyncio.run(etf_selector.ainvoke({
        "trigger_time": "2026-09-10 09:00:00",
        "sort_by": "ret_5d",
        "ascending": False,
        "limit": 10,
    }))
    print(r)
