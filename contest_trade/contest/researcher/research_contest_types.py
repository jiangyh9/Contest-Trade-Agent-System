"""
Research Contest数据结构定义

包含Research Contest系统中用到的所有数据结构和配置类
"""

from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass 
class SignalData:
    """研究信号数据结构"""
    agent_name: str
    trigger_time: str
    thinking: str
    has_opportunity: str
    action: str
    symbol_code: str
    symbol_name: str
    evidence_list: List[Dict]
    limitations: List[str]
    probability: str
    belief: str
    background_information: str
    file_path: Optional[str] = None
    contest_data: Optional[Dict] = None
    
    def has_contest_data(self) -> bool:
        """检查是否有评估数据"""
        return self.contest_data is not None and 'reward' in self.contest_data


@dataclass
class JudgerScore:
    """评分结果"""
    score: float  # 0-100
    reasoning: str
    judger_id: int


@dataclass
class ResearchContestResult:
    """研究竞争最终结果"""
    trigger_time: str
    optimized_weights: Dict[str, float]
    total_signals: int
    valid_signals: int
    selection_method: str = "score_weighted"
    judge_scores: Optional[Dict[str, List[float]]] = None
    
    def get_summary(self) -> str:
        """获取结果摘要"""
        top_signals = sorted(self.optimized_weights.items(), key=lambda x: x[1], reverse=True)[:3]
        top_signals_str = ", ".join([f"{name}({weight:.1%})" for name, weight in top_signals])
        
        return (f"信号总数: {self.total_signals}, 有效信号: {self.valid_signals}, "
                f"Top3权重: {top_signals_str}")
