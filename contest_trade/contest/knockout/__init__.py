"""
Knockout Contest Package

提供 Data Agent 与 Research Agent 的淘汰赛/复活赛机制。
"""

from .data_knockout import DataKnockoutContest
from .research_knockout import ResearchKnockoutContest
from .knockout_manager import KnockoutTournament, AgentScoreCard

__all__ = [
    "DataKnockoutContest",
    "ResearchKnockoutContest",
    "KnockoutTournament",
    "AgentScoreCard",
]
