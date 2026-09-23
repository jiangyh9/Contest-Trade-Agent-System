"""
US Analyst Sentiment data source
美股分析师情绪 + 机构持仓文本数据源
从 Finnhub 获取分析师评级趋势、目标价、机构持仓，
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


WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META",
    "TSLA", "JPM", "UNH", "XOM", "LLY", "V"
]

# Finnhub 免费 tier 下 price_target / institutional_ownership 通常为 403（付费）
# 设为 False 可避免每个 run 白白浪费调用额度
USE_PAID_FINNHUB_ENDPOINTS = False


class USAnalystSentiment(DataSourceBase):
    def __init__(self):
        super().__init__("us_analyst_sentiment")

    def _safe_run(self, func_name: str, kwargs: dict) -> Any:
        try:
            return finnhub_cached.run(func_name, kwargs, verbose=False)
        except Exception as e:
            logger.debug(f"Finnhub {func_name}({kwargs}) failed: {e}")
            return None

    def _date_range(self, trigger_dt: datetime, lookback_days: int) -> Tuple[str, str]:
        start = (trigger_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        end = trigger_dt.strftime("%Y-%m-%d")
        return start, end

    async def _collect(self, trigger_dt: datetime) -> Dict[str, Any]:
        recommendations: List[Dict[str, Any]] = []
        price_targets: List[Dict[str, Any]] = []
        institutional: Dict[str, Dict[str, float]] = {}
        inst_start, inst_end = self._date_range(trigger_dt, 180)

        for symbol in WATCHLIST:
            # 1) recommendation trends
            rec = self._safe_run('recommendation_trends', {'symbol': symbol})
            if isinstance(rec, list) and rec:
                latest = rec[-1]
                recommendations.append({
                    'symbol': symbol,
                    'period': latest.get('period'),
                    'strong_buy': latest.get('strongBuy', 0),
                    'buy': latest.get('buy', 0),
                    'hold': latest.get('hold', 0),
                    'sell': latest.get('sell', 0),
                    'strong_sell': latest.get('strongSell', 0),
                })

            # 2) price target（付费 endpoint，默认跳过）
            if USE_PAID_FINNHUB_ENDPOINTS:
                pt = self._safe_run('price_target', {'symbol': symbol})
                if isinstance(pt, dict) and pt.get('numberOfAnalysts', 0):
                    price_targets.append({
                        'symbol': symbol,
                        'number_of_analysts': pt.get('numberOfAnalysts', 0),
                        'target_high': pt.get('targetHigh', 0),
                        'target_low': pt.get('targetLow', 0),
                        'target_mean': pt.get('targetMean', 0),
                        'target_median': pt.get('targetMedian', 0),
                    })

            # 3) institutional ownership（付费 endpoint，默认跳过）
            if USE_PAID_FINNHUB_ENDPOINTS:
                io = self._safe_run('institutional_ownership', {
                    'symbol': symbol,
                    'cusip': '',
                    '_from': inst_start,
                    'to': inst_end
                })
                if isinstance(io, dict) and io.get('data'):
                    total_shares = 0.0
                    total_change = 0.0
                    for holder in io['data']:
                        shares = holder.get('shares') or holder.get('totalShares') or 0
                        change = holder.get('change') or holder.get('shareChange') or 0
                        total_shares += float(shares) if isinstance(shares, (int, float, str)) else 0
                        total_change += float(change) if isinstance(change, (int, float, str)) else 0
                    institutional[symbol] = {
                        'holders': len(io['data']),
                        'total_shares': total_shares,
                        'net_change': total_change,
                    }

        return {
            'recommendations': recommendations,
            'price_targets': price_targets,
            'institutional': institutional,
        }

    def _format_raw_text(self, trigger_dt: datetime, data: Dict[str, Any]) -> str:
        lines = [f"US Analyst & Institutional Sentiment as of {trigger_dt.strftime('%Y-%m-%d')}", "=" * 60]

        recs = data['recommendations']
        if recs:
            total = {
                'strong_buy': sum(r['strong_buy'] for r in recs),
                'buy': sum(r['buy'] for r in recs),
                'hold': sum(r['hold'] for r in recs),
                'sell': sum(r['sell'] for r in recs),
                'strong_sell': sum(r['strong_sell'] for r in recs),
            }
            lines.append(f"\n1) Aggregate Analyst Ratings (latest month, {len(recs)} symbols)")
            lines.append(
                f"   StrongBuy={total['strong_buy']}, Buy={total['buy']}, Hold={total['hold']}, "
                f"Sell={total['sell']}, StrongSell={total['strong_sell']}"
            )
            # 最偏正面/负面的单个 symbol
            by_bull = sorted(recs, key=lambda r: r['strong_buy'] + r['buy'], reverse=True)[:3]
            by_bear = sorted(recs, key=lambda r: r['sell'] + r['strong_sell'], reverse=True)[:3]
            lines.append("   Top bullish symbols: " + ", ".join(f"{r['symbol']}(+{r['strong_buy']+r['buy']})" for r in by_bull))
            lines.append("   Top bearish symbols: " + ", ".join(f"{r['symbol']}(-{r['sell']+r['strong_sell']})" for r in by_bear))

        pts = data['price_targets']
        if pts:
            lines.append(f"\n2) Price Targets ({len(pts)} symbols with data)")
            by_coverage = sorted(pts, key=lambda x: x['number_of_analysts'], reverse=True)[:5]
            for pt in by_coverage:
                lines.append(
                    f"   {pt['symbol']}: analysts={pt['number_of_analysts']}, "
                    f"mean=${pt['target_mean']:.2f}, median=${pt['target_median']:.2f}, "
                    f"range=[${pt['target_low']:.2f}, ${pt['target_high']:.2f}]"
                )
            # 目标价中位数与高低范围汇总
            mean_targets = [p['target_mean'] for p in pts]
            lines.append(f"   Cross-symbol mean-target range: ${min(mean_targets):.2f} ~ ${max(mean_targets):.2f}")

        io = data['institutional']
        if io:
            lines.append(f"\n3) Institutional Ownership Net Change ({len(io)} symbols)")
            sorted_io = sorted(io.items(), key=lambda x: x[1]['net_change'], reverse=True)
            for sym, v in sorted_io[:8]:
                lines.append(
                    f"   {sym}: holders={v['holders']}, total_shares={v['total_shares']:.0f}, net_change={v['net_change']:.0f}"
                )

        if len(lines) == 2:
            lines.append("No analyst/institutional data available.")

        return "\n".join(lines)

    async def _summarize(self, raw_text: str) -> str:
        if not raw_text.strip():
            return "No analyst sentiment data available."

        prompt = f"""You are a US equity sentiment analyst. Based on the aggregated analyst ratings, price targets, and institutional ownership changes below, write a concise market-level text factor summary (within 250 words) for the next trading session.

