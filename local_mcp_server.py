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


app = MCPServer(
    name="a_share_analysis",
    title="A 股市场综合分析",
    description="提供新浪财经、同花顺、大盘走势、热钱资金流 4 类 A 股分析能力",
)


@app.tool(name="sina_news_summary", description="获取新浪财经新闻摘要")
async def sina_news_summary(trigger_time: str | None = None) -> dict:
    """获取新浪财经新闻摘要。"""
    t = _resolve_trigger_time(trigger_time)
    df = await SinaNewsCrawl().get_data(t)
    return _df_to_result(df)


@app.tool(name="thx_news_summary", description="获取同花顺股票资讯摘要")
async def thx_news_summary(trigger_time: str | None = None) -> dict:
    """获取同花顺股票资讯摘要。"""
    t = _resolve_trigger_time(trigger_time)
    df = await ThxNewsCrawl().get_data(t)
    return _df_to_result(df)


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


if __name__ == "__main__":
    asyncio.run(
        app.run_sse_async(
            host="127.0.0.1",
            port=8000,
            sse_path="/server/mcp/a_share_analysis/sse",
            message_path="/server/mcp/a_share_analysis/messages/",
        )
    )
