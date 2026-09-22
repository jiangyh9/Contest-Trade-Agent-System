"""
US Price Market data source
美股价格市场数据源（替代原price_market.py）
整合美股K线数据、板块轮动、资金流向等，生成综合宏观市场分析
返回DataFrame列: ['title', 'content', 'pub_time', 'url']
""" 
import pandas as pd
import asyncio
from datetime import datetime, timedelta
from data_source.data_source_base import DataSourceBase
from utils.finnhub_utils import finnhub_cached
from models.llm_model import GLOBAL_LLM
from loguru import logger
from utils.date_utils import get_previous_trading_date
from config.config import cfg


class USPriceMarket(DataSourceBase):
    def __init__(self):
        super().__init__("us_price_market")

    def _get_sector_performance(self, trade_date_str: str) -> dict:
        """获取美股行业表现（用 Finnhub quote，免费计划支持 ETF）"""
        sector_etfs = {
            'XLK': 'Technology',
            'XLF': 'Financial',
            'XLE': 'Energy',
            'XLV': 'Healthcare',
            'XLI': 'Industrial',
            'XLY': 'Consumer Discretionary',
            'XLP': 'Consumer Staples',
            'XLU': 'Utilities',
            'XLB': 'Materials',
            'XLRE': 'Real Estate',
            'XLC': 'Communication Services'
        }

        performance_data = {}

        for etf, sector_name in sector_etfs.items():
            try:
                quote = finnhub_cached.run('quote', {'symbol': etf}, verbose=False)
                if quote and quote.get('c') is not None and quote.get('pc', 0) > 0:
                    change_pct = quote.get('dp', 0.0)
                    performance_data[sector_name] = {
                        'symbol': etf,
                        'change_pct': change_pct,
                        'close': quote['c'],
                        'volume_ratio': 1.0  # Finnhub quote 不带 volume，暂不提供量比
                    }
            except Exception as e:
                logger.warning(f"Failed to get data for {etf}({sector_name}): {e}")
                continue

        return performance_data

    def _get_market_breadth(self, trade_date_str: str) -> dict:
        """获取主要指数表现（用 Finnhub quote）"""
        indices = ['SPY', 'QQQ', 'DIA', 'IWM']
        index_data = {}

        for symbol in indices:
            try:
                quote = finnhub_cached.run('quote', {'symbol': symbol}, verbose=False)
                if quote and quote.get('c') is not None and quote.get('pc', 0) > 0:
                    index_data[symbol] = {
                        'change_pct': quote.get('dp', 0.0),
                        'close': quote['c'],
                        'volume': None  # Finnhub quote 不带 volume
                    }
            except Exception:
                continue

        return index_data

    async def _generate_llm_summary(self, trade_date: str) -> dict:
        """Use LLM to generate market analysis summary"""
        try:
            # 获取数据
            sector_data = self._get_sector_performance(trade_date)
            market_data = self._get_market_breadth(trade_date)
            
            # 构造分析内容
            analysis_content = f"""US Stock Market Data Analysis - {trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}

[Major Index Performance]
"""
            
            for symbol, data in market_data.items():
                analysis_content += f"{symbol}: {data['close']:.2f} ({data['change_pct']:+.2f}%)\n"
            
            analysis_content += "\n[Sector Performance]\n"
            
            # 按涨跌幅排序
            sorted_sectors = sorted(sector_data.items(), key=lambda x: x[1]['change_pct'], reverse=True)
            
            for sector_name, data in sorted_sectors:
                analysis_content += f"{sector_name}({data['symbol']}): {data['close']:.2f} ({data['change_pct']:+.2f}%)\n"
            
            analysis_content += "\n[Capital Flow Analysis]\n"
            # Finnhub free quote 不带 volume，仅做提示
            analysis_content += "Volume data not available in free-tier quote; focus on price change and sector rotation.\n"

            # LLM分析
            prompt = f"""Based on the following US stock market data, generate a concise investment insight analysis (within 200 words):

{analysis_content}

Requirements:
1. Analyze the performance characteristics of major indices and sectors
2. Identify capital flows and hot sectors
3. Provide brief market judgment and risk warnings
4. Please respond in {cfg.system_language} language, concise and professional"""

            try:
                llm_response = await GLOBAL_LLM.a_run([{"role": "user", "content": prompt}], verbose=False)
                llm_summary = llm_response.content if hasattr(llm_response, 'content') else str(llm_response)
            except Exception as e:
                logger.warning(f"LLM analysis failed: {e}")
                llm_summary = "LLM analysis is temporarily unavailable, please refer to the above data for judgment."
            
            final_content = analysis_content + f"\n[AI Market Insights]\n{llm_summary}"
            
            return {
                "llm_summary": final_content,
                "raw_data": {
                    "sector_performance": sector_data,
                    "market_breadth": market_data
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to generate LLM analysis: {e}")
            return {
                "llm_summary": f"Market data analysis generation failed: {str(e)}",
                "raw_data": {}
            }

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            # 检查缓存
            df = self.get_data_cached(trigger_time)
            if df is not None:
                return df
            
            # 获取交易日（美股日历）
            trade_date = get_previous_trading_date(trigger_time, market_name="US-Stock")
            logger.info(f"Getting US stock price market data for {trade_date}")

            # 生成LLM分析
            llm_summary_dict = await self._generate_llm_summary(trade_date)
            
            # 构造返回数据
            data = [{
                "title": f"{trade_date}: US Stock Market Macro Data Summary",
                "content": llm_summary_dict["llm_summary"],
                "pub_time": trigger_time,
                "url": None
            }]
            
            df = pd.DataFrame(data)

            logger.info(f"Caching US stock price market data for {trade_date}")
            self.save_data_cached(trigger_time, df)

            return df
                
        except Exception as e:
            logger.error(f"Failed to get US stock price market data: {e}")
            return pd.DataFrame()


if __name__ == "__main__":
    price_market = USPriceMarket()
    result = asyncio.run(price_market.get_data("2024-12-01 15:00:00"))
    print(result['content'].values.tolist())
