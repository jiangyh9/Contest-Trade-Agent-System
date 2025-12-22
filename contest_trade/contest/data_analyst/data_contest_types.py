"""
Contest数据结构定义

包含DataContest系统中用到的所有数据结构和配置类
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


# ContestConfig移除，直接在函数参数中传递history_window_days

@dataclass 
class FactorData:
    """因子数据结构"""
    agent_name: str
    trigger_time: str
    context_string: str
    file_path: Optional[str] = None
    contest_data: Optional[Dict] = None
    
    def has_contest_data(self) -> bool:
        """检查是否有评估数据"""
        return self.contest_data is not None and 'reward' in self.contest_data


@dataclass
class Rating:
    """评分结果"""
    rating: int  # [-2, 2]
    reason: str


@dataclass
class Symbol:
    """股票标的"""
    name: str
    market: str
    code: str
    type: str  # "company" or "industry"
    description: str
    rating: Optional[Rating] = None
    day_price_chg: Optional[float] = None


@dataclass
class Mention:
    """提及的实体"""
    content: str
    type: str  # "company" or "industry"


@dataclass
class Observation:
    """观察结果"""
    id: str
    content: str
    timestamp: str
    mentions: List[Mention] = field(default_factory=list)
    symbols: List[Symbol] = field(default_factory=list)


@dataclass
class EvaluationResult:
    """单个因子的评估结果"""
    factor_agent_name: str
    factor_date: str
    reward: float
    observations: List[Observation]
    meta: Dict[str, Any] = field(default_factory=dict)
    
    def to_contest_data(self) -> Dict:
        """转换为contest_data格式用于保存，只保存必要信息"""
        return {
            "reward": self.reward,
            "symbols_count": self.meta.get("symbols_count", 0),
            "observations_count": self.meta.get("observations_count", 0)
        }


@dataclass
class ContestResult:
    """竞争最终结果"""
    selected_factors: List[FactorData]
    trigger_time: str
    selection_method: str = "simple_topk"  # 当前使用的选择方法
    
    def get_summary(self) -> Dict:
        """获取结果摘要"""
        return {
            "trigger_time": self.trigger_time,
            "selected_count": len(self.selected_factors),
            "selected_agents": [f.agent_name for f in self.selected_factors],
            "selection_method": self.selection_method
        }


