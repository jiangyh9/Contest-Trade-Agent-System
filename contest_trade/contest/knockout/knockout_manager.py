"""
Knockout Tournament Manager - 淘汰赛/复活赛机制核心

核心设计：
1. 每个 agent 维护一个 score card，记录历史得分、胜率、最近表现。
2. 每轮根据得分把 agent 分为 3 个 tier：
   - CHAMPION：头部 agent，每轮都运行并输出。
   - BENCH：中部 agent，按复活周期间歇运行。
   - ELIMINATED：尾部 agent，暂停运行，但每过 N 轮获得一次复活机会。
3. 新 agent（无历史）默认进入 BENCH，避免冷启动直接被淘汰。
4. 支持按分组独立竞赛（例如 Research Agent 按 risk_profile 分组）。
"""

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any


@dataclass
class AgentScoreCard:
    """单个 agent 的竞赛积分卡"""
    agent_id: str
    agent_name: str
    tier: str = "BENCH"          # CHAMPION / BENCH / ELIMINATED
    total_runs: int = 0
    total_score: float = 0.0      # 累计得分（用于计算平均）
    recent_scores: List[float] = field(default_factory=list)
    win_count: int = 0
    eliminated_rounds: int = 0    # 已连续淘汰轮数
    bench_skip_counter: int = 0   # bench 层跳过计数
    last_run_date: Optional[str] = None
    last_score: float = 0.0
    group: str = "default"        # 所属分组，例如 risk_profile
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.recent_scores is None:
            self.recent_scores = []

    @property
    def average_score(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.total_score / self.total_runs

    def recent_average_score(self, window: int = 5) -> float:
        if not self.recent_scores:
            return 0.0
        return sum(self.recent_scores[-window:]) / len(self.recent_scores[-window:])

    @property
    def win_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.win_count / self.total_runs

    def update_score(self, score: float, date_str: str, is_win: bool = False):
        self.total_runs += 1
        self.total_score += score
        self.recent_scores.append(score)
        if len(self.recent_scores) > 20:
            self.recent_scores = self.recent_scores[-20:]
        if is_win:
            self.win_count += 1
        self.last_score = score
        self.last_run_date = date_str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentScoreCard":
        return cls(**data)


class KnockoutTournament:
    """
    淘汰赛管理器

    配置参数：
    - champion_ratio: 进入冠军层的前置比例
    - eliminated_ratio: 被淘汰的后置比例
    - bench_revival_interval: bench 层 agent 每隔多少轮获得一次复活运行机会
    - eliminated_revival_interval: eliminated 层 agent 每隔多少轮获得一次复活运行机会
    - recent_window: 计算近期平均分的窗口
    """

    def __init__(
        self,
        state_dir: Path,
        tournament_name: str,
        champion_ratio: float = 0.30,
        eliminated_ratio: float = 0.30,
        bench_revival_interval: int = 2,
        eliminated_revival_interval: int = 5,
        recent_window: int = 5,
    ):
        self.state_dir = state_dir
        self.tournament_name = tournament_name
        self.state_file = state_dir / f"{tournament_name}_knockout_state.json"
        self.champion_ratio = champion_ratio
        self.eliminated_ratio = eliminated_ratio
        self.bench_revival_interval = bench_revival_interval
        self.eliminated_revival_interval = eliminated_revival_interval
        self.recent_window = recent_window
        self.score_cards: Dict[str, AgentScoreCard] = {}
        self.round_history: List[dict] = []
        self._load_state()

    def _load_state(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.get("score_cards", {}).items():
                self.score_cards[k] = AgentScoreCard.from_dict(v)
            self.round_history = data.get("round_history", [])
        except Exception as e:
            print(f"[Knockout] 加载状态失败: {e}，将重新初始化")
            self.score_cards = {}
            self.round_history = []

    def save_state(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "tournament_name": self.tournament_name,
            "last_updated": datetime.now().isoformat(),
            "score_cards": {k: v.to_dict() for k, v in self.score_cards.items()},
            "round_history": self.round_history[-100:],
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def register_agents(self, agent_ids: List[str], agent_names: Optional[Dict[str, str]] = None, groups: Optional[Dict[str, str]] = None):
        """注册 agent；新 agent 默认进入 BENCH，并设置为下一轮即可运行"""
        for aid in agent_ids:
            if aid not in self.score_cards:
                self.score_cards[aid] = AgentScoreCard(
                    agent_id=aid,
                    agent_name=agent_names.get(aid, aid) if agent_names else aid,
                    tier="BENCH",
                    group=groups.get(aid, "default") if groups else "default",
                    bench_skip_counter=max(0, self.bench_revival_interval - 1),
                )

    def get_agent_tier(self, agent_id: str) -> str:
        return self.score_cards.get(agent_id, AgentScoreCard(agent_id=agent_id)).tier

    def should_run_agent(self, agent_id: str, round_date: str) -> bool:
        """判断某 agent 本轮是否应该运行"""
        card = self.score_cards.get(agent_id)
        if not card:
            return True
        if card.tier == "CHAMPION":
            return True
        if card.tier == "BENCH":
            card.bench_skip_counter += 1
            if card.bench_skip_counter >= self.bench_revival_interval:
                card.bench_skip_counter = 0
                return True
            return False
        if card.tier == "ELIMINATED":
            card.eliminated_rounds += 1
            if card.eliminated_rounds >= self.eliminated_revival_interval:
                card.eliminated_rounds = 0
                return True
            return False
        return True

    def record_scores_and_update_tiers(
        self,
        scores: Dict[str, float],
        round_date: str,
        group_by: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        记录本轮得分并更新 tier。
        如果提供 group_by，则按分组独立排序、独立淘汰。
        """
        # 更新 score card
        for aid, score in scores.items():
            card = self.score_cards.get(aid)
            if not card:
                continue
            card.update_score(score, round_date)

        # 按分组进行 tier 重排
        groups: Dict[str, List[str]] = {}
        for aid, card in self.score_cards.items():
            g = group_by.get(aid, card.group) if group_by else card.group
            groups.setdefault(g, []).append(aid)

        round_summary = {"date": round_date, "groups": {}}

        # 冷启动保护：没有任何历史记录时，不淘汰任何 agent，全部进入 BENCH 观察
        is_cold_start = len(self.round_history) == 0

        for group_name, aids in groups.items():
            ranked = sorted(
                [(aid, self.score_cards[aid].recent_average_score(self.recent_window)) for aid in aids],
                key=lambda x: x[1],
                reverse=True,
            )
            n = len(ranked)
            recent_scores = [score for _, score in ranked]
            score_std = (max(recent_scores) - min(recent_scores)) if recent_scores else 0.0

            group_summary = {
                "agent_count": n,
                "champion": [],
                "bench": [],
                "eliminated": [],
                "ranking": ranked,
            }

            # 冷启动或所有得分没有区分度时，不淘汰；并让这些 agent 下一轮即可运行
            if is_cold_start or score_std < 1e-6:
                for aid, _ in ranked:
                    card = self.score_cards[aid]
                    card.tier = "BENCH"
                    card.bench_skip_counter = max(0, self.bench_revival_interval - 1)
                    card.eliminated_rounds = 0
                    group_summary["bench"].append(aid)
            else:
                champion_count = max(1, math.ceil(n * self.champion_ratio))
                eliminated_count = max(1, math.ceil(n * self.eliminated_ratio))
                bench_count = n - champion_count - eliminated_count
                if bench_count < 0:
                    bench_count = 0

                for i, (aid, _) in enumerate(ranked):
                    card = self.score_cards[aid]
                    if i < champion_count:
                        card.tier = "CHAMPION"
                        card.bench_skip_counter = 0
                        card.eliminated_rounds = 0
                        group_summary["champion"].append(aid)
                    elif i >= champion_count + bench_count:
                        card.tier = "ELIMINATED"
                        group_summary["eliminated"].append(aid)
                    else:
                        card.tier = "BENCH"
                        card.bench_skip_counter = max(0, self.bench_revival_interval - 1)
                        card.eliminated_rounds = 0
                        group_summary["bench"].append(aid)

            round_summary["groups"][group_name] = group_summary

        self.round_history.append(round_summary)
        self.save_state()
        return round_summary

    def get_active_agents_for_round(self, round_date: str) -> List[str]:
        """获取本轮应该运行的 agent 列表"""
        return [aid for aid in self.score_cards if self.should_run_agent(aid, round_date)]

    def get_summary(self) -> dict:
        return {
            "tournament_name": self.tournament_name,
            "total_agents": len(self.score_cards),
            "tiers": {
                "CHAMPION": [c.agent_id for c in self.score_cards.values() if c.tier == "CHAMPION"],
                "BENCH": [c.agent_id for c in self.score_cards.values() if c.tier == "BENCH"],
                "ELIMINATED": [c.agent_id for c in self.score_cards.values() if c.tier == "ELIMINATED"],
            },
            "score_cards": {k: v.to_dict() for k, v in self.score_cards.items()},
        }
