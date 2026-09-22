"""
US Earnings & IPO Events data source
美股财报日历 / IPO 事件数据源
替代原 Polygon 新闻，输出事件层面文本因子
返回 DataFrame 列: ['title', 'content', 'pub_time', 'url']
"""
import pandas as pd
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any

from data_source.data_source_base import DataSourceBase
from utils.fmp_utils import fmp_cached
from utils.finnhub_utils import finnhub_cached
from utils.date_utils import get_previous_trading_date
from models.llm_model import GLOBAL_LLM
from config.config import cfg
from loguru import logger


class USEarningsEvents(DataSourceBase):
    def __init__(self):
        super().__init__("us_earnings_events")

    async def _get_earnings_calendar(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """从 FMP 获取财报日历（包含已发布和待发布）"""
        try:
            data = fmp_cached.run(
                'earnings-calendar',
                {'from': start_date, 'to': end_date, 'limit': 200},
                verbose=False
            )
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"FMP earnings calendar failed: {e}")
            return []

    async def _get_ipo_calendar(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """从 Finnhub 获取 IPO 日历"""
        try:
            data = finnhub_cached.run(
                'ipo_calendar',
                {'_from': start_date, 'to': end_date},
                verbose=False
            )
            if isinstance(data, dict):
                return data.get('ipoCalendar', [])
            return []
        except Exception as e:
            logger.warning(f"Finnhub IPO calendar failed: {e}")
            return []

    def _format_raw_text(self, earnings: List[Dict[str, Any]], ipos: List[Dict[str, Any]], as_of: str) -> str:
        """把原始数据整理成给 LLM 的文本"""
        lines = [f"US Earnings & IPO Event Calendar (as of {as_of})", "=" * 50]

        # 财报：已发布 vs 待发布
        reported = [e for e in earnings if e.get('epsActual') is not None]
        upcoming = [e for e in earnings if e.get('epsActual') is None and e.get('epsEstimated') is not None]

        lines.append(f"\n[Earnings Reported] (count: {len(reported)})")
        for e in sorted(reported, key=lambda x: x.get('date', ''), reverse=True)[:30]:
            symbol = e.get('symbol', 'N/A')
            date = e.get('date', 'N/A')
            eps_a = e.get('epsActual', 'N/A')
            eps_e = e.get('epsEstimated', 'N/A')
            rev_a = e.get('revenueActual', 'N/A')
            rev_e = e.get('revenueEstimated', 'N/A')
            eps_beat = ""
            if isinstance(eps_a, (int, float)) and isinstance(eps_e, (int, float)) and eps_e != 0:
                eps_beat = f", EPS beat {(eps_a - eps_e) / abs(eps_e) * 100:+.1f}%"
            lines.append(f"- {symbol} {date}: EPS actual {eps_a} vs est {eps_e}{eps_beat}, Revenue actual {rev_a} vs est {rev_e}")

        lines.append(f"\n[Upcoming Earnings] (count: {len(upcoming)})")
        for e in sorted(upcoming, key=lambda x: x.get('date', ''))[:40]:
            symbol = e.get('symbol', 'N/A')
            date = e.get('date', 'N/A')
            eps_e = e.get('epsEstimated', 'N/A')
            rev_e = e.get('revenueEstimated', 'N/A')
            lines.append(f"- {symbol} {date}: EPS est {eps_e}, Revenue est {rev_e}")

        lines.append(f"\n[IPO Calendar] (count: {len(ipos)})")
        for ipo in sorted(ipos, key=lambda x: x.get('date', ''))[:20]:
            name = ipo.get('name', 'N/A')
            symbol = ipo.get('symbol', 'N/A')
            date = ipo.get('date', 'N/A')
            exchange = ipo.get('exchange', 'N/A')
            price = ipo.get('price', 'N/A')
            shares = ipo.get('numberOfShares', 'N/A')
            status = ipo.get('status', 'N/A')
            lines.append(f"- {name} ({symbol}) {date} @ {exchange}, price {price}, shares {shares}, status {status}")

        return "\n".join(lines)

    async def _summarize(self, raw_text: str) -> str:
        """用 LLM 把原始事件数据提炼成可读的文本因子"""
        if not raw_text.strip():
            return "No earnings or IPO data available."

        prompt = f"""You are a US equity market analyst. Based on the following earnings and IPO calendar data, write a concise macro/event factor summary (within 250 words) for the next trading session.

Requirements:
1. Highlight the most important upcoming earnings (large-cap or high estimate) and any notable recent earnings surprises.
2. Mention any significant IPOs in the window.
3. Note sectors/themes that appear repeatedly.
4. Provide brief risk reminders (e.g., high-profile misses, crowded events).
5. Respond in {cfg.system_language} language, concise and professional.

Data:
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
            logger.warning(f"LLM summary failed for earnings events: {e}")
            return raw_text[:4000] + "\n\n[LLM summary unavailable; raw data above]"

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            cached = self.get_data_cached(trigger_time)
            if cached is not None:
                return cached

            trade_date_str = get_previous_trading_date(
                trigger_time,
                market_name="US-Stock",
                output_format="%Y-%m-%d"
            )
            trigger_date = datetime.strptime(trigger_time.split(" ")[0], "%Y-%m-%d")

            # 回望 7 天 + 前瞻 14 天
            start_date = (trigger_date - timedelta(days=7)).strftime("%Y-%m-%d")
            end_date = (trigger_date + timedelta(days=14)).strftime("%Y-%m-%d")

            logger.info(f"Getting US earnings & IPO events for {start_date} ~ {end_date}")

            earnings, ipos = await asyncio.gather(
                self._get_earnings_calendar(start_date, end_date),
                self._get_ipo_calendar(start_date, end_date)
            )

            raw_text = self._format_raw_text(earnings, ipos, trigger_date.strftime("%Y-%m-%d"))
            summary = await self._summarize(raw_text)

            df = pd.DataFrame([{
                "title": f"{trade_date_str}: US Earnings & IPO Events Summary",
                "content": summary,
                "pub_time": trigger_time,
                "url": None
            }])

            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            logger.error(f"Failed to get US earnings & IPO events: {e}")
            return pd.DataFrame()


if __name__ == "__main__":
    agent = USEarningsEvents()
    result = asyncio.run(agent.get_data("2026-09-23 09:00:00"))
    print(result['content'].values.tolist())
