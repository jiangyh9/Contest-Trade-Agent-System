import asyncio
import pandas as pd
from typing import List, Dict, Any
import re

from pydantic import BaseModel, Field
from utils.alpha_vantage_utils import alpha_vantage_cached
from tools.tool_utils import smart_tool

class StockSymbolSearchInput(BaseModel):
    market: str = Field(description="The target market. e.g., CN-Stock, US-Stock, HK-Stock, CN-ETF")
    queries: List[str] = Field(description="List of search queries: company names or stock symbols (partial match supported)")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS")
    limit_per_query: int = Field(default=5, description="Maximum number of results per query")
    match_mode: str = Field(default="best", description="Match mode: 'best' (top match), 'all' (all matches), 'exact' (exact only)")

def search_alpha_vantage_symbol(keywords: str) -> pd.DataFrame:
    """
    使用Alpha Vantage API搜索股票代码
    """
    params = {
        'function': 'SYMBOL_SEARCH',
        'keywords': keywords
    }
    
    try:
        result = alpha_vantage_cached.run(params, verbose=False)
        
        # 检查是否找到匹配项
        matches = result.get("bestMatches", [])
        if not matches:
            return pd.DataFrame()

        # 将匹配结果转换为 Pandas DataFrame
        search_results_df = pd.DataFrame(matches)
        
        # 重命名列以提高可读性
        column_mapping = {
            "1. symbol": "symbol",
            "2. name": "name", 
            "3. type": "type",
            "4. region": "region",
            "5. marketOpen": "market_open",
            "6. marketClose": "market_close",
            "7. timezone": "timezone",
            "8. currency": "currency",
            "9. matchScore": "match_score"
        }
        
        for old_col, new_col in column_mapping.items():
            if old_col in search_results_df.columns:
                search_results_df = search_results_df.rename(columns={old_col: new_col})
        
        # 确保match_score是数值类型
        if 'match_score' in search_results_df.columns:
            search_results_df['match_score'] = pd.to_numeric(search_results_df['match_score'], errors='coerce')
        
        return search_results_df
        
    except Exception as e:
        print(f"搜索股票代码时出错: {e}")
        return pd.DataFrame()

def calculate_match_score(query: str, symbol: str, name: str) -> tuple[str, float]:
    """计算匹配分数和类型"""
    query_lower = query.lower()
    symbol_lower = symbol.lower()
    name_lower = name.lower()
    
    # 精确匹配
    if query == symbol or query == name:
        return "exact", 1.0
    if query_lower == symbol_lower or query_lower == name_lower:
        return "exact", 1.0
    
    # 前缀匹配
    if symbol_lower.startswith(query_lower) or name_lower.startswith(query_lower):
        return "prefix", 0.9
    
    # 包含匹配
    if query_lower in symbol_lower or query_lower in name_lower:
        return "contains", 0.8
    
    # 模糊匹配
    if re.search(re.escape(query_lower), symbol_lower) or re.search(re.escape(query_lower), name_lower):
        return "fuzzy", 0.7
    
    return "none", 0.0

def search_single_query(query: str, limit: int, match_mode: str, market: str) -> List[Dict[str, Any]]:
    """搜索单个查询"""
    results = []
    
    # 使用Alpha Vantage搜索
    search_df = search_alpha_vantage_symbol(query)
    
    if search_df.empty:
        return []
    
    for _, row in search_df.iterrows():
        symbol = row.get('symbol', '')
        name = row.get('name', '')
        av_match_score = row.get('match_score', 0.0)
        
        match_type, custom_score = calculate_match_score(query, symbol, name)
        
        if match_mode == "exact" and match_type != "exact":
            continue
        
        # 使用Alpha Vantage的匹配分数和自定义分数的加权平均
        final_score = (av_match_score + custom_score) / 2
        
        if final_score > 0:
            results.append({
                "symbol": symbol,
                "name": name,
                "market": market,
                "type": row.get('type', ''),
                "region": row.get('region', ''),
                "currency": row.get('currency', ''),
                "match_type": match_type,
                "match_score": final_score,
                "av_match_score": av_match_score
            })
    
    # 按分数排序
    results.sort(key=lambda x: x['match_score'], reverse=True)
    
    if match_mode == "best":
        return results[:1]
    else:
        return results[:limit]

@smart_tool(
    description="Search for US stock symbols by company names or partial symbols using Alpha Vantage API.",
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
    
    try:
        # 只处理US市场
        if not market.startswith("US"):
            return {
                "error": f"This tool only supports US markets, got {market}",
                "results": {},
                "summary": {"total_queries": len(queries), "successful_matches": 0, "failed_matches": len(queries)},
                "failed_queries": [{"query": q, "error": "Unsupported market"} for q in queries]
            }
        
        # 处理每个查询
        results = {}
        failed_queries = []
        
        for query in queries:
            try:
                matches = search_single_query(query, limit_per_query, match_mode, market)
                if matches:
                    results[query] = matches
                else:
                    failed_queries.append({"query": query, "error": "No matches found"})
            except Exception as e:
                failed_queries.append({"query": query, "error": str(e)})
        
        # 生成摘要
        summary = {
            "total_queries": len(queries),
            "successful_matches": len(results),
            "failed_matches": len(failed_queries),
            "total_results": sum(len(matches) for matches in results.values())
        }
        
        return {
            "results": results,
            "summary": summary,
            "failed_queries": failed_queries,
            "market": market,
            "trigger_time": trigger_time,
            "data_source": "Alpha Vantage"
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "results": {},
            "summary": {"total_queries": len(queries), "successful_matches": 0, "failed_matches": len(queries)},
            "failed_queries": [{"query": q, "error": str(e)} for q in queries]
        }

if __name__ == "__main__":
    result = asyncio.run(
        stock_symbol_search.ainvoke(
            {"market": "US-Stock", 
             "queries": ["baidu"], 
             "trigger_time": "2025-01-09 15:00:00",
             "limit_per_query": 3,
             "match_mode": "all"}))
    print("搜索结果:")
    print(result)