from datetime import datetime
from utils.market_manager import GLOBAL_MARKET_MANAGER

def get_current_datetime(trigger_time: str) -> str:
    """Get current time"""
    if trigger_time:
        return trigger_time
    else:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_previous_trading_date(trigger_time: str, output_format: str = "%Y%m%d") -> str:
    """获取trigger_time的上一个交易日
    
    Args:
        trigger_time (str): 触发时间，格式：YYYY-MM-DD HH:MM:SS
    
    Returns:
        str: 上一个交易日，格式：YYYYMMDD
    """
    # 解析trigger_time
    trigger_datetime = datetime.strptime(trigger_time, '%Y-%m-%d %H:%M:%S')
    trigger_date = trigger_datetime.strftime('%Y%m%d')
    
    # 获取交易日列表
    trade_dates = GLOBAL_MARKET_MANAGER.get_trade_date(market_name="CN-Stock")
    
    # 找到上一个交易日
    previous_dates = [dt for dt in trade_dates if dt < trigger_date]
    previous_trading_date = previous_dates[-1]
    previous_trading_datetime = previous_trading_date[:4] + "-" + previous_trading_date[4:6] + "-" + previous_trading_date[6:] + " " + trigger_time.split(" ")[1]
    previous_trading_date_formatted = datetime.strptime(previous_trading_datetime, "%Y-%m-%d %H:%M:%S").strftime(output_format)
    return previous_trading_date_formatted


if __name__ == "__main__":
    print(get_current_datetime("2025-01-01 10:00:00"))
    print(get_previous_trading_date("2025-01-01 10:00:00"))