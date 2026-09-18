"""
Backtest Runner - 历史回测

对一段历史日期范围内，每一天 09:00:00 运行一次完整 ContestTrade 流程，
只使用支持历史 trigger_time 的 Tushare/AKShare 数据源。
输出：
- 每日信号报告
- 淘汰赛 leaderboard 随时间演化
- 累计收益统计
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# 确保 contest_trade 在 sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.append(str(PROJECT_ROOT))

from utils.market_manager import GLOBAL_MARKET_MANAGER


class BacktestRunner:
    """历史回测运行器"""

    def __init__(
        self,
        start_date: str,
        end_date: str,
        market: str = "CN-Stock",
        output_dir: Optional[Path] = None,
        force_recompute: bool = False,
    ):
        self.market = market
        self.start_date = start_date
        self.end_date = end_date
        self.force_recompute = force_recompute
        self.output_dir = output_dir or (PROJECT_ROOT.parent / "backtest_results")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[Dict] = []

    def get_trading_dates(self) -> List[str]:
        """获取回测区间内的交易日列表（YYYY-MM-DD）"""
        try:
            trade_dates = GLOBAL_MARKET_MANAGER.get_trade_date(market_name=self.market)
            start = self.start_date.replace("-", "")
            end = self.end_date.replace("-", "")
            selected = [d for d in trade_dates if start <= d <= end]
            return [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in selected]
        except Exception as e:
            print(f"获取交易日失败: {e}，退回到自然日")
            dates = []
            current = datetime.strptime(self.start_date, "%Y-%m-%d")
            end = datetime.strptime(self.end_date, "%Y-%m-%d")
            while current <= end:
                dates.append(current.strftime("%Y-%m-%d"))
                current += timedelta(days=1)
            return dates

    async def run_single_date(self, date_str: str) -> Dict:
        """运行单个交易日"""
        trigger_time = f"{date_str} 09:00:00"
        print(f"\n{'='*60}")
        print(f"🔄 回测日期: {trigger_time}")
        print(f"{'='*60}")

        from main import SimpleTradeCompany
        from langchain_core.runnables import RunnableConfig

        company = SimpleTradeCompany()
        config = RunnableConfig(recursion_limit=200)
        final_state = await company.run_company(trigger_time, config=config)

        step_results = final_state.get('step_results', {})
        research_team = step_results.get('research_team', {})
        best_signals = step_results.get('contest', {}).get('best_signals', [])
        valid_signals = [s for s in best_signals if s.get('has_opportunity', 'no') == 'yes']

        result = {
            "trigger_time": trigger_time,
            "data_factors_count": step_results.get('data_team', {}).get('factors_count', 0),
            "research_signals_count": research_team.get('signals_count', 0),
            "valid_signals_count": len(valid_signals),
            "signals": valid_signals,
            "data_tiers": step_results.get('data_team', {}).get('data_tiers', {}),
            "research_tiers": research_team.get('research_tiers', {}),
        }

        # 保存当日报告
        day_file = self.output_dir / f"day_{date_str}.json"
        with open(day_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    async def run(self) -> Dict:
        """运行整个回测区间"""
        dates = self.get_trading_dates()
        print(f"📅 回测区间: {self.start_date} ~ {self.end_date}, 共 {len(dates)} 个交易日")

        # 设置环境变量
        os.environ['CONTEST_TRADE_MARKET'] = self.market
        os.environ['CONTEST_TRADE_BACKTEST'] = 'true'

        if self.force_recompute:
            # 清理回测相关缓存：只清理 backtest 配置对应的数据源输出
            # 注意：这会删除 agents_workspace 下所有缓存，生产回测请谨慎
            workspace = PROJECT_ROOT.parent / "agents_workspace"
            if workspace.exists():
                import shutil
                shutil.rmtree(workspace)
                print("🧹 已强制清除 agents_workspace 缓存")

        self.results = []
        for date_str in dates:
            try:
                result = await self.run_single_date(date_str)
                self.results.append(result)
            except Exception as e:
                print(f"❌ {date_str} 回测失败: {e}")
                import traceback
                traceback.print_exc()
                self.results.append({
                    "trigger_time": f"{date_str} 09:00:00",
                    "error": str(e),
                })

        # 生成汇总
        summary = self._build_summary()
        summary_file = self.output_dir / "summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"\n✅ 回测完成，结果保存到: {self.output_dir}")
        print(f"   总交易日: {len(dates)}")
        print(f"   成功: {len([r for r in self.results if 'error' not in r])}")
        print(f"   失败: {len([r for r in self.results if 'error' in r])}")

        return summary

    def _build_summary(self) -> Dict:
        """构建回测汇总"""
        summary = {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "market": self.market,
            "total_days": len(self.results),
            "success_days": len([r for r in self.results if 'error' not in r]),
            "daily_results": self.results,
        }

        # 按风险画像统计每日信号数
        profile_signals: Dict[str, List[int]] = {}
        for r in self.results:
            if 'error' in r or 'signals' not in r:
                continue
            day_counts: Dict[str, int] = {}
            for signal in r['signals']:
                profile = signal.get('risk_profile', '未指定')
                day_counts[profile] = day_counts.get(profile, 0) + 1
            for profile, count in day_counts.items():
                profile_signals.setdefault(profile, []).append(count)

        summary['profile_signal_counts'] = {
            profile: {
                "total": sum(counts),
                "avg_per_day": round(sum(counts) / len(counts), 2) if counts else 0,
            }
            for profile, counts in profile_signals.items()
        }

        return summary


async def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser(description="ContestTrade 历史回测")
    parser.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--market", default="CN-Stock", help="市场 (CN-Stock/US-Stock)")
    parser.add_argument("--force", action="store_true", help="强制重新计算，清除缓存")
    parser.add_argument("--output", default=None, help="输出目录")
    args = parser.parse_args()

    output_dir = Path(args.output) if args.output else None
    runner = BacktestRunner(
        start_date=args.start,
        end_date=args.end,
        market=args.market,
        output_dir=output_dir,
        force_recompute=args.force,
    )
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
