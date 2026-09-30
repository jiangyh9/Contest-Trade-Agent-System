"""ETF universe discovery and classification for Wind-backed workflows."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from loguru import logger

EQUITY = "股票ETF"
COMMODITY = "商品ETF"
BOND = "债券ETF"
MONEY = "货币ETF"
MULTI_ASSET = "多资产ETF"

_BOND_KEYWORDS = (
    "债", "国债", "地方债", "政金债", "信用债", "城投", "可转债", "短融",
)
_COMMODITY_KEYWORDS = (
    "黄金", "白银", "豆粕", "原油", "商品期货", "能源化工期货",
    "有色期货", "铜期货", "铝期货", "农产品期货",
)
_MONEY_KEYWORDS = ("货币", "现金", "保证金")
_MULTI_ASSET_KEYWORDS = ("多资产", "股债", "FOF", "资产配置")
_EXCLUDE_KEYWORDS = ("联接",)

_MARKET_RULES = (
    ("港股", ("港股", "恒生", "中概互联")),
    ("美股", ("纳指", "纳斯达克", "标普", "道琼斯", "美国")),
    ("日本", ("日经", "日本")),
    ("欧洲", ("德国", "法国", "欧洲", "德国DAX")),
    ("其他海外", ("印度", "东南亚", "沙特", "越南", "海外", "全球")),
)
_SMART_BETA_KEYWORDS = (
    "红利", "低波", "价值", "成长", "质量", "基本面", "等权", "增强", "自由现金流",
)
_BROAD_BASE_KEYWORDS = (
    "沪深300", "中证500", "中证1000", "上证50", "科创50", "创业板", "深证100",
    "A500", "A50", "恒生", "纳指", "纳斯达克", "标普", "道琼斯", "日经",
)


def classify_etf(name: str) -> str:
    """Classify an exchange-traded fund into the three supported asset buckets."""
    normalized = str(name or "").replace(" ", "")
    if any(keyword in normalized for keyword in _MONEY_KEYWORDS):
        return MONEY
    if any(keyword.upper() in normalized.upper() for keyword in _MULTI_ASSET_KEYWORDS):
        return MULTI_ASSET
    if any(keyword in normalized for keyword in _BOND_KEYWORDS):
        return BOND
    if any(keyword in normalized for keyword in _COMMODITY_KEYWORDS):
        return COMMODITY
    return EQUITY


def classify_market_scope(name: str, asset_class: str) -> str:
    if asset_class != EQUITY:
        return "不适用"
    normalized = str(name or "").replace(" ", "")
    for scope, keywords in _MARKET_RULES:
        if any(keyword in normalized for keyword in keywords):
            return scope
    return "A股"


def classify_strategy_type(name: str, asset_class: str) -> str:
    if asset_class != EQUITY:
        return "不适用"
    normalized = str(name or "").replace(" ", "")
    if any(keyword in normalized for keyword in _SMART_BETA_KEYWORDS):
        return "Smart Beta"
    if any(keyword in normalized for keyword in _BROAD_BASE_KEYWORDS):
        return "宽基"
    if any(keyword in normalized for keyword in ("主题", "人工智能", "机器人", "新能源", "芯片", "半导体")):
        return "主题"
    return "行业/主题"


def enrich_etf_meta(item: Dict[str, Any]) -> Dict[str, Any]:
    name = str(item.get("name", ""))
    asset_class = item.get("asset_class") or classify_etf(name)
    item["asset_class"] = asset_class
    item.setdefault("market_scope", classify_market_scope(name, asset_class))
    item.setdefault("strategy_type", classify_strategy_type(name, asset_class))
    item.setdefault("currency_exposure", "CNY" if item["market_scope"] in ("A股", "不适用") else "外币")
    item.setdefault("duration_bucket", "待识别" if asset_class == BOND else None)
    item.setdefault("commodity_type", name if asset_class == COMMODITY else None)
    return item


def _chunks(items: List[str], size: int = 800) -> Iterable[List[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def load_static_universe(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    for item in data.get("etfs", []):
        enrich_etf_meta(item)
    data.setdefault("source", "static")
    return data


def _query_wind_etfs(client) -> List[Dict[str, Any]]:
    # These two fields are stable across common Wind database editions. More
    # detailed classification is derived locally to avoid edition-specific columns.
    sql = """
    SELECT F_INFO_WINDCODE, F_INFO_NAME
    FROM WIND.CHINAMUTUALFUNDDESCRIPTION
    WHERE F_INFO_NAME LIKE '%ETF%'
      AND (F_INFO_WINDCODE LIKE '%.SH' OR F_INFO_WINDCODE LIKE '%.SZ')
    ORDER BY F_INFO_WINDCODE
    """
    frame = client.query_to_df(sql)
    if frame.empty:
        return []

    result: List[Dict[str, Any]] = []
    seen = set()
    for _, row in frame.iterrows():
        code = str(row.get("F_INFO_WINDCODE", "")).strip()
        name = str(row.get("F_INFO_NAME", "")).strip()
        if not code or not name or code in seen:
            continue
        if any(keyword in name for keyword in _EXCLUDE_KEYWORDS):
            continue
        asset_class = classify_etf(name)
        result.append(enrich_etf_meta({
            "code": code,
            "name": name,
            "asset_class": asset_class,
            "sector": asset_class,
            "theme": name,
        }))
        seen.add(code)
    return result


def _liquidity_snapshot(
    client,
    codes: List[str],
    as_of_date: str,
    lookback_calendar_days: int,
) -> pd.DataFrame:
    end_dt = as_of_date.replace("-", "")
    start_dt = (
        datetime.strptime(end_dt, "%Y%m%d") - timedelta(days=lookback_calendar_days)
    ).strftime("%Y%m%d")
    frames = []
    for batch in _chunks(codes):
        placeholders = ",".join(f"'{code}'" for code in batch)
        sql = f"""
        SELECT S_INFO_WINDCODE,
               MAX(TRADE_DT) AS LAST_TRADE_DT,
               COUNT(*) AS TRADE_DAYS,
               AVG(S_DQ_AMOUNT) AS AVG_AMOUNT
        FROM WIND.CHINACLOSEDFUNDEODPRICE
        WHERE S_INFO_WINDCODE IN ({placeholders})
          AND TRADE_DT >= '{start_dt}'
          AND TRADE_DT <= '{end_dt}'
        GROUP BY S_INFO_WINDCODE
        """
        frames.append(client.query_to_df(sql))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_etf_universe(
    cfg,
    as_of_date: Optional[str] = None,
    static_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load a Wind-discovered universe, falling back to the checked-in JSON pool."""
    from config.config import PROJECT_ROOT

    path = static_path or (
        Path(PROJECT_ROOT) / getattr(cfg, "etf_universe_path", "config/etf_universe.json")
    )
    universe_cfg = getattr(cfg, "etf_universe", {}) or {}
    mode = universe_cfg.get("mode", "wind_auto")
    benchmark = universe_cfg.get("benchmark", "510300.SH")
    asset_classes = set(universe_cfg.get(
        "asset_classes", [EQUITY, COMMODITY, BOND, MONEY, MULTI_ASSET]
    ))
    min_avg_amount = float(universe_cfg.get("min_avg_amount", 0))
    min_trade_days = int(universe_cfg.get("min_trade_days", 5))
    liquidity_lookback_days = int(universe_cfg.get("liquidity_lookback_days", 45))

    if mode == "static":
        return load_static_universe(path)

    try:
        from utils.wind_jdbc_client import get_wind_client

        client = get_wind_client(cfg)
        etfs = [item for item in _query_wind_etfs(client) if item["asset_class"] in asset_classes]
        if not etfs:
            raise RuntimeError("Wind ETF master query returned no rows")

        if as_of_date:
            snapshot = _liquidity_snapshot(
                client,
                [item["code"] for item in etfs],
                as_of_date,
                liquidity_lookback_days,
            )
            if not snapshot.empty:
                snapshot["TRADE_DAYS"] = pd.to_numeric(snapshot["TRADE_DAYS"], errors="coerce").fillna(0)
                snapshot["AVG_AMOUNT"] = pd.to_numeric(snapshot["AVG_AMOUNT"], errors="coerce").fillna(0)
                eligible = set(snapshot.loc[
                    (snapshot["TRADE_DAYS"] >= min_trade_days)
                    & (snapshot["AVG_AMOUNT"] >= min_avg_amount),
                    "S_INFO_WINDCODE",
                ].astype(str))
                etfs = [item for item in etfs if item["code"] in eligible]

        if benchmark not in {item["code"] for item in etfs}:
            etfs.append(enrich_etf_meta({
                "code": benchmark,
                "name": universe_cfg.get("benchmark_name", "沪深300ETF"),
                "asset_class": EQUITY,
                "sector": "大盘蓝筹",
                "theme": "沪深300",
            }))
        return {
            "source": "wind_auto",
            "as_of_date": as_of_date,
            "benchmark": benchmark,
            "benchmark_name": universe_cfg.get("benchmark_name", "沪深300ETF"),
            "etfs": etfs,
        }
    except Exception as exc:
        logger.warning(f"Wind 自动 ETF 池加载失败，回退静态池: {exc}")
        return load_static_universe(path)
