"""
Corporate Info Tools (Alpha Vantage Version for US Market)
"""
import asyncio
import pandas as pd
from pydantic import BaseModel, Field
from utils.alpha_vantage_utils import alpha_vantage_cached
from tools.tool_utils import smart_tool


class CompanyFinancialInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    sheet_name: str = Field(description="The specific financial sheet to retrieve. Options: 'income_statement', 'balance_sheet', 'cash_flow', 'earnings', 'dividends', 'shares_outstanding'")
    task: str = Field(description="The query of the financial data.", default="")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the financial information of a US company using Alpha Vantage API. Specify sheet_name to directly retrieve the desired financial sheet (income_statement, balance_sheet, cash_flow, earnings, dividends, shares_outstanding). Currently only supports US-Stock.",
    args_schema=CompanyFinancialInput,
    max_output_len=4000,
    timeout_seconds=30.0
)
async def company_financial_info(market: str, symbol: str, sheet_name: str, task: str = "", trigger_time: str = None) -> dict:
    if market != "US-Stock":
        return {"error": "Currently only US-Stock is supported for Alpha Vantage version."}
        
    # Direct function mapping to avoid wasteful LLM tool selection
    function_map = {
        "income_statement": company_income_statement,
        "balance_sheet": company_balance_sheet,
        "cash_flow": company_cash_flow,
        "earnings": company_earnings,
        "dividends": company_dividends,
        "shares_outstanding": company_shares_outstanding,
    }
    
    if sheet_name not in function_map:
        return {"error": f"Invalid sheet_name '{sheet_name}'. Valid options: {list(function_map.keys())}"}
    
    # Call the specific function directly
    selected_function = function_map[sheet_name]
    result = await selected_function.ainvoke({
        "market": market,
        "symbol": symbol,
        "trigger_time": trigger_time
    })
    
    return result


class CompanyIncomeStatementInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the income statement information of a US company using Alpha Vantage API",
    args_schema=CompanyIncomeStatementInput,
    max_output_len=3000,
    timeout_seconds=15.0
)
async def company_income_statement(market: str, symbol: str, trigger_time: str = None) -> dict:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    
    try:
        params = {
            'function': 'INCOME_STATEMENT',
            'symbol': symbol
        }
        
        result = alpha_vantage_cached.run(params, verbose=False)
        
        if 'annualReports' not in result:
            return {"error": f"No income statement data found for symbol {symbol}"}
        
        # 转换为DataFrame格式
        annual_reports = result['annualReports']
        quarterly_reports = result.get('quarterlyReports', [])
        
        annual_df = pd.DataFrame(annual_reports)
        quarterly_df = pd.DataFrame(quarterly_reports)
        
        response = {
            "symbol": symbol,
            "market": market,
            "data_source": "Alpha Vantage",
            "trigger_time": trigger_time
        }
        
        if not annual_df.empty:
            response["annual_reports"] = annual_df.to_dict('records')
            response["annual_reports_markdown"] = annual_df.to_markdown(index=False)
        
        if not quarterly_df.empty:
            response["quarterly_reports"] = quarterly_df.to_dict('records')
            response["quarterly_reports_markdown"] = quarterly_df.to_markdown(index=False)
        
        return response
        
    except Exception as e:
        return {"error": f"Failed to get income statement: {str(e)}"}


class CompanyBalanceSheetInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the balance sheet information of a US company using Alpha Vantage API",
    args_schema=CompanyBalanceSheetInput,
    max_output_len=3000,
    timeout_seconds=15.0
)
async def company_balance_sheet(market: str, symbol: str, trigger_time: str = None) -> dict:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    
    try:
        params = {
            'function': 'BALANCE_SHEET',
            'symbol': symbol
        }
        
        result = alpha_vantage_cached.run(params, verbose=False)
        
        if 'annualReports' not in result:
            return {"error": f"No balance sheet data found for symbol {symbol}"}
        
        # 转换为DataFrame格式
        annual_reports = result['annualReports']
        quarterly_reports = result.get('quarterlyReports', [])
        
        annual_df = pd.DataFrame(annual_reports)
        quarterly_df = pd.DataFrame(quarterly_reports)
        
        response = {
            "symbol": symbol,
            "market": market,
            "data_source": "Alpha Vantage",
            "trigger_time": trigger_time
        }
        
        if not annual_df.empty:
            response["annual_reports"] = annual_df.to_dict('records')
            response["annual_reports_markdown"] = annual_df.to_markdown(index=False)
        
        if not quarterly_df.empty:
            response["quarterly_reports"] = quarterly_df.to_dict('records')
            response["quarterly_reports_markdown"] = quarterly_df.to_markdown(index=False)
        
        return response
        
    except Exception as e:
        return {"error": f"Failed to get balance sheet: {str(e)}"}


class CompanyCashFlowInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the cash flow information of a US company using Alpha Vantage API",
    args_schema=CompanyCashFlowInput,
    max_output_len=3000,
    timeout_seconds=15.0
)
async def company_cash_flow(market: str, symbol: str, trigger_time: str = None) -> dict:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    
    try:
        params = {
            'function': 'CASH_FLOW',
            'symbol': symbol
        }
        
        result = alpha_vantage_cached.run(params, verbose=False)
        
        if 'annualReports' not in result:
            return {"error": f"No cash flow data found for symbol {symbol}"}
        
        # 转换为DataFrame格式
        annual_reports = result['annualReports']
        quarterly_reports = result.get('quarterlyReports', [])
        
        annual_df = pd.DataFrame(annual_reports)
        quarterly_df = pd.DataFrame(quarterly_reports)
        
        response = {
            "symbol": symbol,
            "market": market,
            "data_source": "Alpha Vantage",
            "trigger_time": trigger_time
        }
        
        if not annual_df.empty:
            response["annual_reports"] = annual_df.to_dict('records')
            response["annual_reports_markdown"] = annual_df.to_markdown(index=False)
        
        if not quarterly_df.empty:
            response["quarterly_reports"] = quarterly_df.to_dict('records')
            response["quarterly_reports_markdown"] = quarterly_df.to_markdown(index=False)
        
        return response
        
    except Exception as e:
        return {"error": f"Failed to get cash flow: {str(e)}"}


class CompanyEarningsInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the earnings information of a US company using Alpha Vantage API",
    args_schema=CompanyEarningsInput,
    max_output_len=3000,
    timeout_seconds=15.0
)
async def company_earnings(market: str, symbol: str, trigger_time: str = None) -> dict:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    
    try:
        params = {
            'function': 'EARNINGS',
            'symbol': symbol
        }
        
        result = alpha_vantage_cached.run(params, verbose=False)
        
        if 'annualEarnings' not in result:
            return {"error": f"No earnings data found for symbol {symbol}"}
        
        # 转换为DataFrame格式
        annual_earnings = result['annualEarnings']
        quarterly_earnings = result.get('quarterlyEarnings', [])
        
        annual_df = pd.DataFrame(annual_earnings)
        quarterly_df = pd.DataFrame(quarterly_earnings)
        
        response = {
            "symbol": symbol,
            "market": market,
            "data_source": "Alpha Vantage",
            "trigger_time": trigger_time
        }
        
        if not annual_df.empty:
            response["annual_earnings"] = annual_df.to_dict('records')
            response["annual_earnings_markdown"] = annual_df.to_markdown(index=False)
        
        if not quarterly_df.empty:
            response["quarterly_earnings"] = quarterly_df.to_dict('records')
            response["quarterly_earnings_markdown"] = quarterly_df.to_markdown(index=False)
        
        return response
        
    except Exception as e:
        return {"error": f"Failed to get earnings: {str(e)}"}


class CompanyDividendsInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the dividends information of a US company using Alpha Vantage API",
    args_schema=CompanyDividendsInput,
    max_output_len=3000,
    timeout_seconds=15.0
)
async def company_dividends(market: str, symbol: str, trigger_time: str = None) -> dict:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    
    try:
        params = {
            'function': 'DIVIDENDS',
            'symbol': symbol
        }
        
        result = alpha_vantage_cached.run(params, verbose=False)
        
        if 'data' not in result:
            return {"error": f"No dividends data found for symbol {symbol}"}
        
        # 转换为DataFrame格式
        dividends_data = result['data']
        dividends_df = pd.DataFrame(dividends_data)
        
        response = {
            "symbol": symbol,
            "market": market,
            "data_source": "Alpha Vantage",
            "trigger_time": trigger_time
        }
        
        if not dividends_df.empty:
            response["dividends_data"] = dividends_df.to_dict('records')
            response["dividends_markdown"] = dividends_df.to_markdown(index=False)
        else:
            response["dividends_data"] = "No dividend data available"
        
        return response
        
    except Exception as e:
        return {"error": f"Failed to get dividends: {str(e)}"}


class CompanySharesOutstandingInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the shares outstanding information of a US company using Alpha Vantage API",
    args_schema=CompanySharesOutstandingInput,
    max_output_len=3000,
    timeout_seconds=15.0
)
async def company_shares_outstanding(market: str, symbol: str, trigger_time: str = None) -> dict:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    
    try:
        params = {
            'function': 'SHARES_OUTSTANDING',
            'symbol': symbol
        }
        
        result = alpha_vantage_cached.run(params, verbose=False)
        
        if 'data' not in result:
            return {"error": f"No shares outstanding data found for symbol {symbol}"}
        
        # 转换为DataFrame格式
        shares_data = result['data']
        shares_df = pd.DataFrame(shares_data)
        
        response = {
            "symbol": symbol,
            "market": market,
            "data_source": "Alpha Vantage", 
            "trigger_time": trigger_time
        }
        
        if not shares_df.empty:
            response["shares_outstanding_data"] = shares_df.to_dict('records')
            response["shares_outstanding_markdown"] = shares_df.to_markdown(index=False)
        else:
            response["shares_outstanding_data"] = "No shares outstanding data available"
        
        return response
        
    except Exception as e:
        return {"error": f"Failed to get shares outstanding: {str(e)}"}


if __name__ == "__main__":
    # Test the main financial info function
    result = asyncio.run(company_financial_info.ainvoke({
        "market": "US-Stock", 
        "symbol": "AAPL", 
        "sheet_name": "income_statement",
        "task": "最近财报", 
        "trigger_time": "2025-08-20 15:00:00"
    }))
    print("AAPL财务信息:")
    print(result)
    
    # Test individual functions
    result = asyncio.run(company_income_statement.ainvoke({
        "market": "US-Stock", 
        "symbol": "MSFT", 
        "trigger_time": "2025-08-20 15:00:00"
    }))
    print("\nMSFT损益表:")
    print(result)