"""
Corporate Info Tools (Akshare Version)
"""
import asyncio
import asyncio
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from utils.akshare_utils import akshare_cached
from tools.tool_prompts import FINANCIAL_TOOL_SELECT_PROMPT
from tools.tool_utils import ToolManager, ToolManagerConfig
from tools.tool_utils import smart_tool

class CompanyFinancialInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    task: str = Field(description="The query of the financial data.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the financial information of a company (Akshare version). Currently only support CN-Stock.",
    args_schema=CompanyFinancialInput,
    max_output_len=4000,
    timeout_seconds=30.0
)
async def company_financial_info(market: str, symbol: str, task: str, trigger_time: str=None) -> str:
    if market != "CN-Stock":
        return {"error": "Currently only CN-Stock is supported for Akshare version."}
        
    tools_config = ToolManagerConfig(tool_paths=[
        "tools.corp_info_akshare.company_income",
        "tools.corp_info_akshare.company_balance_sheet",
        "tools.corp_info_akshare.company_cash_flow",
        "tools.corp_info_akshare.company_forecast",
        "tools.corp_info_akshare.company_express",
        "tools.corp_info_akshare.company_dividend",
    ])
    inner_tool_manager = ToolManager(tools_config)
    tool_selection_prompt = FINANCIAL_TOOL_SELECT_PROMPT.format(
        date=trigger_time,
        task=task,
        market=market,
        symbol=symbol,
        tool_info=inner_tool_manager.build_toolcall_context()
    )
    tool_call = await inner_tool_manager.select_tool_by_llm(
        prompt=tool_selection_prompt,
    )
    if "error" in tool_call:
        return {"error": tool_call["error_msg"]}

    tool_result = await inner_tool_manager.call_tool(
        tool_call['tool_name'],
        tool_call['properties'],
        trigger_time
    )
    return tool_result


class CompanyIncomeInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    period: str = Field(description="The period of the financial data. Format: YYYYMMDD. \
                        Reporting period (the last day of each quarter, for example, \
                        20171231 for annual report, 20170630 for semi-annual report, 20170930 \
                        for third quarter report).")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@tool(
    description="Get the income information of a company (Akshare version)",
    args_schema=CompanyIncomeInput
)
async def company_income(market: str, symbol: str, period: str, trigger_time: str=None) -> str:
    if market == "CN-Stock":
        trigger_date = trigger_time.split(" ")[0].replace("-", "")
        if period < trigger_date:
            try:
                # Akshare 利润表接口获取所有股票的利润表数据
                df = akshare_cached.run(
                    func_name="stock_lrb_em",
                    func_kwargs={"date": period},
                    verbose=False
                )
                if df is None or df.empty:
                    return {"error": f"No data returned from akshare for period {period}."}
                
                base_symbol = symbol.split(".")[0]  # 600519.SH -> 600519
                stock_data = df[df['股票代码'] == base_symbol]
                
                if stock_data.empty:
                    return {"error": f"No income data found for symbol {symbol} (base: {base_symbol}) in period {period}."}
                
                return stock_data.to_markdown()
            except Exception as e:
                return {"error": str(e)}
        else:
            return {"error": "The period is not in the trigger time."}
    else:
        return {"error": "Market not supported for Akshare version."}


class CompanyBalanceSheetInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    period: str = Field(description="The period of the financial data. Format: YYYYMMDD. \
                        Reporting period (the last day of each quarter, for example, \
                        20171231 for annual report, 20170630 for semi-annual report, 20170930 \
                        for third quarter report).")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@tool(
    description="Get the balance sheet information of a company (Akshare version)",
    args_schema=CompanyBalanceSheetInput
)
async def company_balance_sheet(market: str, symbol: str, period: str, trigger_time: str=None) -> str:
    if market == "CN-Stock":
        trigger_date = trigger_time.split(" ")[0].replace("-", "")
        if period < trigger_date:
            try:
                # Akshare 资产负债表接口获取特定股票的数据
                base_symbol = symbol.split(".")[0]  # 600519.SH -> 600519
                df = akshare_cached.run(
                    func_name="stock_financial_debt_ths",
                    func_kwargs={"symbol": base_symbol, "indicator": "按季度"},
                    verbose=False
                )
                if df is None or df.empty:
                    return {"error": f"No balance sheet data found for symbol {symbol}."}
                
                return df.to_markdown()
            except Exception as e:
                return {"error": str(e)}
        else:
            return {"error": "The period is not in the trigger time."}
    else:
        return {"error": "Market not supported for Akshare version."}


class CompanyCashFlowInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    period: str = Field(description="The period of the financial data. Format: YYYYMMDD. \
                        Reporting period (the last day of each quarter, for example, \
                        20171231 for annual report, 20170630 for semi-annual report, 20170930 \
                        for third quarter report).")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@tool(
    description="Get the cash flow information of a company (Akshare version)",
    args_schema=CompanyCashFlowInput
)
async def company_cash_flow(market: str, symbol: str, period: str, trigger_time: str=None) -> str:
    if market == "CN-Stock":
        trigger_date = trigger_time.split(" ")[0].replace("-", "")
        if period < trigger_date:
            try:
                # Akshare 现金流量表接口获取所有股票的现金流量表数据
                df = akshare_cached.run(
                    func_name="stock_xjll_em",
                    func_kwargs={"date": period},
                    verbose=False
                )
                if df is None or df.empty:
                    return {"error": f"No cash flow data found for period {period}."}
                
                # 筛选特定股票
                base_symbol = symbol.split(".")[0]  # 600519.SH -> 600519
                stock_data = df[df['股票代码'] == base_symbol]
                
                if stock_data.empty:
                    return {"error": f"No cash flow data found for symbol {symbol} (base: {base_symbol}) in period {period}."}
                
                return stock_data.to_markdown()
            except Exception as e:
                return {"error": str(e)}
        else:
            return {"error": "The period is not in the trigger time."}
    else:
        return {"error": "Market not supported for Akshare version."}


class CompanyForecastInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    period: str = Field(description="The period of the financial data. Format: YYYYMMDD. \
                        Reporting period (the last day of each quarter, for example, \
                        20171231 for annual report, 20170630 for semi-annual report, 20170930 \
                        for third quarter report).")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@tool(
    description="Get the forecast information of a company (Akshare version)",
    args_schema=CompanyForecastInput
)
async def company_forecast(market: str, symbol: str, period: str, trigger_time: str=None) -> str:
    if market == "CN-Stock":
        trigger_date = trigger_time.split(" ")[0].replace("-", "")
        if period < trigger_date:
            try:
                # Akshare 业绩预告接口
                df = akshare_cached.run(
                    func_name="stock_yjyg_em",
                    func_kwargs={"date": period},
                    verbose=False
                )
                if df is None or df.empty:
                    return {"error": f"No forecast data found for period {period}."}
                
                # 筛选特定股票
                base_symbol = symbol.split(".")[0]  # 600519.SH -> 600519
                stock_data = df[df['股票代码'] == base_symbol]
                
                if stock_data.empty:
                    return {"error": f"No forecast data found for symbol {symbol} (base: {base_symbol}) in period {period}."}
                
                return stock_data.to_markdown()
            except Exception as e:
                return {"error": str(e)}
        else:
            return {"error": "The period is not in the trigger time."}
    else:
        return {"error": "Market not supported for Akshare version."}


class CompanyExpressInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    period: str = Field(description="The period of the financial data. Format: YYYYMMDD. \
                        Reporting period (the last day of each quarter, for example, \
                        20171231 for annual report, 20170630 for semi-annual report, 20170930 \
                        for third quarter report).")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@tool(
    description="Get the express information of a company (Akshare version)",
    args_schema=CompanyExpressInput
)
async def company_express(market: str, symbol: str, period: str, trigger_time: str=None) -> str:
    if market == "CN-Stock":
        trigger_date = trigger_time.split(" ")[0].replace("-", "")
        if period < trigger_date:
            try:
                # Akshare 业绩快报接口
                df = akshare_cached.run(
                    func_name="stock_yjkb_em",
                    func_kwargs={"date": period},
                    verbose=False
                )
                if df is None or df.empty:
                    return {"error": f"No express data found for period {period}."}
                
                # 筛选特定股票
                base_symbol = symbol.split(".")[0]  # 600519.SH -> 600519
                stock_data = df[df['股票代码'] == base_symbol]
                
                if stock_data.empty:
                    return {"error": f"No express data found for symbol {symbol} (base: {base_symbol}) in period {period}."}
                
                return stock_data.to_markdown()
            except Exception as e:
                return {"error": str(e)}
        else:
            return {"error": "The period is not in the trigger time."}
    else:
        return {"error": "Market not supported for Akshare version."}


class CompanyDividendInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    period: str = Field(description="The period of the financial data. Format: YYYYMMDD. \
                        Reporting period (the last day of each quarter, for example, \
                        20171231 for annual report, 20170630 for semi-annual report, 20170930 \
                        for third quarter report).")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@tool(
    description="Get the dividend information of a company (Akshare version)",
    args_schema=CompanyDividendInput
)
async def company_dividend(market: str, symbol: str, period: str, trigger_time: str=None) -> str:
    if market == "CN-Stock":
        trigger_date = trigger_time.split(" ")[0].replace("-", "")
        if period < trigger_date:
            try:
                # Akshare 分红配送接口
                df = akshare_cached.run(
                    func_name="stock_fhps_em",
                    func_kwargs={"date": period},
                    verbose=False
                )
                if df is None or df.empty:
                    return {"error": f"No dividend data found for period {period}."}
                
                base_symbol = symbol.split(".")[0]  # 600519.SH -> 600519
                if '代码' in df.columns:
                    stock_data = df[df['代码'] == base_symbol]
                elif '股票代码' in df.columns:
                    stock_data = df[df['股票代码'] == base_symbol]
                else:
                    return {"error": "Unexpected column format in dividend data."}
                
                if stock_data.empty:
                    return {"error": f"No dividend data found for symbol {symbol} in period {period}."}
                
                return stock_data.to_markdown()
            except Exception as e:
                return {"error": str(e)}
        else:
            return {"error": "The period is not in the trigger time."}
    else:
        return {"error": "Market not supported for Akshare."}


if __name__ == "__main__":
    result = asyncio.run(company_financial_info.ainvoke({
        "market": "CN-Stock", 
        "symbol": "600519.SH", 
        "task": "最近财报", 
        "trigger_time": "2025-08-20 15:00:00"
    }))
    print(result)
