"""
Price Info Tools (Finnhub + FMP)
美股价格数据工具：用 FMP 获取历史日线与实时报价，Finnhub 作为降级备份。
"""
import asyncio
import pandas as pd
from typing import Dict, Any
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from utils.fmp_utils import fmp_cached, get_us_stock_quote as _fmp_get_us_stock_quote
from utils.finnhub_utils import get_us_stock_price
from tools.tool_utils import smart_tool


class PriceInfoInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company. Only one symbol is allowed.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


def _get_us_stock_daily_price(symbol: str, trigger_time: str, lookback_days: int = 180) -> pd.DataFrame:
    """通过 FMP 获取历史日K线"""
    try:
        trigger_date_str = trigger_time.split(" ")[0]
        trigger_dt = datetime.strptime(trigger_date_str, "%Y-%m-%d")
        # 历史数据取到 trigger 前一天，避免未来数据泄漏
        to_dt = trigger_dt - timedelta(days=1)
        from_dt = trigger_dt - timedelta(days=lookback_days)

        df = fmp_cached.get_historical_price(
            symbol,
            from_date=from_dt.strftime("%Y-%m-%d"),
            to_date=to_dt.strftime("%Y-%m-%d"),
            verbose=False,
        )
        if df is None or df.empty:
            return pd.DataFrame()

        # 统一列名并确保类型
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.sort_values('date').reset_index(drop=True)
        return df
    except Exception as e:
        print(f"获取 {symbol} 历史价格时出错: {e}")
        return pd.DataFrame()


def _get_us_stock_quote(symbol: str) -> Dict[str, Any]:
    """通过 FMP 获取实时报价；失败时回退到 Finnhub quote"""
    quote: Dict[str, Any] = {}
    try:
        result = _fmp_get_us_stock_quote(symbol, verbose=False)
        if result:
            quote = {
                "symbol": result.get("symbol", symbol),
                "price": result.get("price"),
                "open": result.get("open"),
                "high": result.get("dayHigh"),
                "low": result.get("dayLow"),
                "previous_close": result.get("previousClose"),
                "change": result.get("change"),
                "change_percent": result.get("changePercentage"),
                "volume": result.get("volume"),
                "latest_trading_day": datetime.fromtimestamp(result.get("timestamp", 0)).strftime("%Y-%m-%d") if result.get("timestamp") else None,
                "data_source": "FMP",
            }
    except Exception as e:
        print(f"FMP quote failed for {symbol}: {e}")

    if not quote or quote.get("price") is None:
        try:
            fh = get_us_stock_price(symbol, verbose=False)
            if fh:
                quote = {
                    "symbol": symbol,
                    "price": fh.get("c"),
                    "open": fh.get("o"),
                    "high": fh.get("h"),
                    "low": fh.get("l"),
                    "previous_close": fh.get("pc"),
                    "change": fh.get("d"),
                    "change_percent": fh.get("dp"),
                    "volume": None,
                    "latest_trading_day": None,
                    "data_source": "Finnhub",
                }
        except Exception as e:
            print(f"Finnhub quote fallback failed for {symbol}: {e}")

    return quote


@smart_tool(
    description="Get the price information of a US stock symbol using FMP/Finnhub API (historical daily prices + current quote).",
    args_schema=PriceInfoInput,
    max_output_len=4000,
    timeout_seconds=15.0
)
async def price_info(market: str, symbol: str, trigger_time: str = None) -> Dict[str, Any]:
    if market != "US-Stock":
        return {"error": "Market not supported. This tool only supports US-Stock."}

    try:
        # 历史价格
        daily_df = _get_us_stock_daily_price(symbol, trigger_time)

        # 实时报价
        quote_data = _get_us_stock_quote(symbol)

        result = {
            "symbol": symbol,
            "market": market,
            "trigger_time": trigger_time,
            "data_source": "FMP/Finnhub",
        }

        if not daily_df.empty and trigger_time:
            trigger_date = datetime.strptime(trigger_time.split(" ")[0], "%Y-%m-%d")
            start_date = trigger_date - timedelta(days=30)
            end_date = trigger_date - timedelta(days=1)

            filtered_df = daily_df[
                (daily_df['date'] >= start_date) &
                (daily_df['date'] <= end_date)
            ].copy()
            if not filtered_df.empty:
                filtered_df['date'] = filtered_df['date'].dt.strftime('%Y-%m-%d')
                # 限制返回行数和列，避免超出工具输出长度上限
                cols = [c for c in ['date', 'open', 'high', 'low', 'close', 'volume'] if c in filtered_df.columns]
                filtered_df = filtered_df[cols].tail(10)
                result["daily_prices"] = filtered_df.to_dict('records')
                result["daily_prices_markdown"] = filtered_df.to_markdown(index=False)
            else:
                result["daily_prices"] = "No historical data found for the specified date range"
        elif not daily_df.empty:
            recent_df = daily_df.tail(10).copy()
            recent_df['date'] = recent_df['date'].dt.strftime('%Y-%m-%d')
            cols = [c for c in ['date', 'open', 'high', 'low', 'close', 'volume'] if c in recent_df.columns]
            recent_df = recent_df[cols]
            result["daily_prices"] = recent_df.to_dict('records')
            result["daily_prices_markdown"] = recent_df.to_markdown(index=False)
        else:
            result["daily_prices"] = "No historical price data available"

        if quote_data and quote_data.get("price") is not None:
            result["current_quote"] = quote_data
        else:
            result["current_quote"] = "No current quote data available"

        return result

    except Exception as e:
        return {"error": f"Failed to get price information: {str(e)}"}


if __name__ == "__main__":
    result = asyncio.run(price_info.ainvoke(
        {"market": "US-Stock", "symbol": "AAPL", "trigger_time": "2026-09-23 09:00:00"}))
    print("AAPL价格信息:")
    print(result)
