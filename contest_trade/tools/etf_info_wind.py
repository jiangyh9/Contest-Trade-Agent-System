"""
ETF 基础信息查询工具（Wind JDBC）

支持根据 ETF 代码（510300.SH 格式）查询名称、行业板块、主题分类。
"""

import json
import hashlib
import asyncio
import pandas as pd
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field
from utils.wind_jdbc_client import get_wind_client
from tools.tool_utils import smart_tool
from config.config import cfg
from utils.etf_universe_provider import classify_etf

TOOL_HOME = Path(__file__).parent.resolve()
TOOL_CACHE = TOOL_HOME / "etf_info_wind_cache"
if not TOOL_CACHE.exists():
    TOOL_CACHE.mkdir(parents=True, exist_ok=True)


def _load_etf_universe() -> dict:
    from config.config import PROJECT_ROOT
    path_attr = getattr(cfg, "etf_universe_path", "config/etf_universe.json")
    path = Path(PROJECT_ROOT) / path_attr
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_etf_from_universe(symbol: str) -> dict:
    data = _load_etf_universe()
    for etf in data.get("etfs", []):
        if etf["code"] == symbol:
            return etf
    return {}


def _get_etf_name_from_wind(symbol: str) -> str:
    """从 CHINAMUTUALFUNDDESCRIPTION 查 ETF 简称"""
    client = get_wind_client(cfg)
    sql = f"""
    SELECT F_INFO_NAME FROM WIND.CHINAMUTUALFUNDDESCRIPTION
    WHERE F_INFO_WINDCODE = '{symbol}'
    """
    df = client.query_to_df(sql)
    if df.empty:
        return ""
    return str(df.iloc[0, 0])


class ETFInfoInput(BaseModel):
    symbol: str = Field(description="ETF Wind 代码，例如 '510300.SH'、'159915.SZ'")
    trigger_time: str = Field(description="触发时间，格式 YYYY-MM-DD HH:MM:SS")


@smart_tool(
    description="查询 Wind ETF 基础信息：名称、板块、主题。",
    args_schema=ETFInfoInput,
    max_output_len=1000,
    timeout_seconds=30.0,
)
async def etf_info(symbol: str, trigger_time: str) -> str:
    cache_key = f"{symbol}_{trigger_time.split(' ')[0]}"
    cache_file = TOOL_CACHE / f"{hashlib.md5(cache_key.encode()).hexdigest()}.txt"
    if cache_file.exists():
        return cache_file.read_text()

    universe_meta = _get_etf_from_universe(symbol)
    name = universe_meta.get("name") or _get_etf_name_from_wind(symbol) or symbol
    asset_class = universe_meta.get("asset_class") or classify_etf(name)
    sector = universe_meta.get("sector", asset_class)
    theme = universe_meta.get("theme", "未知")

    result = (
        f"ETF: {name} ({symbol})\n"
        f"资产类别: {asset_class}\n"
        f"所属板块/行业: {sector}\n"
        f"主题: {theme}\n"
    )
    cache_file.write_text(result)
    return result


if __name__ == "__main__":
    r = asyncio.run(etf_info.ainvoke({"symbol": "510300.SH", "trigger_time": "2026-09-10 09:00:00"}))
    print(r)
