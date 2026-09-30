"""
ETF 历史价格与动量查询工具（Wind JDBC）

支持查询指定 ETF 在 trigger_time 之前一段时间的收盘价、涨幅、均线、相对强弱等指标。
"""

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

TOOL_HOME = Path(__file__).parent.resolve()
TOOL_CACHE = TOOL_HOME / "etf_price_wind_cache"
if not TOOL_CACHE.exists():
    TOOL_CACHE.mkdir(parents=True, exist_ok=True)


def _query_etf_price(symbol: str, start_dt: str, end_dt: str) -> pd.DataFrame:
    client = get_wind_client(cfg)
    sql = f"""
    SELECT
        S_INFO_WINDCODE,
        TRADE_DT,
        S_DQ_OPEN,
        S_DQ_HIGH,
        S_DQ_LOW,
        S_DQ_CLOSE,
        S_DQ_PCTCHANGE,
        S_DQ_VOLUME,
        S_DQ_AMOUNT,
        S_DQ_ADJPRECLOSE,
        S_DQ_ADJCLOSE
    FROM WIND.CHINACLOSEDFUNDEODPRICE
    WHERE S_INFO_WINDCODE = '{symbol}'
      AND TRADE_DT >= '{start_dt}'
      AND TRADE_DT <= '{end_dt}'
    ORDER BY TRADE_DT
    """
    df = client.query_to_df(sql)
    if df.empty:
        return df
    df["TRADE_DT"] = pd.to_datetime(df["TRADE_DT"], format="%Y%m%d")
    for c in ["S_DQ_OPEN", "S_DQ_HIGH", "S_DQ_LOW", "S_DQ_CLOSE", "S_DQ_PCTCHANGE", "S_DQ_VOLUME", "S_DQ_AMOUNT", "S_DQ_ADJPRECLOSE", "S_DQ_ADJCLOSE"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["S_DQ_CLOSE"]
    df["ret_1d"] = close.pct_change(1)
    df["ret_5d"] = close.pct_change(5)
    df["ret_10d"] = close.pct_change(10)
    df["ret_20d"] = close.pct_change(20)
    df["ma5"] = close.rolling(5).mean()
    df["ma10"] = close.rolling(10).mean()
    df["ma20"] = close.rolling(20).mean()
    df["vol_ma5"] = df["S_DQ_VOLUME"].rolling(5).mean()
    df["vol_ratio_5d"] = df["S_DQ_VOLUME"] / df["vol_ma5"]
    return df


def _format_price_info(df: pd.DataFrame, symbol: str) -> str:
    if df.empty:
        return f"未找到 {symbol} 的价格数据"
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest
    parts = [
        f"ETF代码: {symbol}",
        f"最新交易日: {latest['TRADE_DT'].strftime('%Y-%m-%d')}",
        f"最新收盘: {latest['S_DQ_CLOSE']:.3f}",
        f"最新涨幅: {latest['S_DQ_PCTCHANGE']:.2f}%",
        f"前收盘: {prev['S_DQ_CLOSE']:.3f}",
        f"5日涨幅: {latest['ret_5d']:.2%}" if not pd.isna(latest['ret_5d']) else "5日涨幅: NA",
        f"10日涨幅: {latest['ret_10d']:.2%}" if not pd.isna(latest['ret_10d']) else "10日涨幅: NA",
        f"20日涨幅: {latest['ret_20d']:.2%}" if not pd.isna(latest['ret_20d']) else "20日涨幅: NA",
        f"5/10/20日均线: {latest['ma5']:.3f} / {latest['ma10']:.3f} / {latest['ma20']:.3f}" if not pd.isna(latest['ma5']) else "均线: NA",
        f"成交量(最新/5日均): {latest['S_DQ_VOLUME']:.0f} / {latest['vol_ma5']:.0f}, 量价比: {latest['vol_ratio_5d']:.2f}" if not pd.isna(latest['vol_ma5']) else "量价比: NA",
        f"相对MA5位置: {'站上' if latest['S_DQ_CLOSE'] > latest['ma5'] else '跌破'}5日均线" if not pd.isna(latest['ma5']) else "",
        f"相对MA20位置: {'站上' if latest['S_DQ_CLOSE'] > latest['ma20'] else '跌破'}20日均线" if not pd.isna(latest['ma20']) else "",
    ]
    return "\n".join([p for p in parts if p])


class ETFPriceInput(BaseModel):
    symbol: str = Field(description="ETF Wind 代码，例如 '510300.SH'")
    trigger_time: str = Field(description="触发时间，格式 YYYY-MM-DD HH:MM:SS")
    lookback_days: int = Field(default=60, description="回看交易日天数")


@smart_tool(
    description="查询 Wind ETF 历史价格与动量指标（收盘价、涨幅、均线、量比等）。",
    args_schema=ETFPriceInput,
    max_output_len=2000,
    timeout_seconds=30.0,
)
async def etf_price(symbol: str, trigger_time: str, lookback_days: int = 60) -> str:
    cache_key = f"{symbol}_{trigger_time.split(' ')[0]}_{lookback_days}"
    cache_file = TOOL_CACHE / f"{hashlib.md5(cache_key.encode()).hexdigest()}.txt"
    if cache_file.exists():
        return cache_file.read_text()

    trade_date = get_previous_trading_date(trigger_time)
    trade_date_dt = datetime.strptime(trade_date, "%Y%m%d")
    start_dt = (trade_date_dt - timedelta(days=int(lookback_days * 1.5))).strftime("%Y%m%d")
    end_dt = trade_date_dt.strftime("%Y%m%d")

    df = _query_etf_price(symbol, start_dt, end_dt)
    df = _compute_indicators(df)
    result = _format_price_info(df, symbol)
    cache_file.write_text(result)
    return result


if __name__ == "__main__":
    r = asyncio.run(etf_price.ainvoke({"symbol": "510300.SH", "trigger_time": "2026-09-10 09:00:00", "lookback_days": 60}))
    print(r)
