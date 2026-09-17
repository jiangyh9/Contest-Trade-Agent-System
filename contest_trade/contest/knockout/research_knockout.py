"""
Research Agent Knockout Contest - 研究层淘汰赛

职责：
1. 按 risk_profile 把 Research Agent 分组，组内独立淘汰。
2. 历史信号用实际收益率打分；当日信号没有未来收益时，用 judge 评分或 probability 作为替代分。
3. 每轮决定哪些 Research Agent 运行，并过滤最终输出信号。
4. 最终只保留各组冠军层（CHAMPION）或高分信号进入报告。
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from config.config import cfg, PROJECT_ROOT
from .knockout_manager import KnockoutTournament
from contest_trade.contest.researcher.research_contest_types import SignalData
from contest_trade.contest.researcher.research_data_manager import ResearchDataManager
from contest_trade.contest.researcher.research_signal_judger import ResearchSignalJudger
from models.llm_model import GLOBAL_LLM
from utils.market_manager import GLOBAL_MARKET_MANAGER

logger = logging.getLogger(__name__)


class ResearchKnockoutContest:
    """Research Agent 淘汰赛控制器"""

    def __init__(
        self,
        enabled: bool = True,
        state_dir: Optional[Path] = None,
        history_window_days: int = 5,
        champion_ratio: float = 0.30,
        eliminated_ratio: float = 0.30,
        bench_revival_interval: int = 2,
        eliminated_revival_interval: int = 5,
        fallback_to_judge: bool = True,
        num_judgers: int = 3,
    ):
        self.enabled = enabled
        self.history_window_days = history_window_days
        self.state_dir = state_dir or (PROJECT_ROOT / "agents_workspace" / "contest_state")
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.tournament = KnockoutTournament(
            state_dir=self.state_dir,
            tournament_name="research_agent",
            champion_ratio=champion_ratio,
            eliminated_ratio=eliminated_ratio,
            bench_revival_interval=bench_revival_interval,
            eliminated_revival_interval=eliminated_revival_interval,
        )

        self.data_manager = ResearchDataManager(history_window_days, PROJECT_ROOT, [])
        self.data_manager.set_market_manager(GLOBAL_MARKET_MANAGER)
        self.signal_judger = ResearchSignalJudger(str(PROJECT_ROOT / "agents_workspace"), history_window_days, self.data_manager)
        self.fallback_to_judge = fallback_to_judge
        self.num_judgers = num_judgers

        # 读取风险画像持仓期配置（默认1天）
        research_cfg = getattr(cfg, "researcher_contest_config", {}) or {}
        self.holding_period_by_risk_profile = research_cfg.get("holding_period_by_risk_profile", {})
        self.default_holding_period = 1

    def register_agents(self, agent_beliefs: List[str]):
        """注册 Research Agent，默认按 belief 中的风险画像分组"""
        agent_ids = [f"agent_{i}" for i in range(len(agent_beliefs))]
        agent_names = {aid: aid for aid in agent_ids}

        def extract_risk_profile(belief: str) -> str:
            # 从 belief 文本中匹配风险画像关键词
            profiles = ["风险偏好者", "稳健投资者", "激进套利者", "防御套利者"]
            for p in profiles:
                if p in belief:
                    return p
            return "default"

        groups = {f"agent_{i}": extract_risk_profile(belief) for i, belief in enumerate(agent_beliefs)}
        self.tournament.register_agents(agent_ids, agent_names=agent_names, groups=groups)

    def _get_holding_period(self, agent_name: str, signal: Optional[SignalData] = None) -> int:
        """根据 agent 所属 risk_profile 获取持仓期"""
        # 优先从 tournament 的 group 推断
        card = self.tournament.score_cards.get(agent_name)
        if card and card.group in self.holding_period_by_risk_profile:
            return self.holding_period_by_risk_profile[card.group]
        # 其次从 signal 的 belief 文本推断
        if signal and signal.belief:
            for profile, period in self.holding_period_by_risk_profile.items():
                if profile in signal.belief:
                    return period
        return self.default_holding_period

    def _extract_probability(self, probability_str: str) -> float:
        """把 probability 字符串解析成 0-1 数值"""
        if not probability_str:
            return 0.0
        numbers = re.findall(r"\d+(?:\.\d+)?", str(probability_str))
        if not numbers:
            return 0.0
        val = float(numbers[-1])
        if val > 1.0:
            val = val / 100.0
        return min(max(val, 0.0), 1.0)

    async def evaluate_historical_signals(self, current_date: str) -> Dict[str, float]:
        """评估历史窗口内 agent 的信号收益率，返回 agent_id -> score"""
        scores: Dict[str, float] = {}
        try:
            agent_signals = self.data_manager.load_historical_signals(current_date)
        except Exception as e:
            logger.warning(f"加载历史信号失败: {e}")
            return scores

        if not agent_signals:
            return scores

        for agent_name, signals in agent_signals.items():
            rewards = []
            for signal in signals:
                if signal is None:
                    continue
                holding_days = self._get_holding_period(agent_name, signal)
                if signal.has_contest_data():
                    # 已有评估结果：如果未记录持仓期，则按当前配置重新计算
                    stored = signal.contest_data.get("reward", 0.0)
                    stored_holding = signal.contest_data.get("holding_days")
                    if stored_holding == holding_days:
                        rewards.append(stored)
                        continue
                try:
                    reward = await self.data_manager.calculate_signal_reward(signal, holding_days=holding_days)
                    # 更新 contest_data，记录本次使用的持仓期
                    if signal.file_path:
                        signal.contest_data = {
                            "reward": reward,
                            "holding_days": holding_days,
                            "evaluation_date": signal.trigger_time.split(" ")[0],
                            "evaluation_method": "market_return",
                        }
                        self.data_manager._save_signal_contest_data(signal)
                    rewards.append(reward)
                except Exception as e:
                    logger.debug(f"计算 {agent_name} 信号收益失败: {e}")

            if rewards:
                scores[agent_name] = sum(rewards) / len(rewards)
            else:
                scores[agent_name] = 0.0

        return scores

    async def score_current_signals(
        self,
        current_signals: Dict[str, SignalData],
        trigger_time: str,
    ) -> Dict[str, float]:
        """对当日信号打分（没有未来收益，使用 judge 评分或 probability 作为替代）"""
        scores: Dict[str, float] = {}

        if not current_signals:
            return scores

        if self.fallback_to_judge:
            try:
                llm_config = {
                    "api_key": cfg.llm.api_key,
                    "api_base": cfg.llm.api_base,
                    "model_name": cfg.llm.model_name,
                }
                judge_scores = await self.signal_judger.judge_signals(
                    signals=current_signals,
                    trigger_time=trigger_time,
                    num_judgers=self.num_judgers,
                    llm_config=llm_config,
                )

                for agent_name, scores_list in judge_scores.items():
                    if scores_list:
                        scores[agent_name] = sum(scores_list) / len(scores_list) / 100.0
            except Exception as e:
                logger.warning(f"judge 评分失败，回退到 probability: {e}")

        # 没有 judge 分或 judge 失败时，用 probability 兜底
        for agent_name, signal in current_signals.items():
            if agent_name not in scores:
                scores[agent_name] = self._extract_probability(signal.probability)

        return scores

    def select_active_agents(self, round_date: str, agent_beliefs: List[str]) -> List[str]:
        """选出本轮应运行的 Research Agent"""
        if not self.enabled:
            return [f"agent_{i}" for i in range(len(agent_beliefs))]

        self.register_agents(agent_beliefs)
        active = self.tournament.get_active_agents_for_round(round_date)

        # 冷启动：全部 BENCH 且没有历史时全部运行
        if not self.tournament.round_history and all(
            self.tournament.score_cards[a].tier == "BENCH" for a in self.tournament.score_cards
        ):
            active = [f"agent_{i}" for i in range(len(agent_beliefs))]

        logger.info(f"Research Agent Knockout - 本轮运行 {len(active)}/{len(agent_beliefs)} 个: {active}")
        return active

    async def update_after_run(
        self,
        round_date: str,
        current_signals: Dict[str, SignalData],
        trigger_time: str,
    ) -> dict:
        """本轮运行结束后：综合历史收益与当日 judge 分更新 tier"""
        if not self.enabled:
            return {"enabled": False, "message": "淘汰赛已禁用"}

        historical_scores = await self.evaluate_historical_signals(round_date)
        current_scores = await self.score_current_signals(current_signals, trigger_time)

        # 合并：有历史收益用历史收益，否则用当日代理分
        merged_scores: Dict[str, float] = {}
        for agent_name in self.tournament.score_cards:
            if agent_name in historical_scores and historical_scores[agent_name] != 0.0:
                merged_scores[agent_name] = historical_scores[agent_name]
            elif agent_name in current_scores:
                merged_scores[agent_name] = current_scores[agent_name]
            else:
                merged_scores[agent_name] = 0.0

        # 按 risk_profile 分组进行独立淘汰
        group_by = {aid: card.group for aid, card in self.tournament.score_cards.items()}
        summary = self.tournament.record_scores_and_update_tiers(merged_scores, round_date, group_by=group_by)
        self.tournament.save_state()

        return {
            "enabled": True,
            "date": round_date,
            "historical_scores": historical_scores,
            "current_scores": current_scores,
            "summary": summary,
            "tiers": self.tournament.get_summary()["tiers"],
        }

    def filter_signals(
        self,
        signals: List[dict],
        allowed_tiers: Optional[List[str]] = None,
        min_score: Optional[float] = None,
    ) -> List[dict]:
        """过滤信号：默认保留 CHAMPION 和 BENCH，丢弃 ELIMINATED"""
        if not self.enabled:
            return signals

        if allowed_tiers is None:
            allowed_tiers = ["CHAMPION", "BENCH"]

        filtered = []
        for signal in signals:
            # 优先使用 agent_name，它通常是 "agent_0"；其次使用 agent_id 字符串
            agent_key = signal.get("agent_name") or str(signal.get("agent_id"))
            if not agent_key:
                continue

            card = self.tournament.score_cards.get(agent_key)
            if not card:
                continue

            if card.tier not in allowed_tiers:
                continue

            if min_score is not None and card.recent_average_score() < min_score:
                continue

            # 给信号加上 contest 元信息，便于报告展示
            signal["contest_tier"] = card.tier
            signal["contest_score"] = round(card.recent_average_score(), 4)
            filtered.append(signal)

        return filtered

    def get_status(self) -> dict:
        return self.tournament.get_summary()
