from datetime import datetime, timedelta
from utils.market_manager import GLOBAL_MARKET_MANAGER


def get_current_datetime(trigger_time: str) -> str:
    """Get current time"""
    if trigger_time:
        return trigger_time
    else:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _previous_business_day_simple(dt: datetime) -> datetime:
    """简单周末跳过，作为没有交易日历库时的 fallback"""
    one_day = timedelta(days=1)
    prev = dt - one_day
    while prev.weekday() >= 5:  # 周六=5, 周日=6
        prev -= one_day
    return prev


def get_previous_trading_date(trigger_time: str, market_name: str = "CN-Stock",
                              output_format: str = "%Y%m%d") -> str:
    """获取 trigger_time 的上一个交易日

    Args:
        trigger_time (str): 触发时间，格式：YYYY-MM-DD HH:MM:SS
        market_name (str): 市场标识，默认 CN-Stock；美股请传 US-Stock
        output_format (str): 输出格式

    Returns:
        str: 上一个交易日，格式默认 YYYYMMDD
    """
    trigger_datetime = datetime.strptime(trigger_time, '%Y-%m-%d %H:%M:%S')
    trigger_date = trigger_datetime.strftime('%Y%m%d')

    # A股相关市场：使用统一交易日历
    if market_name in ["CN-Stock", "CN-ETF", "CSI300", "CSI500", "CSI1000"]:
        trade_dates = GLOBAL_MARKET_MANAGER.get_trade_date(market_name=market_name)
        previous_dates = [dt for dt in trade_dates if dt < trigger_date]
        if not previous_dates:
            # 兜底：简单回退一天
            previous_trading_datetime = trigger_datetime - timedelta(days=1)
        else:
            previous_trading_date = previous_dates[-1]
            previous_trading_datetime = datetime.strptime(
                previous_trading_date[:4] + "-" + previous_trading_date[4:6] + "-" + previous_trading_date[6:] + " " + trigger_time.split(" ")[1],
                "%Y-%m-%d %H:%M:%S"
            )
        return previous_trading_datetime.strftime(output_format)

    # 美股市场：优先使用 exchange_calendars 获取准确NYSE日历
    if market_name == "US-Stock":
        try:
            import exchange_calendars as xcals
            cal = xcals.get_calendar("XNYS")
            session = cal.date_to_session(trigger_datetime.date(), direction="previous")
            prev_session = cal.previous_session(session)
            return prev_session.strftime(output_format)
        except Exception:
            # 兜底：跳过周末
            return _previous_business_day_simple(trigger_datetime).strftime(output_format)

    # 其他市场：统一使用简单周末跳过兜底
    return _previous_business_day_simple(trigger_datetime).strftime(output_format)


if __name__ == "__main__":
    print(get_current_datetime("2025-01-01 10:00:00"))
    print(get_previous_trading_date("2025-01-01 10:00:00"))
    print(get_previous_trading_date("2026-09-21 11:18:00", market_name="US-Stock"))
