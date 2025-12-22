"""
stock selector tool that can be used to filter stocks based on natural language query and tushare stock basic data.

"""
import re
import json
import asyncio
import pandas as pd
from pydantic import BaseModel, Field

from tools.tool_utils import smart_tool
from utils.tushare_utils import pro_cached
from utils.date_utils import get_previous_trading_date
from tools.tool_prompts import STOCK_FILTER_PROMPT
from models.llm_model import GLOBAL_LLM

def get_basic_stock_df(trggler_time: str):
    trade_date = get_previous_trading_date(trggler_time)
    df1 = pro_cached.run(
        func_name="daily_basic",
        func_kwargs={
            "ts_code": "",
            "trade_date": trade_date,
            "fields": "ts_code,turnover_rate, turnover_rate_f, volume_ratio, pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm, total_share, float_share, free_share, total_mv, circ_mv"
        }
    )
    df2 = pro_cached.run(
        func_name="stock_basic",
        func_kwargs={
            "exchange": "",
            "list_status": "L",
            "fields": "ts_code,name,area,industry"
        }
    )
    df2 = df2[~(df2['name'].str.contains('ST'))]
    df2 = df2[~(df2['ts_code'].str.contains('.BJ'))]
    df = pd.merge(df2, df1, on='ts_code', how='left')
    return df

class StockSelectorInput(BaseModel):
    market: str = Field(description="目标市场，当前仅支持 CN-Stock")
    query: str = Field(description="股票查询query, 自然语言的形式。")
    trigger_time: str = Field(description="触发时间，格式：YYYY-MM-DD HH:MM:SS")
    limit: int = Field(default=10, description="返回结果数量，默认10个, 最多20个。")

@smart_tool(
    description="""
    选股工具，基于自然语言查询筛选A股股票，支持通过财务指标等组合筛选股票。不可用于查询具体股票信息。
    例如
    - 行业 + 财务指标筛选
    - 示例："新能源汽车市值最大的3家"、"市值超过1000亿的银行股"、"PE小于20银行股" 
    具体可以筛选的字段如下：             
    字段名              类型      含义                example
    ts_code            str      股票代码              000001.SZ
    name               str      股票名称              平安银行
    area               str      地区                  深圳
    industry           str      行业                  银行
    turnover_rate      float    换手率（%）           2.06
    turnover_rate_f    float    换手率（自由流通股）   3.28
    volume_ratio       float    量比                  1.08
    pe                 float    市盈率（总市值/净利润，亏损的PE为空） 21.22
    pe_ttm             float    市盈率（TTM，亏损的PE为空） 22.06
    pb                 float    市净率（总市值/净资产） 2.16
    ps                 float    市销率                2.4
    ps_ttm             float    市销率（TTM）         2.37
    dv_ratio           float    股息率（%）           1.45
    dv_ttm             float    股息率（TTM）（%）    1.11
    total_share        float    总股本（万股）        34813.69
    float_share        float    流通股本（万股）      32001.01
    free_share         float    自由流通股本（万）    20114.79
    total_mv           float    总市值（万元）        470332.97
    circ_mv            float    流通市值（万元）      432333.64
    """,
    args_schema=StockSelectorInput,
    max_output_len=2000,
    timeout_seconds=30.0
)
async def stock_selector(market: str, query: str, trigger_time: str, limit: int = 10) -> str:
    try:
        # get stock df
        stock_df = get_basic_stock_df(trigger_time)

        # gen search code
        prompt = STOCK_FILTER_PROMPT.format(query=query)
        messages = [{"role": "user", "content": prompt}]
        response = await GLOBAL_LLM.a_run(messages, verbose=False, thinking=False)

        # parse search code
        code_match = re.search(r"```python(.*?)```", response.content, re.DOTALL)
        code_str = code_match.group(1)
        exec_globals = {}
        code_str = f'import pandas as pd\n{code_str}'
        exec(code_str, exec_globals)
        filter_stock_func = exec_globals['filter_stock']
        filter_stock_df = filter_stock_func(stock_df)[:min(20, limit)]
        result_context = json.dumps(filter_stock_df.to_dict(orient='records'), ensure_ascii=False)
        return result_context
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    query = "市净率低于1且总市值小于50亿的股票"
    market = "CN-Stock"
    trigger_time = "2025-01-02 15:00:00"
    limit = 10
    result = asyncio.run(stock_selector.ainvoke({"market": "CN-Stock", "query": query, "trigger_time": "2025-01-09 15:00:00", "limit": 5}))
    print(result)
