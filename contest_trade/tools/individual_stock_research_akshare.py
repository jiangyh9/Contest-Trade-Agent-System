"""
A 股个股深度研究工具
输入一个 A 股代码，自动聚合 K线、技术指标、实时行情、分时资金流、财务数据和新闻，
调用 LLM 生成一份个股研究报告，供 Research Agent 使用。
"""
import asyncio
import ast
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from models.llm_model import GLOBAL_LLM
from tools.corp_info_akshare import company_financial_info
from tools.search_web import search_web
from tools.technical_analysis_akshare import (
    intraday_fund_flow,
    realtime_quote,
    technical_indicators,
)
from tools.tool_utils import smart_tool
from utils.akshare_utils import akshare_cached


def _extract_data_from_tool_response(resp) -> dict:
    """从 smart_tool 包装后的 {'success':..., 'data':...} 响应中提取真实数据"""
    if not isinstance(resp, dict):
        return resp if isinstance(resp, dict) else {"raw": resp}

    # 如果外层已经有 result，直接返回
    if "result" in resp and len(resp) == 1:
        return resp.get("result", {})

    # 否则从 data 字段解析
    if "data" in resp:
        data = resp["data"]
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
            except Exception:
                try:
                    parsed = ast.literal_eval(data)
                except Exception:
                    return {"raw": data}
            # 如果解析后只有 result 键，返回 result 内容
            if isinstance(parsed, dict) and list(parsed.keys()) == ["result"]:
                return parsed.get("result", {})
            return parsed if isinstance(parsed, dict) else {"raw": data}
        return data if isinstance(data, dict) else {"raw": data}

    return resp

TOOL_HOME = Path(__file__).parent.resolve()
TOOL_CACHE = TOOL_HOME / "individual_stock_research_akshare_cache"


def _base_symbol(symbol: str) -> str:
    return symbol.split(".")[0]


def _fmt(value, fmt: str = ".2f") -> str:
    try:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return "NA"
        return format(value, fmt)
    except Exception:
        return "NA"


def _get_stock_name(symbol: str) -> str:
    try:
        base = _base_symbol(symbol)
        df = akshare_cached.run("stock_info_a_code_name", func_kwargs={}, verbose=False)
        if df is not None and not df.empty:
            if "code" in df.columns and "name" in df.columns:
                match = df[df["code"] == base]
                if not match.empty:
                    return str(match.iloc[0]["name"])
        return symbol
    except Exception:
        return symbol