Requirements:
1. Summarize overall analyst sentiment (bullish/bearish tilt, upgrades vs downgrades).
2. Highlight symbols or groups with notable analyst conviction or target price dispersion.
3. Note any institutional accumulation/distribution patterns and whether they support or contradict analyst views.
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
            logger.warning(f"LLM summary failed for analyst sentiment: {e}")
            return raw_text[:4000] + "\n\n[LLM summary unavailable; raw data above]"

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            cached = self.get_data_cached(trigger_time)
            if cached is not None:
                return cached

            trigger_dt = datetime.strptime(trigger_time.split(" ")[0], "%Y-%m-%d")
            logger.info(f"Getting US analyst sentiment up to {trigger_dt}")

            data = await self._collect(trigger_dt)
            raw_text = self._format_raw_text(trigger_dt, data)
            summary = await self._summarize(raw_text)

            df = pd.DataFrame([{
                "title": f"{trigger_dt.strftime('%Y-%m-%d')}: US Analyst & Institutional Sentiment Summary",
                "content": summary,
                "pub_time": trigger_time,
                "url": None
            }])

            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            logger.error(f"Failed to get US analyst sentiment: {e}")
            return pd.DataFrame()


if __name__ == "__main__":
    agent = USAnalystSentiment()
    result = asyncio.run(agent.get_data("2026-09-23 09:00:00"))
    print(result['content'].values.tolist())
