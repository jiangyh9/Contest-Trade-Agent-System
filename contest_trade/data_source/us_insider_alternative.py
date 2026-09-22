"""
US Insider & Alternative Data data source
美股内幕交易 + 另类文本数据源
从 Finnhub 获取内幕交易、游说、政府合同、专利等另类数据，
聚合为市场级文本因子。
返回 DataFrame 列: ['title', 'content', 'pub_time', 'url']
"""
import pandas as pd
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple

from data_source.data_source_base import DataSourceBase
from utils.finnhub_utils import finnhub_cached
from models.llm_model import GLOBAL_LLM
from config.config import cfg
from loguru import logger


# 用于聚合的代表性大盘股池
WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META",
    "TSLA", "JPM", "UNH", "XOM", "LLY", "V"
]


class USInsiderAlternative(DataSourceBase):
    def __init__(self):
        super().__init__("us_insider_alternative")

    def _date_range(self, trigger_dt: datetime, lookback_days: int) -> Tuple[str, str]:
        start = (trigger_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        end = trigger_dt.strftime("%Y-%m-%d")
        return start, end

    def _safe_run(self, func_name: str, kwargs: dict) -> Any:
        """带错误隔离的 Finnhub 调用"""
        try:
            return finnhub_cached.run(func_name, kwargs, verbose=False)
        except Exception as e:
            logger.debug(f"Finnhub {func_name}({kwargs}) failed: {e}")
            return None

    async def _collect(self, trigger_dt: datetime) -> Dict[str, Any]:
        """并行收集所有符号的另类数据（基于同步调用）"""
        insider_start, insider_end = self._date_range(trigger_dt, 90)
        alt_start, alt_end = self._date_range(trigger_dt, 180)

        insider_buy_sell: Dict[str, Dict[str, float]] = {}
        insider_sentiment: List[Dict[str, Any]] = []
        lobbying: Dict[str, float] = {}
        patents: Dict[str, int] = {}
        usa_spending: Dict[str, float] = {}

        for symbol in WATCHLIST:
            # 1) insider transactions
            tx_data = self._safe_run('stock_insider_transactions', {
                'symbol': symbol,
                '_from': insider_start,
                'to': insider_end
            })
            if isinstance(tx_data, dict) and 'data' in tx_data:
                total_change = 0.0
                buy_count = 0
                sell_count = 0
                for tx in tx_data['data']:
                    change = tx.get('change') or tx.get('share') or 0
                    code = (tx.get('transactionCode') or '').upper()
                    total_change += float(change) if isinstance(change, (int, float, str)) else 0
                    if code in ('P', 'B', 'A'):
                        buy_count += 1
                    elif code in ('S', 'D', 'G'):
                        sell_count += 1
                insider_buy_sell[symbol] = {
                    'net_shares': total_change,
                    'buy_count': buy_count,
                    'sell_count': sell_count
                }

            # 2) insider sentiment (monthly mspr)
            sent_data = self._safe_run('stock_insider_sentiment', {
                'symbol': symbol,
                '_from': insider_start,
                'to': insider_end
            })
            if isinstance(sent_data, dict) and sent_data.get('data'):
                latest = sent_data['data'][-1]
                insider_sentiment.append({
                    'symbol': symbol,
                    'month': latest.get('month'),
                    'year': latest.get('year'),
                    'mspr': latest.get('mspr', 0),
                    'change': latest.get('change', 0),
                })

            # 3) lobbying spend
            lob_data = self._safe_run('stock_lobbying', {
                'symbol': symbol,
                '_from': alt_start,
                'to': alt_end
            })
            if isinstance(lob_data, dict) and lob_data.get('data'):
                amount = sum(
                    float(item.get('amount') or item.get('income') or item.get('expenses') or 0)
                    for item in lob_data['data']
                )
                lobbying[symbol] = amount

            # 4) patent count
            pat_data = self._safe_run('stock_uspto_patent', {
                'symbol': symbol,
                '_from': alt_start,
                'to': alt_end
            })
            if isinstance(pat_data, dict) and pat_data.get('data'):
                patents[symbol] = len(pat_data['data'])

            # 5) US government spending
            spend_data = self._safe_run('stock_usa_spending', {
                'symbol': symbol,
                '_from': alt_start,
                'to': alt_end
            })
            if isinstance(spend_data, dict) and spend_data.get('data'):
                obligated = sum(
                    float(item.get('obligatedAmount') or item.get('totalValue') or item.get('outlayedAmount') or 0)
                    for item in spend_data['data']
                )
                usa_spending[symbol] = obligated

        return {
            'insider_buy_sell': insider_buy_sell,
            'insider_sentiment': insider_sentiment,
            'lobbying': lobbying,
            'patents': patents,
            'usa_spending': usa_spending,
        }

    def _format_raw_text(self, trigger_dt: datetime, data: Dict[str, Any]) -> str:
        lines = [f"US Insider & Alternative Data as of {trigger_dt.strftime('%Y-%m-%d')}", "=" * 60]

        insider_bs = data['insider_buy_sell']
        if insider_bs:
            lines.append("\n1) Insider Net Share Change (90 days)")
            sorted_bs = sorted(insider_bs.items(), key=lambda x: x[1]['net_shares'], reverse=True)
            for sym, v in sorted_bs:
                lines.append(
                    f"   {sym}: net_shares={v['net_shares']:.0f}, buy_tx={v['buy_count']}, sell_tx={v['sell_count']}"
                )

        sent = data['insider_sentiment']
        if sent:
            avg_mspr = sum(s.get('mspr', 0) for s in sent) / len(sent)
            lines.append(f"\n2) Insider Sentiment (latest monthly MSPR): avg={avg_mspr:.3f} across {len(sent)} symbols")
            sorted_sent = sorted(sent, key=lambda x: x.get('mspr', 0), reverse=True)
            for s in sorted_sent:
                lines.append(f"   {s['symbol']} ({s['year']}-{s['month']}): mspr={s.get('mspr', 0):.3f}, change={s.get('change', 0):.3f}")

        if data['lobbying']:
            lines.append("\n3) Lobbying Spend (180 days)")
            for sym, amt in sorted(data['lobbying'].items(), key=lambda x: x[1], reverse=True):
                lines.append(f"   {sym}: ${amt:,.0f}")

        if data['patents']:
            lines.append("\n4) USPTO Patent Counts (180 days)")
            for sym, cnt in sorted(data['patents'].items(), key=lambda x: x[1], reverse=True):
                lines.append(f"   {sym}: {cnt} patents")

        if data['usa_spending']:
            lines.append("\n5) US Government Spending/Obligations (180 days)")
            for sym, amt in sorted(data['usa_spending'].items(), key=lambda x: x[1], reverse=True):
                lines.append(f"   {sym}: ${amt:,.0f}")

        if len(lines) == 2:
            lines.append("No alternative data available for the selected window.")

        return "\n".join(lines)

    async def _summarize(self, raw_text: str) -> str:
        if not raw_text.strip():
            return "No insider/alternative data available."

        prompt = f"""You are a US equity analyst specializing in insider and alternative data. Based on the aggregated data below, write a concise market-level text factor summary (within 250 words) for the next trading session.

Requirements:
1. Highlight the strongest insider buying/selling signals and any concentrated sector patterns.
2. Note any unusually high lobbying, government spending, or patent activity and what it might imply.
3. Provide a balanced risk note (e.g., insider sales can be pre-planned).
4. Respond in {cfg.system_language} language, concise and professional.

Data:
{raw_text}
"""
        try:
            response = await GLOBAL_LLM.a_run(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=900,
                verbose=False,
                thinking=False
            )
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.warning(f"LLM summary failed for insider/alternative data: {e}")
            return raw_text[:4000] + "\n\n[LLM summary unavailable; raw data above]"

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            cached = self.get_data_cached(trigger_time)
            if cached is not None:
                return cached

            trigger_dt = datetime.strptime(trigger_time.split(" ")[0], "%Y-%m-%d")
            logger.info(f"Getting US insider & alternative data up to {trigger_dt}")

            data = await self._collect(trigger_dt)
            raw_text = self._format_raw_text(trigger_dt, data)
            summary = await self._summarize(raw_text)

            df = pd.DataFrame([{
                "title": f"{trigger_dt.strftime('%Y-%m-%d')}: US Insider & Alternative Data Summary",
                "content": summary,
                "pub_time": trigger_time,
                "url": None
            }])

            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            logger.error(f"Failed to get US insider/alternative data: {e}")
            return pd.DataFrame()


if __name__ == "__main__":
    agent = USInsiderAlternative()
    result = asyncio.run(agent.get_data("2026-09-23 09:00:00"))
    print(result['content'].values.tolist())
