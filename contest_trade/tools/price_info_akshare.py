"""
Price Info Tools
"""

import asyncio
import pandas as pd
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from utils.akshare_utils import akshare_cached
from tools.tool_utils import smart_tool

class PriceInfoInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company. Only one symbol is allowed.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")

@smart_tool(
    description="Get the price information of a symbol. Currently only support CN-Stock and HK-Stock.",
    args_schema=PriceInfoInput,
    max_output_len=2000,
    timeout_seconds=3.0
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

        if market in ["CN-Stock"]:
            # Normalize symbol like 600519.SH -> 600519
            base_symbol = symbol.split(".")[0]
            # Fetch via akshare with caching
            df = akshare_cached.run(
                func_name="stock_zh_a_hist",
                func_kwargs={
                    "symbol": base_symbol,
                    "period": "daily",
                    "start_date": start_date,
                    "end_date": end_date,
                    "adjust": "qfq"
                },
                verbose=False
            )
            if df is None or len(df) == 0:
                return {"error": "No data returned from akshare."}
            # Rename columns like test.py
            rename_map = {
                "日期": "date",
                "开盘": "open",
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
                df["date"] = pd.to_datetime(df["date"])  # align with test.py
            return {"result": df.to_markdown()}
        else:
            return {"error": "Market not supported."}
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