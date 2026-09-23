"""
Data Summary Based On Finnhub + FMP for US Market
美股个股摘要工具：基于 FMP 日线 + Finnhub 基本面/新闻。
"""
import asyncio
import hashlib
from pathlib import Path
from pydantic import BaseModel, Field
from utils.fmp_utils import fmp_cached
from utils.finnhub_utils import finnhub_cached
from models.llm_model import GLOBAL_VISION_LLM
from tools.tool_utils import smart_tool
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

TOOL_HOME = Path(__file__).parent.resolve()
TOOL_CACHE = TOOL_HOME / "stock_summary_us_cache"


def _fmt_value(value, fmt: str = ".2f") -> str:
    try:
        if value is None:
            return "NA"
        if isinstance(value, float) and np.isnan(value):
            return "NA"
        return format(value, fmt)
    except Exception:
        return "NA"


def get_stock_name_by_code(symbol, market):
    """通过 Finnhub 公司资料获取股票名称"""
    try:
        if market == "US-Stock":
            profile = finnhub_cached.run('company_profile2', {'symbol': symbol}, verbose=False)
            if isinstance(profile, dict):
                return profile.get('name', symbol)
        return symbol
    except Exception:
        return symbol


def _fetch_us_kline(symbol: str, trigger_time: str, lookback_days: int = 365) -> pd.DataFrame:
    """Fetch US stock daily data using FMP historical price."""
    try:
        trigger_date_str = trigger_time.split(" ")[0]
        trigger_dt = datetime.strptime(trigger_date_str, "%Y-%m-%d")
        end_date = (trigger_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (trigger_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        df = fmp_cached.get_historical_price(symbol, from_date=start_date, to_date=end_date, verbose=False)
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.sort_values('date').reset_index(drop=True)
        return df
    except Exception as e:
        print(f"Failed to fetch K-line data for {symbol}: {e}")
        return pd.DataFrame()


def _compute_indicators(df: pd.DataFrame) -> dict:
    """Compute technical indicators."""
    out = {}
    if df.empty:
        return out

    closes = df["close"].astype(float)
    out["ma5"] = closes.rolling(5).mean().iloc[-1]
    out["ma10"] = closes.rolling(10).mean().iloc[-1]
    out["ma20"] = closes.rolling(20).mean().iloc[-1]

    # RSI(14)
    delta = closes.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(gain).rolling(14).mean()
    roll_down = pd.Series(loss).rolling(14).mean()
    rs = roll_up / (roll_down.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    out["rsi14"] = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else None

    # MACD (12,26,9)
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = (dif - dea) * 2
    out["macd_dif"] = float(dif.iloc[-1])
    out["macd_dea"] = float(dea.iloc[-1])
    out["macd_hist"] = float(macd.iloc[-1])

    # Bollinger (20, 2 std)
    ma20 = closes.rolling(20).mean()
    std20 = closes.rolling(20).std()
    out["boll_mid"] = float(ma20.iloc[-1]) if not np.isnan(ma20.iloc[-1]) else None
    out["boll_up"] = float((ma20 + 2 * std20).iloc[-1]) if not np.isnan(std20.iloc[-1]) else None
    out["boll_dn"] = float((ma20 - 2 * std20).iloc[-1]) if not np.isnan(std20.iloc[-1]) else None

    return out


def _describe_kline(df: pd.DataFrame, indicators: dict) -> str:
    """Describe K-line data."""
    if df.empty:
        return "无可用K线数据"

    last = df.iloc[-1]
    parts = [
        f"最新交易日: {last['date'].strftime('%Y-%m-%d') if hasattr(last['date'], 'strftime') else last['date']}",
        f"收盘: {last['close']} 开盘: {last['open']} 最高: {last['high']} 最低: {last['low']}",
        f"5/10/20日均线: {_fmt_value(indicators.get('ma5'))} / {_fmt_value(indicators.get('ma10'))} / {_fmt_value(indicators.get('ma20'))}",
        f"RSI14: {_fmt_value(indicators.get('rsi14'))}",
        f"MACD: DIF {_fmt_value(indicators.get('macd_dif'), '.3f')}, DEA {_fmt_value(indicators.get('macd_dea'), '.3f')}, Hist {_fmt_value(indicators.get('macd_hist'), '.3f')}",
        f"布林带: 上 {_fmt_value(indicators.get('boll_up'))}, 中 {_fmt_value(indicators.get('boll_mid'))}, 下 {_fmt_value(indicators.get('boll_dn'))}",
    ]
    return "\n".join([p for p in parts])


async def _get_financial_summary_async(symbol: str, trigger_time: str) -> str:
    """获取近期盈利摘要"""
    try:
        data = finnhub_cached.run('company_earnings', {'symbol': symbol}, verbose=False)
        if isinstance(data, list) and data:
            latest = data[0]
            return (
                f"财务摘要(最新季度 {latest.get('period', 'N/A')}): "
                f"预期 EPS {latest.get('estimate', 'N/A')}, 实际 EPS {latest.get('actual', 'N/A')}, "
                f" Surprise {latest.get('surprisePercent', 'N/A')}%"
            )
        return "财务摘要: 未获取到盈利数据"
    except Exception as e:
        return f"财务摘要获取失败: {str(e)}"


def _get_company_profile_summary(symbol: str) -> str:
    """获取公司行业/市值等摘要"""
    try:
        profile = finnhub_cached.run('company_profile2', {'symbol': symbol}, verbose=False)
        if not isinstance(profile, dict):
            return "公司资料: 无可用数据"
        return (
            f"公司资料: {profile.get('name', symbol)} ({profile.get('country', 'US')}), "
            f"行业 {profile.get('finnhubIndustry', 'N/A')}, "
            f"市值 {profile.get('marketCapitalization', 'N/A')}M, "
            f"流通股 {profile.get('shareOutstanding', 'N/A')}M"
        )
    except Exception as e:
        return f"公司资料获取失败: {str(e)}"


def _get_recent_news(symbol: str, trigger_time: str, days: int = 7, limit: int = 10) -> str:
    """获取 symbol 近 N 天新闻（Finnhub company_news）"""
    try:
        trigger_date_str = trigger_time.split(" ")[0]
        end_dt = datetime.strptime(trigger_date_str, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=days)
        data = finnhub_cached.run(
            'company_news',
            {
                'symbol': symbol,
                '_from': start_dt.strftime("%Y-%m-%d"),
                'to': end_dt.strftime("%Y-%m-%d"),
            },
            verbose=False,
        )
        if not isinstance(data, list) or not data:
            return "相关新闻: 无"
        data.sort(key=lambda x: x.get('datetime', 0), reverse=True)
        lines = [f"相关新闻（近 {days} 天，共 {len(data)} 条）:"]
        for item in data[:limit]:
            ts = item.get('datetime', 0)
            dt_str = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d') if ts else 'N/A'
            lines.append(f"  [{dt_str}] {item.get('source', 'N/A')}: {item.get('headline', '')}")
        return "\n".join(lines)
    except Exception as e:
        return f"相关新闻获取失败: {str(e)}"


async def get_all_stock_data(market: str, symbol: str, stock_name: str, trigger_time: str) -> dict:
    """Main data gathering function."""
    if market != "US-Stock":
        return {
            "kline_description": "暂不支持该市场",
            "technical_analysis": "",
            "financial_summary": "",
            "profile_summary": "",
            "news_summary": "",
            "stock_moneyflow_analysis": "",
            "intraday_chart_base64": None,
            "kline_chart_base64": None,
        }

    trigger_date = trigger_time.split(" ")[0]
    trigger_dt = datetime.strptime(trigger_date, "%Y-%m-%d")
    end_date = (trigger_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (trigger_dt - timedelta(days=90)).strftime("%Y-%m-%d")

    df = _fetch_us_kline(symbol, trigger_time)
    indicators = _compute_indicators(df) if not df.empty else {}
    kline_desc = _describe_kline(df, indicators)

    tech_desc = (
        "技术指标摘要: MA5/10/20="
        f"{_fmt_value(indicators.get('ma5'))}/"
        f"{_fmt_value(indicators.get('ma10'))}/"
        f"{_fmt_value(indicators.get('ma20'))}; "
        f"RSI14={_fmt_value(indicators.get('rsi14'))}; "
        f"MACD(DIF/DEA/Hist)={_fmt_value(indicators.get('macd_dif'), '.3f')}/"
        f"{_fmt_value(indicators.get('macd_dea'), '.3f')}/"
        f"{_fmt_value(indicators.get('macd_hist'), '.3f')}; "
        f"布林(上/中/下)={_fmt_value(indicators.get('boll_up'))}/"
        f"{_fmt_value(indicators.get('boll_mid'))}/"
        f"{_fmt_value(indicators.get('boll_dn'))}"
    ) if indicators else "技术指标不足，无法计算"

    financial_summary = await _get_financial_summary_async(symbol, trigger_time)
    profile_summary = _get_company_profile_summary(symbol)
    news_summary = _get_recent_news(symbol, trigger_time)

    return {
        "kline_description": kline_desc,
        "technical_analysis": tech_desc,
        "financial_summary": financial_summary,
        "profile_summary": profile_summary,
        "news_summary": news_summary,
        "stock_moneyflow_analysis": "资金流向分析: 当前数据源暂不直接提供个股资金流",
        "intraday_chart_base64": None,
        "kline_chart_base64": None,
    }


async def call_llm_for_comprehensive_analysis(prompt, intraday_chart_base64=None, kline_chart_base64=None):
    """Calls the LLM for a comprehensive analysis with text and images."""
    content = [{"type": "text", "text": prompt}]
    if intraday_chart_base64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{intraday_chart_base64}"}})
    if kline_chart_base64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{kline_chart_base64}"}})

    messages = [{"role": "user", "content": content}]
    response = await GLOBAL_VISION_LLM.a_run(messages, temperature=0.3, max_tokens=4000, verbose=False, thinking=False)
    return response.content


class StockSummaryInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company. For US-Stock use format like 'AAPL'.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


async def analyze_stock_basic_info(market, symbol, stock_name, trigger_time):
    """Main analysis function for US stocks using Finnhub + FMP."""
    print("📊  Fetching K-line & indicators via FMP...")
    all_data = await get_all_stock_data(market, symbol, stock_name, trigger_time)
    print("✅  Data fetching complete.")

    prompt_template = f"""请为{stock_name}({symbol})生成一份基于可用数据的股票技术分析报告。
分析时间: {trigger_time}

=== 数据输入（基于 Finnhub + FMP 可用数据）===
【K线数据与关键指标】
{all_data['kline_description']}
{all_data['technical_analysis']}

【公司资料】
{all_data['profile_summary']}

【财务基本面数据】
{all_data['financial_summary']}

【新闻事件数据】
{all_data['news_summary']}

【资金流向数据】
{all_data['stock_moneyflow_analysis']}

=== 分析要求 ===
1. 概述近期价格走势与波动特征
2. 结合均线、RSI、MACD、布林带等指标给出技术判断
3. 标注关键支撑/阻力位与潜在风险
4. 说明数据局限性（基于 Finnhub + FMP 可用数据）
5. 报告请控制在 400 个英文单词以内，重点突出结论和风险，不要流水账。
"""
    if market == "US-Stock":
        prompt_template += "\n\nPlease output the US stock analysis report in English, concise and within 400 words."

    print("🤖  Starting LLM technical analysis...")
    try:
        analysis_result = await call_llm_for_comprehensive_analysis(
            prompt_template,
            all_data['intraday_chart_base64'],
            all_data['kline_chart_base64'],
        )
        return analysis_result
    except Exception as e:
        print(f"❌  LLM analysis failed: {e}")
        return f'LLM分析失败: {e}'


@smart_tool(
    description="""Get stock summarized technical info (Finnhub + FMP-based). 仅支持美股，返回基于K线与技术指标的分析报告。""",
    args_schema=StockSummaryInput,
    max_output_len=4000,
    timeout_seconds=120.0
)
async def stock_summary(market: str, symbol: str, trigger_time: str) -> str:
    """Finnhub + FMP-based stock summary tool."""
    if market not in ["US-Stock"]:
        return f"错误：当前模式仅支持美股(US-Stock)，传入: '{market}'。"

    if not TOOL_CACHE.exists():
        TOOL_CACHE.mkdir(parents=True, exist_ok=True)

    cache_key = f"{market}_{symbol}_{trigger_time.split(' ')[0]}"
    cache_file = TOOL_CACHE / f"{hashlib.md5(cache_key.encode()).hexdigest()}.txt"

    if cache_file.exists():
        return cache_file.read_text()
    else:
        stock_name = get_stock_name_by_code(symbol, market)
        result = await analyze_stock_basic_info(market, symbol, stock_name, trigger_time)
        cache_file.write_text(result)
        return result


if __name__ == "__main__":
    result = asyncio.run(stock_summary.ainvoke(
        {"market": "US-Stock", "symbol": "TSLA", "trigger_time": "2026-09-23 09:00:00"}))
    print(result)
