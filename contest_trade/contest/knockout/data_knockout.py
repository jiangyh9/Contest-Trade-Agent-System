"""
Data Agent Knockout Contest - 数据层淘汰赛

职责：
1. 维护每个 Data Agent 的 tier 状态（CHAMPION / BENCH / ELIMINATED）。
2. 使用 DataContest 评估器对历史因子进行评分（reward）。
3. 每轮决定哪些 Data Agent 可以运行，并过滤其输出。
4. 把胜出的 factor 列表交给 Research Agent 层。
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from config.config import cfg, PROJECT_ROOT
from .knockout_manager import KnockoutTournament
from contest_trade.contest.data_analyst.data_contest_types import FactorData
from contest_trade.contest.data_analyst.data_manager import ContestDataManager
from contest_trade.contest.data_analyst.evaluator import ContestEvaluator
from models.llm_model import GLOBAL_LLM
from utils.market_manager import GLOBAL_MARKET_MANAGER

logger = logging.getLogger(__name__)


class DataKnockoutContest:
    """Data Agent 淘汰赛控制器"""

    def __init__(
        self,
        enabled: bool = True,
        state_dir: Optional[Path] = None,
        history_window_days: int = 5,
        champion_ratio: float = 0.30,
        eliminated_ratio: float = 0.30,
        bench_revival_interval: int = 2,
        eliminated_revival_interval: int = 5,
    ):
        self.enabled = enabled
        self.history_window_days = history_window_days
        self.state_dir = state_dir or (PROJECT_ROOT / "agents_workspace" / "contest_state")
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.tournament = KnockoutTournament(
            state_dir=self.state_dir,
            tournament_name="data_agent",
            champion_ratio=champion_ratio,
            eliminated_ratio=eliminated_ratio,
            bench_revival_interval=bench_revival_interval,
            eliminated_revival_interval=eliminated_revival_interval,
        )

        self.data_manager = ContestDataManager(history_window_days, PROJECT_ROOT, [])
        self.evaluator = ContestEvaluator(GLOBAL_LLM, GLOBAL_MARKET_MANAGER)

    def register_agents(self, agent_configs: List[dict]):
        """从配置中注册 Data Agent"""
        agent_ids = [c["agent_name"] for c in agent_configs]
        agent_names = {c["agent_name"]: c["agent_name"] for c in agent_configs}
        self.tournament.register_agents(agent_ids, agent_names=agent_names)

    async def evaluate_historical_factors(self, current_date: str) -> Dict[str, float]:
        """评估历史窗口内所有因子的 reward，返回 agent_name -> score"""
        scores: Dict[str, float] = {}

        try:
            agent_factors = self.data_manager.load_historical_factors(current_date)
        except Exception as e:
            logger.warning(f"加载历史因子失败: {e}")
            return scores

        if not agent_factors:
            return scores

        for agent_name, factors in agent_factors.items():
            rewards = []
            for factor in factors:
                if factor is None:
                    continue
                if factor.has_contest_data():
                    rewards.append(factor.contest_data.get("reward", 0.0))
                    continue

                # 没有评估数据则尝试评估
                try:
                    factor_date = factor.trigger_time.split(" ")[0]
                    result = await self.evaluator.evaluate_factor(factor, factor_date)
                    if result:
                        contest_data = result.to_contest_data()
                        self.data_manager.save_contest_data(factor, contest_data)
                        rewards.append(contest_data.get("reward", 0.0))
                except Exception as e:
                    logger.warning(f"评估 {agent_name} 因子失败: {e}")

            if rewards:
                # score = 近期平均 reward，无数据时给 0
                scores[agent_name] = sum(rewards) / len(rewards)
            else:
                scores[agent_name] = 0.0

        return scores

    def select_active_agents(self, round_date: str, all_agent_configs: List[dict]) -> List[str]:
        """根据淘汰赛状态选出本轮应运行的 Data Agent"""
        if not self.enabled:
            return [c["agent_name"] for c in all_agent_configs]

        agent_ids = [c["agent_name"] for c in all_agent_configs]
        self.tournament.register_agents(agent_ids, agent_names={a: a for a in agent_ids})

        active = self.tournament.get_active_agents_for_round(round_date)

        # 第一回（没有任何历史 tier 记录）时全部运行，保证冷启动
        if not self.tournament.round_history and all(
            self.tournament.score_cards[a].tier == "BENCH" for a in self.tournament.score_cards
        ):
            active = agent_ids

        logger.info(f"Data Agent Knockout - 本轮运行 {len(active)}/{len(agent_ids)} 个: {active}")
        return active

    async def update_after_run(
        self,
        round_date: str,
        current_factors: List[FactorData],
    ) -> dict:
        """本轮运行结束后：评分历史并更新 tier"""
        if not self.enabled:
            return {"enabled": False, "message": "淘汰赛已禁用"}

        scores = await self.evaluate_historical_factors(round_date)

        # 对本轮没有历史得分的 agent，使用其当前因子无法立即评分（需要未来收益）。
        # 这里只更新有历史数据的 score；其余 agent 本次不调整 tier，但记录运行。
        for factor in current_factors:
            agent_name = getattr(factor, "agent_name", None)
            if agent_name and agent_name not in scores:
                scores[agent_name] = 0.0

        summary = self.tournament.record_scores_and_update_tiers(scores, round_date)
        self.tournament.save_state()

        return {
            "enabled": True,
            "date": round_date,
            "scores": scores,
            "summary": summary,
            "tiers": self.tournament.get_summary()["tiers"],
        }

    def filter_factors(
        self,
        factors: List[FactorData],
        active_agents: List[str],
        top_k: Optional[int] = None,
    ) -> List[FactorData]:
        """只保留活跃 agent 的 factor；可选只保留 top_k"""
        filtered = [f for f in factors if getattr(f, "agent_name", None) in active_agents]
        if top_k:
            def _score(f):
                card = self.tournament.score_cards.get(getattr(f, "agent_name", ""))
                return card.recent_average_score() if card else 0.0
            ranked = sorted(filtered, key=_score, reverse=True)
            filtered = ranked[:top_k]
        return filtered

    def get_status(self) -> dict:
        return self.tournament.get_summary()
