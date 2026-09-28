"""
本地 MCP Server：把 A 股 4 个 Data Source 封装成 MCP Tool。

启动：
    python local_mcp_server.py

SSE 端点：
    http://127.0.0.1:8000/server/mcp/a_share_analysis/sse
"""

import sys
import asyncio
from datetime import datetime

sys.dont_write_bytecode = True

from mcp.server.mcpserver import MCPServer
import pandas as pd

from contest_trade.data_source.sina_news_crawl import SinaNewsCrawl
from contest_trade.data_source.thx_news_crawl import ThxNewsCrawl
from contest_trade.data_source.price_market_akshare import PriceMarketAkshare
from contest_trade.data_source.hot_money_akshare import HotMoneyAkshare
from contest_trade.models.llm_model import LLMModel, LLMModelConfig
from contest_trade.tools.individual_stock_research_akshare import (
    _gather_data,
    _get_stock_name,
    _serialize,
)
from contest_trade.tools.stock_symbol_search_akshare import get_stock_basic_akshare, calculate_match_score


# Skill / MCP 专用 LLM，不影响本地 CLI 的 config.yaml
SKILL_LLM = LLMModel(LLMModelConfig(
    provider="openai",
    model_name="internal-qwen3.6-35b-a3b",
    api_key="b2a07a6d-dc18-418d-9525-c3fb216acfb2",
    base_url="http://llm.smart-zone-dev.gf.com.cn/api/oai/v1",
))


def _resolve_trigger_time(trigger_time: str | None) -> str:
    if trigger_time:
        return trigger_time
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _df_to_result(df: pd.DataFrame) -> dict:
    """把 DataFrame 转成 MCP tool 返回结构。"""
    return {
        "success": True,
        "count": len(df),
        "data": df.to_dict(orient="records"),
    }


NEWS_SUMMARY_PROMPT = """你是 A 股市场新闻分析助手。请对以下{source_name}新闻进行摘要和归纳。

要求：
1. 总结市场整体情绪和主要关注点
2. 提炼重要的宏观政策、行业动态、公司新闻
3. 列出主要涉及的板块和个股（如有）
4. 字数控制在 800 字以内

新闻内容：
{news_text}

请输出结构化的中文摘要："""


async def _summarize_news(df: pd.DataFrame, source_name: str, trigger_time: str) -> dict:
    """对新闻 DataFrame 做 LLM 摘要，返回统一格式。"""
    if df.empty:
        result_df = pd.DataFrame([{
            "title": f"{source_name}新闻摘要",
            "content": f"未获取到{source_name}新闻。",
            "pub_time": trigger_time,
            "url": None
        }])
        return _df_to_result(result_df)

    # 按时间倒序，取最新 50 条
    df = df.sort_values("pub_time", ascending=False).head(50).reset_index(drop=True)

    news_text = ""
    for _, row in df.iterrows():
        title = str(row.get("title", "")).strip()
        pub_time = str(row.get("pub_time", "")).strip()
        content = str(row.get("content", "")).strip()[:300]
        news_text += f"标题：{title}\n时间：{pub_time}\n摘要：{content}\n\n"

    prompt = NEWS_SUMMARY_PROMPT.format(source_name=source_name, news_text=news_text)
    messages = [{"role": "user", "content": prompt}]

    try:
        response = await SKILL_LLM.a_run(messages, temperature=0.7, max_tokens=1500)
        summary = response.content.strip()
    except Exception as e:
        summary = f"{source_name}新闻摘要生成失败：{type(e).__name__}: {e}"

    result_df = pd.DataFrame([{
        "title": f"{source_name}新闻摘要",
        "content": summary,
        "pub_time": trigger_time,
        "url": None
    }])
    return _df_to_result(result_df)


async def _extract_summary(result: dict) -> str:
    """从 MCP tool 返回结构里取出 content。"""
    data = (result or {}).get("data") or []
    if not data:
        return ""
    return str(data[0].get("content") or "").strip()


