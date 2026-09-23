"""
US Stock Symbol Search Tool (Finnhub-based)
美股代码搜索工具：通过 Finnhub symbol_lookup 把公司名/关键词映射到美股代码。
"""
import asyncio
import pandas as pd
from typing import List, Dict, Any
import re

from pydantic import BaseModel, Field
from utils.finnhub_utils import finnhub_cached
from tools.tool_utils import smart_tool


class StockSymbolSearchInput(BaseModel):
    market: str = Field(description="The target market. e.g., CN-Stock, US-Stock, HK-Stock, CN-ETF")
    queries: List[str] = Field(description="List of search queries: company names or stock symbols (partial match supported)")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS")
    limit_per_query: int = Field(default=5, description="Maximum number of results per query")
    match_mode: str = Field(default="best", description="Match mode: 'best' (top match), 'all' (all matches), 'exact' (exact only)")


def _search_finnhub(query: str) -> pd.DataFrame:
    """使用 Finnhub symbol_lookup 搜索股票代码"""
    try:
        result = finnhub_cached.run('symbol_lookup', {'query': query}, verbose=False)
        if not isinstance(result, dict):
            return pd.DataFrame()
        items = result.get('result', [])
        if not items:
            return pd.DataFrame()

        # 过滤到美股常见类型，优先 Common Stock / ETF
        rows = []
        for item in items:
            symbol = item.get('displaySymbol') or item.get('symbol', '')
            # 过滤掉明显非美股的 suffix（如 .SS/.T/.L 等）
            if '.' in symbol:
                continue
            rows.append({
                "symbol": symbol,
                "name": item.get('description', ''),
                "type": item.get('type', ''),
                "region": "US",
                "currency": "USD",
                "match_score": 0.0,  # 后续由 calculate_match_score 填充
            })
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"Finnhub symbol_lookup failed for '{query}': {e}")
        return pd.DataFrame()


def _calculate_match_score(query: str, symbol: str, name: str) -> tuple[str, float]:
    """计算查询与代码/名称的匹配分数"""
    query_lower = query.lower()
    symbol_lower = symbol.lower()
    name_lower = name.lower()

    if query == symbol or query == name:
        return "exact", 1.0
    if query_lower == symbol_lower or query_lower == name_lower:
        return "exact", 1.0
    if symbol_lower.startswith(query_lower) or name_lower.startswith(query_lower):
        return "prefix", 0.9
    if query_lower in symbol_lower or query_lower in name_lower:
        return "contains", 0.8
    if re.search(re.escape(query_lower), symbol_lower) or re.search(re.escape(query_lower), name_lower):
        return "fuzzy", 0.7
    return "none", 0.0


def _search_single_query(query: str, limit: int, match_mode: str, market: str) -> List[Dict[str, Any]]:
    """搜索单个查询并返回结构化结果"""
    search_df = _search_finnhub(query)
    if search_df.empty:
        return []

    results = []
    for _, row in search_df.iterrows():
        symbol = row.get('symbol', '')
        name = row.get('name', '')
        match_type, custom_score = _calculate_match_score(query, symbol, name)

        if match_mode == "exact" and match_type != "exact":
            continue

        final_score = custom_score
        if final_score > 0:
            results.append({
                "symbol": symbol,
                "name": name,
                "market": market,
                "type": row.get('type', ''),
                "region": row.get('region', 'US'),
                "currency": row.get('currency', 'USD'),
                "match_type": match_type,
                "match_score": final_score,
                "data_source": "Finnhub",
            })

    results.sort(key=lambda x: x['match_score'], reverse=True)
    if match_mode == "best":
        return results[:1]
    return results[:limit]


@smart_tool(
    description="Search for US stock symbols by company names or partial symbols using Finnhub API.",
    args_schema=StockSymbolSearchInput,
    max_output_len=4000,
    timeout_seconds=10.0
)
async def stock_symbol_search(
    market: str,
    queries: List[str],
    trigger_time: str,
    limit_per_query: int = 5,
    match_mode: str = "best"
) -> Dict[str, Any]:
    """美股代码搜索入口"""
    try:
        if not market.startswith("US"):
            return {
                "error": f"This tool only supports US markets, got {market}",
                "results": {},
                "summary": {"total_queries": len(queries), "successful_matches": 0, "failed_matches": len(queries)},
                "failed_queries": [{"query": q, "error": "Unsupported market"} for q in queries],
            }

        results = {}
        failed_queries = []
        for query in queries:
            try:
                matches = _search_single_query(query, limit_per_query, match_mode, market)
                if matches:
                    results[query] = matches
                else:
                    failed_queries.append({"query": query, "error": "No matches found"})
            except Exception as e:
                failed_queries.append({"query": query, "error": str(e)})

        summary = {
            "total_queries": len(queries),
            "successful_matches": len(results),
            "failed_matches": len(failed_queries),
            "total_results": sum(len(matches) for matches in results.values()),
        }

        return {
            "results": results,
            "summary": summary,
            "failed_queries": failed_queries,
            "market": market,
            "trigger_time": trigger_time,
            "data_source": "Finnhub",
        }

    except Exception as e:
        return {
            "error": str(e),
            "results": {},
            "summary": {"total_queries": len(queries), "successful_matches": 0, "failed_matches": len(queries)},
            "failed_queries": [{"query": q, "error": str(e)} for q in queries],
        }


if __name__ == "__main__":
    result = asyncio.run(
        stock_symbol_search.ainvoke(
            {
                "market": "US-Stock",
                "queries": ["Apple", "Microsoft", "Tesla"],
                "trigger_time": "2026-09-23 09:00:00",
                "limit_per_query": 3,
                "match_mode": "best",
            }
        )
    )
    print(result)
