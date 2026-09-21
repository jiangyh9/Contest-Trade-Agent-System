"""
Price Info Tools
"""

import asyncio
import time
import pandas as pd
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from utils.akshare_utils import akshare_cached
from tools.tool_utils import smart_tool

class PriceInfoInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company. Only one symbol is allowed.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


def _normalize_price_df(df: pd.DataFrame, source: str = "") -> pd.DataFrame:
    """统一各数据源返回的列名"""
    rename_map = {
        "日期": "date",
        "交易日期": "date",
        "开盘": "open",
        "收盘价": "close",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "turnover",
        "振幅": "amplitude",
        "涨跌幅": "change_percent",
        "涨跌额": "change_amount",
        "换手率": "turnover_rate"
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def _fetch_with_retry(func_name: str, func_kwargs: dict, retries: int = 3, delay: float = 0.5):
    """带重试的 AKShare 调用"""
    last_error = None
    for attempt in range(retries):
        try:
            return akshare_cached.run(func_name=func_name, func_kwargs=func_kwargs, verbose=False)
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    raise last_error


@smart_tool(
    description="Get the price information of a symbol. Currently only support CN-Stock and HK-Stock.",
    args_schema=PriceInfoInput,
    max_output_len=2000,
    timeout_seconds=10.0
)
async def price_info(market: str, symbol: str, trigger_time: str=None) -> str:
    try:
        if not trigger_time:
            return {"error": "trigger_time is required"}
        # Normalize dates
        trigger_date_str = trigger_time.split(" ")[0]  # YYYY-MM-DD
        trigger_date = datetime.strptime(trigger_date_str, "%Y-%m-%d")
        end_date = (trigger_date - timedelta(days=1)).strftime("%Y%m%d")
        start_date = (trigger_date - timedelta(days=30)).strftime("%Y%m%d")

        if market not in ["CN-Stock"]:
            return {"error": "Market not supported."}

        base_symbol = symbol.split(".")[0]
        errors = []
        df = None

        # 1. 主数据源：东方财富（前复权）
        try:
            df = _fetch_with_retry(
                "stock_zh_a_hist",
                {
                    "symbol": base_symbol,
                    "period": "daily",
                    "start_date": start_date,
                    "end_date": end_date,
                    "adjust": "qfq"
                },
                retries=3,
                delay=0.8
            )
        except Exception as e:
            errors.append(f"stock_zh_a_hist: {e}")

        # 2. 兜底 1：腾讯财经历史行情
        if df is None or len(df) == 0:
            try:
                df = _fetch_with_retry(
                    "stock_zh_a_hist_tx",
                    {
                        "symbol": base_symbol,
                        "start_date": start_date,
                        "end_date": end_date,
                        "adjust": "qfq"
                    },
                    retries=2,
                    delay=0.5
                )
            except Exception as e:
                errors.append(f"stock_zh_a_hist_tx: {e}")

        # 3. 兜底 2：新浪财经历史行情（无前复权）
        if df is None or len(df) == 0:
            try:
                # Sina 接口需要带 sh/sz 前缀
                prefix = "sh" if base_symbol.startswith("6") else "sz"
                sina_symbol = f"{prefix}{base_symbol}"
                df = _fetch_with_retry(
                    "stock_zh_a_daily",
                    {
                        "symbol": sina_symbol,
                        "start_date": start_date,
                        "end_date": end_date,
                        "adjust": ""
                    },
                    retries=2,
                    delay=0.5
                )
            except Exception as e:
                errors.append(f"stock_zh_a_daily: {e}")

        if df is None or len(df) == 0:
            return {"error": f"All price data sources failed for {symbol}. Errors: {'; '.join(errors)}"}

        df = _normalize_price_df(df)
        return {"result": df.to_markdown()}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    result = asyncio.run(price_info.ainvoke(
        { "market": "CN-Stock", 
         "symbol": "600519.SH", 
         "trigger_time": "2025-07-09 15:00:00"}))
    print(result)

    result = asyncio.run(price_info.ainvoke(
        { "market": "HK-Stock", 
         "symbol": "009988.HK", 
         "trigger_time": "2025-07-09 15:00:00"}))
    print(result)