async def _build_market_background(trigger_time: str) -> str:
    """个股分析用的市场背景：并发取 4 路摘要。Data Source 自带按 trigger_time 缓存。"""
    sina_task = asyncio.create_task(sina_news_summary(trigger_time))
    thx_task = asyncio.create_task(thx_news_summary(trigger_time))
    market_task = asyncio.create_task(a_share_market_overview(trigger_time))
    hot_task = asyncio.create_task(a_share_hot_money(trigger_time))

    sina_text = thx_text = market_text = hot_text = ""
    try:
        sina_text = await _extract_summary(await sina_task)
    except Exception as e:
        sina_text = f"新浪新闻摘要获取失败：{type(e).__name__}: {e}"
    try:
        thx_text = await _extract_summary(await thx_task)
    except Exception as e:
        thx_text = f"同花顺资讯摘要获取失败：{type(e).__name__}: {e}"
    try:
        market_text = await _extract_summary(await market_task)
    except Exception as e:
        market_text = f"大盘走势获取失败：{type(e).__name__}: {e}"
    try:
        hot_text = await _extract_summary(await hot_task)
    except Exception as e:
        hot_text = f"热钱资金获取失败：{type(e).__name__}: {e}"

    return (
        "<market_information>\n"
        f"<source>sina_news_summary</source>\n<content>{sina_text}</content>\n"
        f"<source>thx_news_summary</source>\n<content>{thx_text}</content>\n"
        f"<source>a_share_market_overview</source>\n<content>{market_text}</content>\n"
        f"<source>a_share_hot_money</source>\n<content>{hot_text}</content>\n"
        "</market_information>"
    )


def _resolve_symbol(query: str) -> tuple[str, str]:
    """把用户输入的代码或名称解析成 (symbol, name)。"""
    q = (query or "").strip()
    if not q:
        raise ValueError("缺少股票代码或名称")

    base = q.split(".")[0]
    if base.isdigit() and len(base) == 6:
        name = _get_stock_name(base)
        if base.startswith(("6", "9")):
            return f"{base}.SH", name
        return f"{base}.SZ", name

    df = get_stock_basic_akshare()
    if df is None or df.empty:
        raise ValueError(f"无法解析股票：{q}")

    scored = []
    for _, row in df.iterrows():
        ts_code = str(row.get("ts_code", ""))
        name = str(row.get("name", ""))
        match_type, score = calculate_match_score(q, ts_code, name)
        if score > 0:
            scored.append((score, match_type, ts_code, name))
    if not scored:
        raise ValueError(f"未找到匹配股票：{q}")
    scored.sort(key=lambda x: x[0], reverse=True)
    _, _, ts_code, name = scored[0]
    code = ts_code.split(".")[0] if "." in ts_code else ts_code
    if code.startswith(("6", "9")):
        return f"{code}.SH", name
    if code.startswith(("0", "3")):
        return f"{code}.SZ", name
    return ts_code, name


STOCK_ANALYSIS_PROMPT = """你是 A 股个股分析助手。请基于市场背景和个股数据，对 {stock_name}({symbol}) 做利好/利空对照分析。
分析时间：{trigger_time}

<background_information>
{background}
</background_information>

<stock_data>
{stock_data}
</stock_data>

输出要求：
1. 只做分析，不给投资建议。禁止出现买入、卖出、加仓、减仓、持有、看多、看空、中性评级、目标价、仓位、布局、建议关注等表述。
2. 必须同时写利好因素和利空因素，每条都要能对应到上面的数据；没有数据就写进“待观察与不确定点”，不要编造。
3. 支撑/阻力如果提到，只能作为技术事实描述，不能写成操作位。
4. 不要使用投资信念、风险偏好、持仓天数等决策口径。
5. 字数控制在 1000 字以内。

请严格按以下结构用中文输出：

# {stock_name} 分析（{trigger_time}）

## 一、标的与市场背景
说明大盘、新闻、资金面与该股的关系，只陈述事实。

## 二、利好因素
分基本面 / 技术面 / 资金面 / 消息面列出。

## 三、利空因素
分基本面 / 技术面 / 资金面 / 消息面列出。

## 四、待观察与不确定点
数据缺失、口径冲突、尚未兑现的事件。

## 五、分析边界
本报告不构成投资建议，不给出买入/卖出/持有判断，不预测目标价。
"""