def _fetch_kline(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    base = _base_symbol(symbol)
    try:
        df = akshare_cached.run(
            "stock_zh_a_hist",
            {
                "symbol": base,
                "period": "daily",
                "start_date": start_date,
                "end_date": end_date,
                "adjust": "qfq",
            },
            verbose=False,
        )
        if df is None or len(df) == 0:
            return pd.DataFrame()
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
            "换手率": "turnover_rate",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception as e:
        print(f"K-line fetch failed: {e}")
        return pd.DataFrame()


def _describe_trend(df: pd.DataFrame) -> str:
    if df.empty or len(df) < 5:
        return "K线数据不足"
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    week_ago = df.iloc[-5] if len(df) >= 5 else df.iloc[0]
    change_1d = latest.get("change_percent", 0) or 0
    change_5d = (latest["close"] / week_ago["close"] - 1) * 100 if week_ago["close"] else 0
    vol_avg_5 = df.tail(5)["volume"].mean()
    vol_avg_20 = df.tail(20)["volume"].mean() if len(df) >= 20 else df["volume"].mean()
    return (
        f"最新收盘价 {_fmt(latest.get('close'))}，"
        f"较前日涨跌 {_fmt(change_1d)}%，"
        f"近5日累计涨跌 {_fmt(change_5d)}%；"
        f"最新成交量 {int(latest.get('volume', 0))}，"
        f"5日均量 {int(vol_avg_5)}，"
        f"20日均量 {int(vol_avg_20)}"
    )


async def _gather_data(market: str, symbol: str, trigger_time: str) -> dict:
    """聚合个股多维数据（并行调用，控制总耗时）"""
    trigger_date = trigger_time.split(" ")[0]
    trigger_dt = datetime.strptime(trigger_date, "%Y-%m-%d")
    end_date = (trigger_dt - timedelta(days=1)).strftime("%Y%m%d")
    start_date = (trigger_dt - timedelta(days=180)).strftime("%Y%m%d")

    data = {"symbol": symbol, "stock_name": _get_stock_name(symbol), "trigger_time": trigger_time}

    # 1. K线
    df = _fetch_kline(symbol, start_date, end_date)
    data["kline_df"] = df
    data["trend"] = _describe_trend(df)

    # 2/3/4/6 并行调用：技术指标、实时行情、分时资金流、新闻
    async def _get_ti():
        try:
            ti = await technical_indicators.ainvoke({"market": market, "symbol": symbol, "trigger_time": trigger_time})
            return _extract_data_from_tool_response(ti)
        except Exception as e:
            return {"error": str(e)}

    async def _get_rt():
        try:
            rt = await realtime_quote.ainvoke({"market": market, "symbol": symbol})
            return _extract_data_from_tool_response(rt)
        except Exception as e:
            return {"error": str(e)}

    async def _get_ff():
        try:
            ff = await intraday_fund_flow.ainvoke({"market": market, "symbol": symbol, "trigger_time": trigger_time})
            return _extract_data_from_tool_response(ff)
        except Exception as e:
            return {"error": str(e)}

    async def _get_news():
        try:
            news = await search_web.ainvoke({"query": data["stock_name"], "topk": 8, "trigger_time": trigger_time})
            extracted = _extract_data_from_tool_response(news)
            if isinstance(extracted, list):
                return extracted
            if isinstance(extracted, dict) and "raw" in extracted:
                return [extracted["raw"]]
            return [str(news)]
        except Exception as e:
            return [f"新闻获取失败: {e}"]

    ti_task = asyncio.create_task(_get_ti())
    rt_task = asyncio.create_task(_get_rt())
    ff_task = asyncio.create_task(_get_ff())
    news_task = asyncio.create_task(_get_news())

    data["indicators"] = await ti_task
    data["realtime"] = await rt_task
    data["fund_flow"] = await ff_task
    data["news"] = await news_task

    # 5. 财务数据：直接取最新季度利润表，避免 company_financial_info 内部再调 LLM
    try:
        base = _base_symbol(symbol)
        # 尝试最近 4 个季度
        periods = []
        year, month = trigger_dt.year, trigger_dt.month
        for _ in range(4):
            if month >= 10:
                periods.append(f"{year}0930")
                month = 6
            elif month >= 7:
                periods.append(f"{year}0630")
                month = 3
            elif month >= 4:
                periods.append(f"{year}0331")
                month = 12
                year -= 1
            else:
                periods.append(f"{year}1231")
                month = 9
                year -= 1

        fin_summary = ""
        for period in periods:
            try:
                df = akshare_cached.run("stock_lrb_em", {"date": period}, verbose=False)
                if df is not None and not df.empty:
                    row = df[df["股票代码"] == base]
                    if not row.empty:
                        fin_summary = row.to_markdown()
                        break
            except Exception:
                continue
        data["financial"] = {"summary": fin_summary[:1500] if fin_summary else "未获取到最新季度利润表数据"}
    except Exception as e:
        data["financial"] = {"error": str(e)}

    return data


def _serialize(data: dict) -> str:
    """把聚合数据序列化成 LLM 可读的文本"""
    lines = []
    lines.append(f"## 个股：{data['stock_name']} ({data['symbol']})")
    lines.append(f"分析时间：{data['trigger_time']}")
    lines.append("")

    lines.append("### 1. 价格走势")
    lines.append(data["trend"])
    lines.append("")

    rt = data.get("realtime", {})
    if rt and "error" not in rt:
        lines.append("### 2. 实时行情快照")
        lines.append(
            f"最新价 {_fmt(rt.get('latest_price'))}，"
            f"涨跌额 {_fmt(rt.get('change_amount'))}，"
            f"涨跌幅 {_fmt(rt.get('change_percent'))}%，"
            f"今开 {_fmt(rt.get('open'))}，"
            f"最高 {_fmt(rt.get('high'))}，"
            f"最低 {_fmt(rt.get('low'))}，"
            f"昨收 {_fmt(rt.get('pre_close'))}，"
            f"成交量 {rt.get('volume')}"
        )
        lines.append("")

    ind = data.get("indicators", {})
    if ind and "error" not in ind:
        lines.append("### 3. 技术指标")
        ma = ind.get("MA", {})
        lines.append(
            f"MA5/10/20/30/60: {_fmt(ma.get('MA5'))} / {_fmt(ma.get('MA10'))} / "
            f"{_fmt(ma.get('MA20'))} / {_fmt(ma.get('MA30'))} / {_fmt(ma.get('MA60'))}"
        )
        kdj = ind.get("KDJ", {})
        lines.append(f"KDJ: K={_fmt(kdj.get('K'))}, D={_fmt(kdj.get('D'))}, J={_fmt(kdj.get('J'))}")
        macd = ind.get("MACD", {})
        lines.append(
            f"MACD: DIF={_fmt(macd.get('DIF'), '.3f')}, "
            f"DEA={_fmt(macd.get('DEA'), '.3f')}, "
            f"MACD={_fmt(macd.get('MACD'), '.3f')}"
        )
        rsi = ind.get("RSI", {})
        lines.append(f"RSI14: {_fmt(rsi.get('RSI14'))}")
        lines.append("")

    ff = data.get("fund_flow", {})
    if ff and "error" not in ff:
        lines.append("### 4. 分时与资金流")
        latest = ff.get("latest_minute", {})
        lines.append(
            f"最新分钟 {latest.get('time')} 收盘 {_fmt(latest.get('close'))} 成交量 {latest.get('volume')}"
        )
        summary = ff.get("intraday_summary", {})
        if summary:
            lines.append(
                f"日内均价 {_fmt(summary.get('avg_price'))}，"
                f"总成交 {summary.get('total_volume')}，"
                f"总成交额 {_fmt(summary.get('total_turnover'))}"
            )
        flow = ff.get("fund_flow", {})
        if flow:
            lines.append(
                f"主力净流入 {_fmt(flow.get('main_inflow'))}，"
                f"主力净流入占比 {_fmt(flow.get('main_inflow_ratio'))}%，"
                f"超大单 {_fmt(flow.get('super_large_inflow'))}，"
                f"大单 {_fmt(flow.get('large_inflow'))}，"
                f"中单 {_fmt(flow.get('medium_inflow'))}，"
                f"小单 {_fmt(flow.get('small_inflow'))}"
            )
        lines.append("")

    fin = data.get("financial", {})
    if fin and "error" not in fin:
        lines.append("### 5. 财务概况")
        lines.append(fin.get("summary", "")[:1500])
        lines.append("")
    elif fin and "error" in fin:
        lines.append("### 5. 财务概况")
        lines.append(f"财务数据获取失败：{fin['error']}")
        lines.append("")

    news = data.get("news", [])
    if news:
        lines.append("### 6. 相关新闻")
        for item in news[:8]:
            if isinstance(item, dict):
                title = item.get("title", "")
                snippet = item.get("snippet", "")
                t = item.get("time", "")
                lines.append(f"- **{title}**（{t}）：{snippet[:200]}")
            else:
                lines.append(f"- {str(item)[:300]}")
        lines.append("")

    return "\n".join(lines)


async def _call_llm_analysis(stock_name: str, symbol: str, trigger_time: str, context: str) -> str:
    prompt = f"""你是一位专业的 A 股个股研究员。请基于以下数据为 {stock_name}({symbol}) 生成一份个股研究报告。
分析时间：{trigger_time}

{context}

=== 报告要求 ===
1. 技术面分析：结合 K线走势、均线排列、KDJ/MACD/RSI 给出判断（超买/超卖、金叉死叉、趋势方向）。
2. 资金面分析：结合分时成交、主力资金流向判断短期资金态度。
3. 基本面分析：基于财务数据给出盈利、资产负债、现金流的关键结论（如数据不可用请说明）。
4. 消息面分析：结合新闻提炼催化事件或风险事件。
5. 综合判断：给出看多/看空/中性的明确观点，并给出关键价位（支撑/阻力）。
6. 风险提示：列出真实风险点，禁止写"未能获取实时行情"或"工具接口不足"这类免责声明。

请用中文输出，结构清晰，控制在 800 字以内，重点突出结论和风险。
"""
    messages = [{"role": "user", "content": prompt}]
    response = await GLOBAL_LLM.a_run(messages, temperature=0.3, max_tokens=4000, verbose=False, thinking=False)
    return response.content


class IndividualStockResearchInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company. For CN-Stock use format like '600519.SH'.")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="""Conduct in-depth research on a single A-share stock. Returns a comprehensive report covering technical indicators, realtime quote, intraday fund flow, financial data and news. Use this when the user wants a per-stock analysis or when you need to verify a specific stock before submitting a signal.""",
    args_schema=IndividualStockResearchInput,
    max_output_len=5000,
    timeout_seconds=180.0,
)
async def individual_stock_research(market: str, symbol: str, trigger_time: str) -> str:
    """A 股个股深度研究工具"""
    if market != "CN-Stock":
        return f"错误：当前工具仅支持 A 股(CN-Stock)，传入: '{market}'。"

    if not TOOL_CACHE.exists():
        TOOL_CACHE.mkdir(parents=True, exist_ok=True)

    cache_key = f"{market}_{symbol}_{trigger_time.split(' ')[0]}"
    cache_file = TOOL_CACHE / f"{hashlib.md5(cache_key.encode()).hexdigest()}.txt"
    if cache_file.exists():
        return cache_file.read_text()

    stock_name = _get_stock_name(symbol)
    print(f"🔍 开始个股深度研究：{stock_name} ({symbol}) ...")
    data = await _gather_data(market, symbol, trigger_time)
    context = _serialize(data)
    result = await _call_llm_analysis(stock_name, symbol, trigger_time, context)
    cache_file.write_text(result, encoding="utf-8")
    return result


if __name__ == "__main__":
    result = asyncio.run(
        individual_stock_research.ainvoke(
            {"market": "CN-Stock", "symbol": "600519.SH", "trigger_time": "2026-09-28 09:30:00"}
        )
    )
    print(result)
