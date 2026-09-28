"""
A 股实时行情与技术分析工具
为 Research Agent 提供实时行情快照、技术指标（KDJ/MACD/RSI/均线）和分时资金流数据。
"""
import asyncio
import time
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
from pydantic import BaseModel, Field

from tools.tool_utils import smart_tool
from utils.akshare_utils import akshare_cached


def _base_symbol(symbol: str) -> str:
    """去掉 .SH/.SZ 后缀"""
    return symbol.split(".")[0]


def _market_prefix(symbol: str) -> str:
    """返回 sh/sz 前缀"""
    base = _base_symbol(symbol)
    return "sh" if base.startswith("6") else "sz"


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


def _calc_kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    """计算 KDJ 指标"""
    low_list = df["low"].rolling(window=n, min_periods=n).min()
    high_list = df["high"].rolling(window=n, min_periods=n).max()
    rsv = (df["close"] - low_list) / (high_list - low_list) * 100
    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    df["K"] = k
    df["D"] = d
    df["J"] = j
    return df


def _calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """计算 MACD 指标"""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["DIF"] = ema_fast - ema_slow
    df["DEA"] = df["DIF"].ewm(span=signal, adjust=False).mean()
    df["MACD"] = 2 * (df["DIF"] - df["DEA"])
    return df


def _calc_rsi(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """计算 RSI 指标"""
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=n, min_periods=n).mean()
    avg_loss = loss.rolling(window=n, min_periods=n).mean()
    rs = avg_gain / avg_loss
    df[f"RSI{n}"] = 100 - (100 / (1 + rs))
    return df


def _calc_ma(df: pd.DataFrame) -> pd.DataFrame:
    """计算常用均线"""
    for ma in [5, 10, 20, 30, 60]:
        df[f"MA{ma}"] = df["close"].rolling(window=ma, min_periods=1).mean()
    return df


class RealtimeQuoteInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company. Only one symbol is allowed.")


class TechnicalIndicatorInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company. Only one symbol is allowed.")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS.")


class IntradayFundFlowInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company. Only one symbol is allowed.")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get real-time snapshot quote for an A-share stock (latest price, change, volume, etc.).",
    args_schema=RealtimeQuoteInput,
    max_output_len=1200,
    timeout_seconds=20.0,
)
async def realtime_quote(market: str, symbol: str) -> dict:
    """获取 A 股实时行情快照"""
    if market != "CN-Stock":
        return {"error": "Market not supported. Only CN-Stock is supported."}

    base = _base_symbol(symbol)
    try:
        df = _fetch_with_retry("stock_zh_a_spot", {}, retries=2, delay=0.5)
        row = df[df["代码"] == base]
        if row.empty:
            return {"error": f"No realtime quote found for {symbol}. Market may be closed or symbol invalid."}

        row = row.iloc[0]
        result = {
            "symbol": symbol,
            "name": str(row.get("名称", "")),
            "latest_price": float(row.get("最新价", 0)) if pd.notna(row.get("最新价")) else None,
            "change_amount": float(row.get("涨跌额", 0)) if pd.notna(row.get("涨跌额")) else None,
            "change_percent": float(row.get("涨跌幅", 0)) if pd.notna(row.get("涨跌幅")) else None,
            "open": float(row.get("今开", 0)) if pd.notna(row.get("今开")) else None,
            "high": float(row.get("最高", 0)) if pd.notna(row.get("最高")) else None,
            "low": float(row.get("最低", 0)) if pd.notna(row.get("最低")) else None,
            "pre_close": float(row.get("昨收", 0)) if pd.notna(row.get("昨收")) else None,
            "volume": int(row.get("成交量", 0)) if pd.notna(row.get("成交量")) else None,
            "turnover": float(row.get("成交额", 0)) if pd.notna(row.get("成交额")) else None,
            "bid": float(row.get("买入", 0)) if pd.notna(row.get("买入")) else None,
            "ask": float(row.get("卖出", 0)) if pd.notna(row.get("卖出")) else None,
            "timestamp": str(row.get("时间戳", "")),
        }
        return {"result": result}
    except Exception as e:
        return {"error": f"Failed to fetch realtime quote for {symbol}: {e}"}


@smart_tool(
    description="Get technical indicators for an A-share stock: KDJ, MACD, RSI and moving averages (MA5/10/20/30/60).",
    args_schema=TechnicalIndicatorInput,
    max_output_len=2000,
    timeout_seconds=15.0,
)
async def technical_indicators(market: str, symbol: str, trigger_time: str) -> dict:
    """获取 A 股技术指标"""
    if market != "CN-Stock":
        return {"error": "Market not supported. Only CN-Stock is supported."}
    if not trigger_time:
        return {"error": "trigger_time is required"}

    base = _base_symbol(symbol)
    trigger_date = datetime.strptime(trigger_time.split(" ")[0], "%Y-%m-%d")
    end_date = (trigger_date - timedelta(days=1)).strftime("%Y%m%d")
    start_date = (trigger_date - timedelta(days=120)).strftime("%Y%m%d")

    try:
        df = _fetch_with_retry(
            "stock_zh_a_hist",
            {
                "symbol": base,
                "period": "daily",
                "start_date": start_date,
                "end_date": end_date,
                "adjust": "qfq",
            },
            retries=3,
            delay=0.8,
        )
        if df is None or len(df) == 0:
            return {"error": f"No historical price data for {symbol}"}

        # 标准化列名
        df = df.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
            }
        )
        df = _calc_ma(df)
        df = _calc_kdj(df)
        df = _calc_macd(df)
        df = _calc_rsi(df)

        latest = df.iloc[-1]
        result = {
            "symbol": symbol,
            "latest_trading_day": str(latest.get("date", "")),
            "close": float(latest["close"]),
            "MA": {f"MA{ma}": float(latest[f"MA{ma}"]) for ma in [5, 10, 20, 30, 60]},
            "KDJ": {
                "K": round(float(latest["K"]), 3),
                "D": round(float(latest["D"]), 3),
                "J": round(float(latest["J"]), 3),
            },
            "MACD": {
                "DIF": round(float(latest["DIF"]), 4),
                "DEA": round(float(latest["DEA"]), 4),
                "MACD": round(float(latest["MACD"]), 4),
            },
            "RSI": {"RSI14": round(float(latest["RSI14"]), 3)},
            "recent_3_days": df[["date", "open", "high", "low", "close", "volume", "MA5", "MA10", "K", "D", "J", "DIF", "DEA", "MACD", "RSI14"]]
            .tail(3)
            .astype({"date": "str"})
            .to_dict(orient="records"),
        }
        return {"result": result}
    except Exception as e:
        return {"error": f"Failed to calculate technical indicators for {symbol}: {e}"}