app = MCPServer(
    name="a_share_analysis",
    title="A 股市场综合分析",
    description="提供新闻、大盘、热钱资金流和个股利好/利空分析",
)


@app.tool(name="sina_news_summary", description="获取新浪财经新闻摘要")
async def sina_news_summary(trigger_time: str | None = None) -> dict:
    """获取新浪财经新闻摘要。"""
    t = _resolve_trigger_time(trigger_time)
    df = await SinaNewsCrawl().get_data(t)
    return await _summarize_news(df, "新浪财经", t)


@app.tool(name="thx_news_summary", description="获取同花顺股票资讯摘要")
async def thx_news_summary(trigger_time: str | None = None) -> dict:
    """获取同花顺股票资讯摘要。"""
    t = _resolve_trigger_time(trigger_time)
    df = await ThxNewsCrawl().get_data(t)
    return await _summarize_news(df, "同花顺", t)


@app.tool(name="a_share_market_overview", description="获取 A 股大盘走势分析")
async def a_share_market_overview(trigger_time: str | None = None) -> dict:
    """获取 A 股大盘走势分析。"""
    t = _resolve_trigger_time(trigger_time)
    df = await PriceMarketAkshare().get_data(t)
    return _df_to_result(df)


@app.tool(name="a_share_hot_money", description="获取 A 股热钱资金流向分析")
async def a_share_hot_money(trigger_time: str | None = None) -> dict:
    """获取 A 股热钱资金流向分析。"""
    t = _resolve_trigger_time(trigger_time)
    df = await HotMoneyAkshare().get_data(t)
    return _df_to_result(df)


@app.tool(name="a_share_stock_analysis", description="对指定 A 股做利好/利空对照分析，不给投资建议")
async def a_share_stock_analysis(symbol: str, trigger_time: str | None = None) -> dict:
    """输入股票代码或名称，内部拼市场背景 + 个股数据，只做利好/利空分析。"""
    t = _resolve_trigger_time(trigger_time)
    try:
        resolved_symbol, stock_name = _resolve_symbol(symbol)
    except Exception as e:
        return _df_to_result(pd.DataFrame([{
            "title": f"{symbol} 个股分析",
            "content": f"无法解析股票标的：{e}",
            "pub_time": t,
            "url": None,
        }]))

    background_task = asyncio.create_task(_build_market_background(t))
    stock_task = asyncio.create_task(_gather_data("CN-Stock", resolved_symbol, t))

    background = await background_task
    stock_data = await stock_task
    stock_text = _serialize(stock_data)

    prompt = STOCK_ANALYSIS_PROMPT.format(
        stock_name=stock_name,
        symbol=resolved_symbol,
        trigger_time=t,
        background=background,
        stock_data=stock_text,
    )
    try:
        response = await SKILL_LLM.a_run(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )
        content = (response.content or "").strip()
    except Exception as e:
        content = f"个股分析生成失败：{type(e).__name__}: {e}"

    return _df_to_result(pd.DataFrame([{
        "title": f"{stock_name}({resolved_symbol}) 个股分析",
        "content": content,
        "pub_time": t,
        "url": None,
    }]))


if __name__ == "__main__":
    asyncio.run(
        app.run_sse_async(
            host="127.0.0.1",
            port=8000,
            sse_path="/server/mcp/a_share_analysis/sse",
            message_path="/server/mcp/a_share_analysis/messages/",
        )
    )
