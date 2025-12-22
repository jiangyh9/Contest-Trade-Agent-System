"""
Price Info Tools
"""
import asyncio
import pandas as pd
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from utils.alpha_vantage_utils import alpha_vantage_cached
from tools.tool_utils import smart_tool


class PriceInfoInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company. Only one symbol is allowed.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")

def get_us_stock_daily_price(symbol: str) -> pd.DataFrame:
    """
    获取美股日K线数据
    """
    params = {
        'function': 'TIME_SERIES_DAILY',
        'symbol': symbol
    }
    
    try:
        result = alpha_vantage_cached.run(params, verbose=False)
        
        # 检查是否有时间序列数据
        time_series_key = "Time Series (Daily)"
        if time_series_key not in result:
            return pd.DataFrame()
        
        time_series = result[time_series_key]
        
        # 转换为DataFrame
        df_data = []
        for date_str, daily_data in time_series.items():
            row = {
                'date': date_str,
                'open': float(daily_data['1. open']),
                'high': float(daily_data['2. high']),
                'low': float(daily_data['3. low']),
                'close': float(daily_data['4. close']),
                'volume': int(daily_data['5. volume'])
            }
            df_data.append(row)
        
        df = pd.DataFrame(df_data)
        if not df.empty:
            # 转换日期列并排序
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
        
        return df
        
    except Exception as e:
        print(f"获取价格数据时出错: {e}")
        return pd.DataFrame()

def get_us_stock_quote(symbol: str) -> dict:
    """
    获取美股实时报价
    """
    params = {
        'function': 'GLOBAL_QUOTE',
        'symbol': symbol
    }
    
    try:
        result = alpha_vantage_cached.run(params, verbose=False)
        
        # 检查是否有全局报价数据
        quote_key = "Global Quote"
        if quote_key not in result:
            return {}
        
        quote_data = result[quote_key]
        
        # 格式化报价数据
        formatted_quote = {
            'symbol': quote_data.get('01. symbol', ''),
            'open': float(quote_data.get('02. open', 0)),
            'high': float(quote_data.get('03. high', 0)),
            'low': float(quote_data.get('04. low', 0)),
            'price': float(quote_data.get('05. price', 0)),
            'volume': int(quote_data.get('06. volume', 0)),
            'latest_trading_day': quote_data.get('07. latest trading day', ''),
            'previous_close': float(quote_data.get('08. previous close', 0)),
            'change': float(quote_data.get('09. change', 0)),
            'change_percent': quote_data.get('10. change percent', '')
        }
        
        return formatted_quote
        
    except Exception as e:
        print(f"获取实时报价时出错: {e}")
        return {}

@smart_tool(
    description="Get the price information of a US stock symbol using Alpha Vantage API.",
    args_schema=PriceInfoInput,
    max_output_len=4000,
    timeout_seconds=10.0
)
async def price_info(market: str, symbol: str, trigger_time: str = None) -> dict:
    if market != "US-Stock":
        return {"error": "Market not supported. This tool only supports US-Stock."}
    
    try:
        # 获取日K线数据
        daily_df = get_us_stock_daily_price(symbol)
        
        # 获取实时报价
        quote_data = get_us_stock_quote(symbol)
        
        result = {
            "symbol": symbol,
            "market": market,
            "trigger_time": trigger_time,
            "data_source": "Alpha Vantage"
        }
        
        # 如果有日K线数据，过滤最近30天
        if not daily_df.empty and trigger_time:
            trigger_date = datetime.strptime(trigger_time.split(" ")[0], "%Y-%m-%d")
            start_date = trigger_date - timedelta(days=30)
            end_date = trigger_date - timedelta(days=1)
            
            # 过滤日期范围
            filtered_df = daily_df[
                (daily_df['date'] >= start_date) & 
                (daily_df['date'] <= end_date)
            ]
            
            if not filtered_df.empty:
                result["daily_prices"] = filtered_df.to_dict('records')
                result["daily_prices_markdown"] = filtered_df.to_markdown(index=False)
            else:
                result["daily_prices"] = "No historical data found for the specified date range"
        elif not daily_df.empty:
            # 如果没有指定trigger_time，返回最近30条记录
            recent_df = daily_df.tail(30)
            result["daily_prices"] = recent_df.to_dict('records')
            result["daily_prices_markdown"] = recent_df.to_markdown(index=False)
        else:
            result["daily_prices"] = "No historical price data available"
        
        # 添加实时报价
        if quote_data:
            result["current_quote"] = quote_data
        else:
            result["current_quote"] = "No current quote data available"
        
        return result
        
    except Exception as e:
        return {"error": f"Failed to get price information: {str(e)}"}

if __name__ == "__main__":
    result = asyncio.run(price_info.ainvoke(
        {"market": "US-Stock", 
         "symbol": "AAPL", 
         "trigger_time": "2025-08-20 15:00:00"}))
    print("AAPL价格信息:")
    print(result)
    
    result = asyncio.run(price_info.ainvoke(
        {"market": "US-Stock", 
         "symbol": "TSLA", 
         "trigger_time": "2025-08-20 15:00:00"}))
    print("\nTSLA价格信息:")
    print(result)
