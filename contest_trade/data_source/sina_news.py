"""
sina news data source
"""
import asyncio
import re
import pandas as pd
from utils.tushare_utils import tushare_cached
from utils.date_utils import get_previous_trading_date
from data_source.data_source_base import DataSourceBase
from loguru import logger

class SinaNews(DataSourceBase):
    def __init__(self):
        super().__init__("sina_news")

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        previous_trading_datetime = get_previous_trading_date(trigger_time, output_format="%Y-%m-%d %H:%M:%S")
        df = tushare_cached.run(
            func_name="major_news", 
            func_kwargs={
                "src": "新浪财经",
                "start_date": previous_trading_datetime, 
                "end_date": trigger_time,
                "fields": "title,content,pub_time, url"
            }
        )
        if 'content' in df.columns:
            df['content'] = df['content'].apply(lambda x: re.sub(r'<[^>]*>', '', str(x)))
        
        logger.info(f"get sina news from {previous_trading_datetime} to {trigger_time} success. Total {len(df)} rows")
        return df

if __name__ == "__main__":
    sina_news = SinaNews()
    print(asyncio.run(sina_news.get_data("2025-01-01 10:00:00")))


