"""
Corporate Info Tools (FMP + Finnhub)
美股基本面/财务数据工具：
- income_statement / balance_sheet / cash_flow：FMP
- earnings：Finnhub company_earnings
- dividends：Finnhub stock_dividends（免费 tier 通常无权限，会降级提示）
- shares_outstanding：Finnhub company_profile2
"""
import asyncio
import pandas as pd
from typing import Dict, Any
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from utils.fmp_utils import fmp_cached, get_us_stock_financials
from utils.finnhub_utils import finnhub_cached
from tools.tool_utils import smart_tool


class CompanyFinancialInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    sheet_name: str = Field(description="The specific financial sheet to retrieve. Options: 'income_statement', 'balance_sheet', 'cash_flow', 'earnings', 'dividends', 'shares_outstanding'")
    task: str = Field(description="The query of the financial data.", default="")
    trigger_time: str = Field(description="The trigger time of the financial data. Format: YYYY-MM-DD HH:MM:SS.")


def _df_to_response(df: pd.DataFrame, symbol: str, market: str, trigger_time: str, data_source: str,
                    key_cols: list = None) -> Dict[str, Any]:
    response = {
        "symbol": symbol,
        "market": market,
        "data_source": data_source,
        "trigger_time": trigger_time,
    }
    if df.empty:
        response["error"] = "No data available"
        return response

    # 默认只保留最近 2 期，避免超出工具输出长度上限
    df = df.head(2).copy()

    # 只保留关键列
    if key_cols:
        available_cols = [c for c in key_cols if c in df.columns]
        if available_cols:
            df = df[available_cols]

    # 保证 JSON 可序列化：日期转字符串，NaN 转 None
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime('%Y-%m-%d')
    df = df.where(pd.notnull(df), None)

    response["annual_reports"] = df.to_dict('records')
    # markdown 表太长，只保留 records，由 LLM 自行阅读
    return response


INCOME_KEY_COLS = [
    "date", "symbol", "fiscalYear", "period",
    "revenue", "costOfRevenue", "grossProfit",
    "researchAndDevelopmentExpenses", "operatingExpenses", "operatingIncome",
    "netIncome", "eps", "epsDiluted",
]

BALANCE_KEY_COLS = [
    "date", "symbol", "fiscalYear", "period",
    "cashAndCashEquivalents", "totalCurrentAssets", "totalAssets",
    "totalCurrentLiabilities", "totalLiabilities",
    "totalStockholdersEquity", "totalDebt", "netDebt",
]

CASHFLOW_KEY_COLS = [
    "date", "symbol", "fiscalYear", "period",
    "netCashProvidedByOperatingActivities", "capitalExpenditure", "freeCashFlow",
    "netChangeInCash", "cashAtEndOfPeriod",
]


@smart_tool(
    description="Get the financial information of a US company using FMP/Finnhub API. Specify sheet_name to directly retrieve the desired financial sheet (income_statement, balance_sheet, cash_flow, earnings, dividends, shares_outstanding). Currently only supports US-Stock.",
    args_schema=CompanyFinancialInput,
    max_output_len=4000,
    timeout_seconds=30.0
)
async def company_financial_info(market: str, symbol: str, sheet_name: str, task: str = "", trigger_time: str = None) -> Dict[str, Any]:
    if market != "US-Stock":
        return {"error": "Currently only US-Stock is supported for Finnhub/FMP version."}

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

    selected_function = function_map[sheet_name]
    try:
        return await selected_function.ainvoke({
            "market": market,
            "symbol": symbol,
            "trigger_time": trigger_time,
        })
    except Exception as e:
        return {"error": f"Failed to get {sheet_name}: {str(e)}"}


class CompanyIncomeStatementInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the income statement information of a US company using FMP API",
    args_schema=CompanyIncomeStatementInput,
    max_output_len=3000,
    timeout_seconds=15.0
)
async def company_income_statement(market: str, symbol: str, trigger_time: str = None) -> Dict[str, Any]:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    try:
        df = get_us_stock_financials(symbol, statement_type='income', period='annual', verbose=False)
        return _df_to_response(df, symbol, market, trigger_time, "FMP", key_cols=INCOME_KEY_COLS)
    except Exception as e:
        return {"error": f"Failed to get income statement: {str(e)}"}


class CompanyBalanceSheetInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the balance sheet information of a US company using FMP API",
    args_schema=CompanyBalanceSheetInput,
    max_output_len=3000,
    timeout_seconds=15.0
)
async def company_balance_sheet(market: str, symbol: str, trigger_time: str = None) -> Dict[str, Any]:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    try:
        df = get_us_stock_financials(symbol, statement_type='balance', period='annual', verbose=False)
        return _df_to_response(df, symbol, market, trigger_time, "FMP", key_cols=BALANCE_KEY_COLS)
    except Exception as e:
        return {"error": f"Failed to get balance sheet: {str(e)}"}


class CompanyCashFlowInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the cash flow information of a US company using FMP API",
    args_schema=CompanyCashFlowInput,
    max_output_len=3000,
    timeout_seconds=15.0
)
async def company_cash_flow(market: str, symbol: str, trigger_time: str = None) -> Dict[str, Any]:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    try:
        df = get_us_stock_financials(symbol, statement_type='cash', period='annual', verbose=False)
        return _df_to_response(df, symbol, market, trigger_time, "FMP", key_cols=CASHFLOW_KEY_COLS)
    except Exception as e:
        return {"error": f"Failed to get cash flow: {str(e)}"}


class CompanyEarningsInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the earnings surprise/estimate information of a US company using Finnhub API",
    args_schema=CompanyEarningsInput,
    max_output_len=2000,
    timeout_seconds=10.0
)
async def company_earnings(market: str, symbol: str, trigger_time: str = None) -> Dict[str, Any]:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    try:
        data = finnhub_cached.run('company_earnings', {'symbol': symbol}, verbose=False)
        if not isinstance(data, list) or not data:
            return {
                "symbol": symbol,
                "market": market,
                "data_source": "Finnhub",
                "trigger_time": trigger_time,
                "error": "No earnings data available",
            }
        df = pd.DataFrame(data)
        return _df_to_response(df, symbol, market, trigger_time, "Finnhub")
    except Exception as e:
        return {"error": f"Failed to get earnings: {str(e)}"}


class CompanyDividendsInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the dividend history of a US company using Finnhub API (premium endpoint on most free plans)",
    args_schema=CompanyDividendsInput,
    max_output_len=2000,
    timeout_seconds=10.0
)
async def company_dividends(market: str, symbol: str, trigger_time: str = None) -> Dict[str, Any]:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    try:
        trigger_date_str = trigger_time.split(" ")[0] if trigger_time else datetime.now().strftime("%Y-%m-%d")
        end_dt = datetime.strptime(trigger_date_str, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=365 * 5)
        data = finnhub_cached.run(
            'stock_dividends',
            {'symbol': symbol, '_from': start_dt.strftime("%Y-%m-%d"), 'to': end_dt.strftime("%Y-%m-%d")},
            verbose=False,
        )
        if not isinstance(data, list) or not data:
            return {
                "symbol": symbol,
                "market": market,
                "data_source": "Finnhub",
                "trigger_time": trigger_time,
                "error": "No dividend data available (Finnhub dividends may require paid tier)",
            }
        df = pd.DataFrame(data)
        return _df_to_response(df, symbol, market, trigger_time, "Finnhub")
    except Exception as e:
        return {
            "symbol": symbol,
            "market": market,
            "data_source": "Finnhub",
            "trigger_time": trigger_time,
            "error": f"Dividend data unavailable: {str(e)}",
        }


class CompanySharesOutstandingInput(BaseModel):
    market: str = Field(description="The market of the company.")
    symbol: str = Field(description="The symbol of the company.")
    trigger_time: str = Field(description="The trigger time. Format: YYYY-MM-DD HH:MM:SS.")


@smart_tool(
    description="Get the shares outstanding of a US company using Finnhub company_profile2",
    args_schema=CompanySharesOutstandingInput,
    max_output_len=1000,
    timeout_seconds=10.0
)
async def company_shares_outstanding(market: str, symbol: str, trigger_time: str = None) -> Dict[str, Any]:
    if market != "US-Stock":
        return {"error": "Market not supported. Only US-Stock is supported."}
    try:
        profile = finnhub_cached.run('company_profile2', {'symbol': symbol}, verbose=False)
        return {
            "symbol": symbol,
            "market": market,
            "data_source": "Finnhub",
            "trigger_time": trigger_time,
            "shares_outstanding": profile.get('shareOutstanding') if isinstance(profile, dict) else None,
            "name": profile.get('name') if isinstance(profile, dict) else None,
        }
    except Exception as e:
        return {"error": f"Failed to get shares outstanding: {str(e)}"}


if __name__ == "__main__":
    result = asyncio.run(company_financial_info.ainvoke(
        {
            "market": "US-Stock",
            "symbol": "AAPL",
            "sheet_name": "income_statement",
            "trigger_time": "2026-09-23 09:00:00",
        }
    ))
    print(result)
