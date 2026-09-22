"""
US Macro News data source
美股宏观/行业新闻数据源
从 Finnhub general_news 获取市场级新闻，输出文本因子
返回 DataFrame 列: ['title', 'content', 'pub_time', 'url']
"""
import pandas as pd
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any

from data_source.data_source_base import DataSourceBase
from utils.finnhub_utils import finnhub_cached
from models.llm_model import GLOBAL_LLM
from config.config import cfg
from loguru import logger


class USMacroNews(DataSourceBase):
    def __init__(self):
        super().__init__("us_macro_news")

    async def _get_general_news(self, trigger_dt: datetime) -> List[Dict[str, Any]]:
        """获取 Finnhub 市场新闻并过滤时间窗口"""
        try:
            data = finnhub_cached.run(
                'general_news',
                {'category': 'general', 'min_id': 0},
                verbose=False
            )
            if not isinstance(data, list):
                return []

            # 取触发时间前后 48 小时内的前 50 条
            start_ts = int((trigger_dt - timedelta(days=2)).timestamp())
            end_ts = int(trigger_dt.timestamp())

            filtered = [
                item for item in data
                if isinstance(item, dict) and start_ts <= item.get('datetime', 0) <= end_ts
            ]
            filtered.sort(key=lambda x: x.get('datetime', 0), reverse=True)
            return filtered[:50]
        except Exception as e:
            logger.warning(f"Finnhub general_news failed: {e}")
            return []

    def _format_raw_text(self, news_list: List[Dict[str, Any]]) -> str:
        """把新闻整理成给 LLM 的文本"""
        if not news_list:
            return "No general market news available in the selected window."

        lines = [f"US Market News Summary ({len(news_list)} items)", "=" * 50]
        for i, item in enumerate(news_list, 1):
            ts = item.get('datetime', 0)
            dt_str = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M') if ts else 'N/A'
            lines.append(
                f"{i}. [{dt_str}] {item.get('source', 'N/A')} - {item.get('headline', '')}\n"
                f"   Summary: {item.get('summary', '')}"
            )
        return "\n\n".join(lines)

    async def _summarize(self, raw_text: str) -> str:
        """用 LLM 把新闻提炼成宏观/行业文本因子"""
        if not raw_text.strip():
            return "No macro news available."

        prompt = f"""You are a US equity market analyst. Based on the following market news, write a concise macro/industry factor summary (within 250 words) for the next trading session.

Requirements:
1. Identify the most important macro themes (Fed, geopolitics, commodities, FX, policy).
2. Note sectors or industries that are repeatedly mentioned.
3. Provide a brief sentiment tilt (risk-on / risk-off / mixed) and key risk reminders.
4. Respond in {cfg.system_language} language, concise and professional.

News:
{raw_text}
"""
        try:
            response = await GLOBAL_LLM.a_run(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
                verbose=False,
                thinking=False
            )
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.warning(f"LLM summary failed for macro news: {e}")
            return raw_text[:4000] + "\n\n[LLM summary unavailable; raw news above]"

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            cached = self.get_data_cached(trigger_time)
            if cached is not None:
                return cached

            trigger_dt = datetime.strptime(trigger_time.split(" ")[0], "%Y-%m-%d")
            logger.info(f"Getting US macro news up to {trigger_dt}")

            news = await self._get_general_news(trigger_dt)
            raw_text = self._format_raw_text(news)
            summary = await self._summarize(raw_text)

            df = pd.DataFrame([{
                "title": f"{trigger_dt.strftime('%Y-%m-%d')}: US Macro & Industry News Summary",
                "content": summary,
                "pub_time": trigger_time,
                "url": None
            }])

            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            logger.error(f"Failed to get US macro news: {e}")
            return pd.DataFrame()


if __name__ == "__main__":
    agent = USMacroNews()
    result = asyncio.run(agent.get_data("2026-09-23 09:00:00"))
    print(result['content'].values.tolist())