@smart_tool(
    description="Get intraday 1-minute price/volume data and latest fund flow summary for an A-share stock.",
    args_schema=IntradayFundFlowInput,
    max_output_len=2500,
    timeout_seconds=15.0,
)
async def intraday_fund_flow(market: str, symbol: str, trigger_time: str) -> dict:
    """获取 A 股分时行情和资金流摘要"""
    if market != "CN-Stock":
        return {"error": "Market not supported. Only CN-Stock is supported."}
    if not trigger_time:
        return {"error": "trigger_time is required"}

    base = _base_symbol(symbol)
    trigger_dt = datetime.strptime(trigger_time, "%Y-%m-%d %H:%M:%S")
    start_dt = trigger_dt - timedelta(days=3)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = trigger_dt.strftime("%Y-%m-%d %H:%M:%S")

    result = {"symbol": symbol}

    # 1. 分时行情
    try:
        df_min = _fetch_with_retry(
            "stock_zh_a_hist_min_em",
            {
                "symbol": base,
                "period": "1",
                "adjust": "qfq",
                "start_date": start_str,
                "end_date": end_str,
            },
            retries=2,
            delay=0.5,
        )
        if df_min is not None and len(df_min) > 0:
            latest_min = df_min.iloc[-1]
            result["latest_minute"] = {
                "time": str(latest_min.get("时间", "")),
                "open": float(latest_min.get("开盘", 0)) if pd.notna(latest_min.get("开盘")) else None,
                "close": float(latest_min.get("收盘", 0)) if pd.notna(latest_min.get("收盘")) else None,
                "high": float(latest_min.get("最高", 0)) if pd.notna(latest_min.get("最高")) else None,
                "low": float(latest_min.get("最低", 0)) if pd.notna(latest_min.get("最低")) else None,
                "volume": int(latest_min.get("成交量", 0)) if pd.notna(latest_min.get("成交量")) else None,
                "turnover": float(latest_min.get("成交额", 0)) if pd.notna(latest_min.get("成交额")) else None,
            }
            result["intraday_summary"] = {
                "total_minutes": len(df_min),
                "avg_price": round(float(df_min["收盘"].mean()), 3) if "收盘" in df_min.columns else None,
                "total_volume": int(df_min["成交量"].sum()) if "成交量" in df_min.columns else None,
                "total_turnover": float(df_min["成交额"].sum()) if "成交额" in df_min.columns else None,
                "first_30min_volume": int(df_min.head(30)["成交量"].sum()) if "成交量" in df_min.columns and len(df_min) >= 30 else None,
            }
            # 最近 30 分钟数据摘要
            recent = df_min.tail(30)[["时间", "收盘", "成交量", "成交额"]] if len(df_min) >= 30 else df_min[["时间", "收盘", "成交量", "成交额"]]
            result["recent_30_minutes"] = recent.to_dict(orient="records")
    except Exception as e:
        result["intraday_error"] = str(e)

    # 2. 资金流（日级）
    try:
        prefix = _market_prefix(symbol)
        sina_symbol = f"{prefix}{base}"
        df_flow = _fetch_with_retry(
            "stock_fund_flow_individual",
            {},
            retries=2,
            delay=0.5,
        )
        row = df_flow[df_flow["代码"] == base] if "代码" in df_flow.columns else df_flow[df_flow["股票代码"] == base]
        if not row.empty:
            row = row.iloc[0]
            result["fund_flow"] = {
                "main_inflow": float(row.get("主力净流入", 0)) if pd.notna(row.get("主力净流入")) else None,
                "main_inflow_ratio": float(row.get("主力净流入占比", 0)) if pd.notna(row.get("主力净流入占比")) else None,
                "super_large_inflow": float(row.get("超大单净流入", 0)) if pd.notna(row.get("超大单净流入")) else None,
                "large_inflow": float(row.get("大单净流入", 0)) if pd.notna(row.get("大单净流入")) else None,
                "medium_inflow": float(row.get("中单净流入", 0)) if pd.notna(row.get("中单净流入")) else None,
                "small_inflow": float(row.get("小单净流入", 0)) if pd.notna(row.get("小单净流入")) else None,
            }
    except Exception as e:
        result["fund_flow_error"] = str(e)

    return {"result": result}


if __name__ == "__main__":
    async def _test():
        print(await realtime_quote.ainvoke({"market": "CN-Stock", "symbol": "600026.SH"}))
        print(await technical_indicators.ainvoke({"market": "CN-Stock", "symbol": "600026.SH", "trigger_time": "2026-09-28 09:30:00"}))
        print(await intraday_fund_flow.ainvoke({"market": "CN-Stock", "symbol": "600026.SH", "trigger_time": "2026-09-28 09:30:00"}))

    asyncio.run(_test())
