"""
A 股市场综合分析 Skill 的 CLI 脚本。

通过本地 MCP SSE 服务取数。

用法：
    python scripts/cli.py sina_news_summary
    python scripts/cli.py thx_news_summary
    python scripts/cli.py a_share_market_overview
    python scripts/cli.py a_share_hot_money
    python scripts/cli.py a_share_stock_analysis 600519
    python scripts/cli.py a_share_stock_analysis 贵州茅台

注意：trigger_time 固定为当前时间，不支持历史回测。
"""

import asyncio
import json
import sys
from datetime import datetime

sys.dont_write_bytecode = True

from mcp import ClientSession
from mcp.client.sse import sse_client


SSE_URL = "http://127.0.0.1:8000/server/mcp/a_share_analysis/sse"

VALID_TOOLS = {
    "sina_news_summary",
    "thx_news_summary",
    "a_share_market_overview",
    "a_share_hot_money",
    "a_share_stock_analysis",
}


async def call_tool(tool_name: str, args: dict) -> dict:
    if tool_name not in VALID_TOOLS:
        sys.stderr.write(f"ERROR: 未知 tool: {tool_name}\n")
        sys.stderr.write(f"可用 tool: {', '.join(sorted(VALID_TOOLS))}\n")
        raise SystemExit(2)

    try:
        async with sse_client(SSE_URL) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)

                texts = []
                for item in result.content:
                    if hasattr(item, "text") and item.text:
                        texts.append(item.text)

                if not texts:
                    sys.stderr.write("ERROR: MCP 返回为空\n")
                    raise SystemExit(1)

                full_text = "\n".join(texts)
                try:
                    parsed = json.loads(full_text)
                    print(json.dumps(parsed, ensure_ascii=False, indent=2))
                except json.JSONDecodeError:
                    print(full_text)

                return {"tool": tool_name, "raw": full_text}

    except Exception as e:
        sys.stderr.write(f"ERROR: 调用 MCP 失败: {type(e).__name__}: {e}\n")
        sys.stderr.write("请确认本地服务已启动: python local_mcp_server.py\n")
        raise SystemExit(1)


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: python scripts/cli.py <tool_name> [symbol]\n")
        sys.stderr.write(f"可用 tool: {', '.join(sorted(VALID_TOOLS))}\n")
        raise SystemExit(2)

    tool_name = sys.argv[1]
    args = {
        "trigger_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    if tool_name == "a_share_stock_analysis":
        if len(sys.argv) < 3:
            sys.stderr.write("ERROR: a_share_stock_analysis 需要股票代码或名称，例如：600519 或 贵州茅台\n")
            raise SystemExit(2)
        args["symbol"] = sys.argv[2]

    asyncio.run(call_tool(tool_name, args))


if __name__ == "__main__":
    main()
