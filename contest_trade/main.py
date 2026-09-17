"""
Simplified Trade Company - 合并所有代码，包装成LangGraph工作流
"""
import re
import json
import asyncio
from datetime import datetime
from typing import List, Dict, TypedDict
from langgraph.graph import END, StateGraph
from langchain_core.runnables import RunnableConfig
from langchain_core.callbacks import dispatch_custom_event
from config.config import cfg, PROJECT_ROOT
from agents.data_analysis_agent import DataAnalysisAgent, DataAnalysisAgentConfig, DataAnalysisAgentInput
from agents.research_agent import ResearchAgent, ResearchAgentConfig, ResearchAgentInput
from utils.market_manager import GLOBAL_MARKET_MANAGER
from contest.data_analyst.data_contest_types import FactorData
from contest.knockout.data_knockout import DataKnockoutContest
from contest.knockout.research_knockout import ResearchKnockoutContest

# 统一的状态定义
class CompanyState(TypedDict):
    trigger_time: str
    data_factors: List[Dict]
    research_signals: List[Dict]
    all_events: List[Dict]
    step_results: Dict

class SimpleTradeCompany:
    def __init__(self):
        # 设置工作目录
        self.workspace_dir = str(PROJECT_ROOT / "agents_workspace")
        
        # 初始化Data Agents
        self.data_agents = {}
        for agent_config_idx, agent_config in enumerate(cfg.data_agents_config):
            custom_config = DataAnalysisAgentConfig(
                source_list=agent_config["data_source_list"],
                agent_name=agent_config["agent_name"],
                final_target_tokens=agent_config.get("final_target_tokens", 4000),
                bias_goal=agent_config.get("bias_goal", ""),
            )
            self.data_agents[agent_config_idx] = DataAnalysisAgent(custom_config)
        
        # 初始化Research Agents
        self.research_agents = {}

        # 从belief_list.json读取belief配置
        belief_list_path = PROJECT_ROOT / cfg.research_agent_config["belief_list_path"]
        with open(belief_list_path, 'r', encoding='utf-8') as f:
            belief_list = json.load(f)

        # 读取不同风险画像的持仓期配置
        research_contest_cfg = getattr(cfg, "researcher_contest_config", {}) or {}
        holding_period_map = research_contest_cfg.get("holding_period_by_risk_profile", {})

        for agent_config_idx, belief in enumerate(belief_list):
            risk_profile = self._extract_risk_profile_from_belief(belief)
            holding_period = holding_period_map.get(risk_profile, 1)
            custom_config = ResearchAgentConfig(
                agent_name=f"agent_{agent_config_idx}",
                belief=belief,
                holding_period=holding_period,
            )
            self.research_agents[agent_config_idx] = ResearchAgent(custom_config)

        # 淘汰赛配置
        data_contest_cfg = getattr(cfg, "data_contest_config", {}) or {}
        research_contest_cfg = getattr(cfg, "researcher_contest_config", {}) or {}

        self.data_knockout = DataKnockoutContest(
            enabled=data_contest_cfg.get("enabled", True),
            history_window_days=data_contest_cfg.get("history_window_days", 5),
            champion_ratio=data_contest_cfg.get("champion_ratio", 0.30),
            eliminated_ratio=data_contest_cfg.get("eliminated_ratio", 0.30),
            bench_revival_interval=data_contest_cfg.get("bench_revival_interval", 2),
            eliminated_revival_interval=data_contest_cfg.get("eliminated_revival_interval", 5),
        )
        self.data_knockout.register_agents(cfg.data_agents_config)

        self.research_knockout = ResearchKnockoutContest(
            enabled=research_contest_cfg.get("enabled", True),
            history_window_days=research_contest_cfg.get("window_m", 5),
            champion_ratio=research_contest_cfg.get("champion_ratio", 0.30),
            eliminated_ratio=research_contest_cfg.get("eliminated_ratio", 0.30),
            bench_revival_interval=research_contest_cfg.get("bench_revival_interval", 2),
            eliminated_revival_interval=research_contest_cfg.get("eliminated_revival_interval", 5),
            fallback_to_judge=research_contest_cfg.get("fallback_to_judge", True),
            num_judgers=research_contest_cfg.get("num_judgers", 3),
        )
        self.research_knockout.register_agents(belief_list)

    # LangGraph节点函数
    async def run_data_agents_step(self, state: CompanyState, config: RunnableConfig) -> CompanyState:
        """运行Data Agents步骤（集成淘汰赛）"""
        trigger_time = state["trigger_time"]
        current_date = trigger_time.split(' ')[0]

        # 根据淘汰赛状态选择本轮应运行的 Data Agent
        active_agent_names = self.data_knockout.select_active_agents(
            current_date, cfg.data_agents_config
        )
        active_agent_ids = [
            idx for idx, agent in self.data_agents.items()
            if agent.config.agent_name in active_agent_names
        ]

        print(f"🚀 Data Knockout - 本轮运行 {len(active_agent_ids)}/{len(self.data_agents)} 个Data Agents...")
        dispatch_custom_event(
            name="data_knockout_active_agents",
            data={"active": active_agent_names, "total": len(self.data_agents)},
            config=config,
        )
        
        # 创建并发任务
        agent_tasks = []
        for agent_id in active_agent_ids:
            agent = self.data_agents[agent_id]
            task = self._run_single_data_agent(agent_id, agent, trigger_time, config)
            agent_tasks.append(task)
        
        # 并发执行
        results = await asyncio.gather(*agent_tasks)
        
        # 收集结果
        all_factors = []
        all_events = []
        for result in results:
            if result:
                all_factors.append(result["factor"])
                all_events.extend(result["events"])

        # 更新淘汰赛状态（基于历史收益）
        contest_factors = [
            FactorData(
                agent_name=f.agent_name,
                trigger_time=f.trigger_time,
                context_string=f.context_string,
            )
            for f in all_factors if hasattr(f, "agent_name")
        ]
        try:
            data_contest_summary = await self.data_knockout.update_after_run(
                current_date, contest_factors
            )
        except Exception as e:
            print(f"⚠️ Data Knockout 更新状态失败: {e}")
            data_contest_summary = {"enabled": self.data_knockout.enabled, "error": str(e)}

        # 过滤传给 Research Agent 的 factor：默认保留活跃 agent，可选只保留 CHAMPION
        filtered_factors = self.data_knockout.filter_factors(
            contest_factors, active_agent_names, top_k=None
        )
        # 转回原始 factor 对象输出
        active_factor_names = {f.agent_name for f in filtered_factors}
        final_factors = [f for f in all_factors if getattr(f, "agent_name", None) in active_factor_names]

        print(f"✅ Data Agents完成，有效结果: {len(all_factors)}，传给研究层: {len(final_factors)}")
        dispatch_custom_event(
            name="data_knockout_tiers_updated",
            data={
                "enabled": self.data_knockout.enabled,
                "tiers": self.data_knockout.get_status().get("tiers", {}),
                "summary": data_contest_summary,
            },
            config=config,
        )
        
        # 更新状态
        all_events_state = state["all_events"].copy()
        all_events_state.extend(all_events)
        
        step_results = state["step_results"].copy()
        step_results["data_team"] = {
            "factors_count": len(all_factors),
            "events_count": len(all_events),
            "active_count": len(active_agent_ids),
            "data_contest": data_contest_summary,
            "data_tiers": self.data_knockout.get_status().get("tiers", {}),
        }
        
        return {
            "data_factors": final_factors,
            "all_events": all_events_state,
            "step_results": step_results
        }

    async def run_research_agents_step(self, state: CompanyState, config: RunnableConfig) -> CompanyState:
        """运行Research Agents步骤（集成淘汰赛）"""
        trigger_time = state["trigger_time"]
        current_date = trigger_time.split(' ')[0]
        data_factors = state["data_factors"]

        # 读取 belief 以注册/分组 Research Agent
        belief_list_path = PROJECT_ROOT / cfg.research_agent_config["belief_list_path"]
        with open(belief_list_path, 'r', encoding='utf-8') as f:
            belief_list = json.load(f)

        # 根据淘汰赛状态选择本轮应运行的 Research Agent
        active_agent_names = self.research_knockout.select_active_agents(current_date, belief_list)
        active_agent_ids = [
            idx for idx, agent in self.research_agents.items()
            if agent.config.agent_name in active_agent_names
        ]
        
        print(f"🚀 Research Knockout - 本轮运行 {len(active_agent_ids)}/{len(self.research_agents)} 个Research Agents...")
        dispatch_custom_event(
            name="research_knockout_active_agents",
            data={"active": active_agent_names, "total": len(self.research_agents)},
            config=config,
        )
        
        # 创建并发任务
        agent_tasks = []
        for agent_id in active_agent_ids:
            agent = self.research_agents[agent_id]
            task = self._run_single_research_agent(agent_id, agent, trigger_time, data_factors, config)
            agent_tasks.append(task)
        
        # 并发执行
        results = await asyncio.gather(*agent_tasks)
        
        # 收集结果
        all_signals = []
        all_events = []
        for result in results:
            if result and result["signals"]:
                all_signals.extend(result["signals"])
                all_events.extend(result["events"])

        # 更新淘汰赛状态并过滤信号
        try:
            current_signal_data = self._signals_to_signal_data(all_signals)
            research_contest_summary = await self.research_knockout.update_after_run(
                current_date, current_signal_data, trigger_time
            )
            # 默认保留 CHAMPION / BENCH 层信号，丢弃 ELIMINATED
            final_signals = self.research_knockout.filter_signals(
                all_signals, allowed_tiers=["CHAMPION", "BENCH"], min_score=None
            )
        except Exception as e:
            print(f"⚠️ Research Knockout 更新状态失败: {e}")
            research_contest_summary = {"enabled": self.research_knockout.enabled, "error": str(e)}
            final_signals = all_signals
        
        print(f"✅ Research Agents完成，本轮信号: {len(all_signals)}，进入最终报告: {len(final_signals)}")
        dispatch_custom_event(
            name="research_knockout_tiers_updated",
            data={
                "enabled": self.research_knockout.enabled,
                "tiers": self.research_knockout.get_status().get("tiers", {}),
                "summary": research_contest_summary,
                "final_signals_count": len(final_signals),
            },
            config=config,
        )
        
        # 更新状态
        all_events_state = state["all_events"].copy()
        all_events_state.extend(all_events)
        
        step_results = state["step_results"].copy()
        step_results["research_team"] = {
            "signals_count": len(all_signals),
            "events_count": len(all_events),
            "active_count": len(active_agent_ids),
            "final_signals_count": len(final_signals),
            "research_contest": research_contest_summary,
            "research_tiers": self.research_knockout.get_status().get("tiers", {}),
        }
        
        return {
            "research_signals": final_signals,
            "all_events": all_events_state,
            "step_results": step_results
        }

    async def finalize_step(self, state: CompanyState, config: RunnableConfig) -> CompanyState:
        """最终结果步骤"""
        trigger_time = state["trigger_time"]
        data_factors = state["data_factors"]
        research_signals = state["research_signals"]
        all_events = state["all_events"]
        step_results = state["step_results"]
        
        print("🚀 开始最终结果步骤...")
        # 优先使用research产生的信号作为最终最佳信号
        best_signals = research_signals if research_signals else []

        # 生成最终结果（保留但不额外输出）
        final_result = {
            "trigger_time": trigger_time,
            "data_factors_count": len(data_factors),
            "research_signals_count": len(research_signals),
            "total_events_count": len(all_events),
            "best_signals": best_signals,
            "step_results": step_results
        }

        print("✅ 最终结果步骤完成")

        step_results = state["step_results"]
        step_results["contest"] = {
            "best_signals": best_signals
        }
        return {
            "step_results": step_results
        }

    @staticmethod
    def _extract_risk_profile_from_belief(belief: str) -> str:
        """从 belief 文本中提取风险画像关键词"""
        profiles = ["风险偏好者", "稳健投资者", "激进套利者", "防御套利者"]
        for profile in profiles:
            if profile in belief:
                return profile
        return "default"

    # 辅助函数
    async def _run_single_data_agent(self, agent_id: int, agent, trigger_time: str, config: RunnableConfig):
        """运行单个data agent"""
        print(f"🔍 开始运行Data Agent {agent_id} ({agent.config.agent_name})...")
        
        agent_input = DataAnalysisAgentInput(trigger_time=trigger_time)
        agent_events = []
        agent_output = None
        
        # 运行agent并收集事件
        async for event in agent.run_with_monitoring_events(agent_input, config):
            # 转发事件
            if event["event"] == "on_custom":
                dispatch_custom_event(
                    name=f"data_agent_{agent_id}_{event['name']}", 
                    data={**event.get('data', {}), "agent_id": agent_id, "agent_name": agent.config.agent_name},
                    config=config
                )
            else:
                dispatch_custom_event(
                    name=f"data_agent_{agent_id}_{event['event']}", 
                    data={"agent_id": agent_id, "agent_name": agent.config.agent_name, "sub_node": event.get('name', 'unknown')},
                    config=config
                )
            
            agent_events.append({**event, "agent_id": agent_id, "agent_name": agent.config.agent_name})
            
            # 获取最终结果
            if event["event"] == "on_chain_end" and event.get("name") == "submit_result":
                agent_output = event.get("data", {}).get("output", {})
        
        # 处理结果
        factor = None
        if agent_output:
            factor = agent_output['result']
        return {"factor": factor, "events": agent_events} if factor else None

    async def _run_single_research_agent(self, agent_id: int, agent, trigger_time: str, factors: List, config: RunnableConfig):
        """运行单个research agent"""
        print(f"🔍 开始运行Research Agent {agent_id} ({agent.config.agent_name})...")
        
        # 构建背景信息
        background_information = agent.build_background_information(trigger_time, agent.config.belief, factors)
        agent_input = ResearchAgentInput(
            trigger_time=trigger_time,
            background_information=background_information
        )
        
        agent_events = []
        agent_output = None

        # 运行agent并收集事件
        async for event in agent.run_with_monitoring_events(agent_input, config):
            # 转发事件
            if event["event"] == "on_custom":
                dispatch_custom_event(
                    name=f"research_agent_{agent_id}_{event['name']}", 
                    data={**event.get('data', {}), "agent_id": agent_id, "agent_name": agent.config.agent_name},
                    config=config
                )
            else:
                dispatch_custom_event(
                    name=f"research_agent_{agent_id}_{event['event']}", 
                    data={"agent_id": agent_id, "agent_name": agent.config.agent_name, "sub_node": event.get('name', 'unknown')},
                    config=config
                )
            
            agent_events.append({**event, "agent_id": agent_id, "agent_name": agent.config.agent_name})
            
            # 获取最终结果
            if event["event"] == "on_chain_end" and event.get("name") == "submit_result":
                agent_output = event.get("data", {}).get("output", {})
        
        # 处理结果 - 解析多个信号
        signals = []
        if agent_output:
            if "result" in agent_output and agent_output["result"]:
                result_obj = agent_output["result"]
                signals = self._parse_multiple_results(result_obj.final_result_thinking, result_obj.final_result)
            else:
                signals = self._parse_multiple_results(agent_output.get("final_result_thinking", ""), agent_output.get("final_result", ""))
            
            # 为每个信号添加agent信息，最多取5个信号
            valid_signals = []
            agent_belief = getattr(agent.config, "belief", "")
            agent_background = ""
            if isinstance(agent_output, dict):
                agent_background = agent_output.get("background_information", "")
            elif hasattr(agent_output, "background_information"):
                agent_background = agent_output.background_information
            for i, signal in enumerate(signals[:5]):
                if signal:
                    signal["agent_id"] = agent_id
                    signal["agent_name"] = agent.config.agent_name
                    signal["signal_index"] = i + 1
                    signal["trigger_time"] = trigger_time
                    signal["belief"] = agent_belief
                    signal["background_information"] = agent_background
                    valid_signals.append(signal)
            signals = valid_signals
        
        return {"signals": signals, "events": agent_events} if signals else None

    def _parse_multiple_results(self, thinking_result: str, output_result: str):
        """解析多个信号结果"""
        thinking = thinking_result.split("<Output>")[0].strip('\n').strip()
        output = output_result.split("<Output>")[-1].strip('\n').strip()
        
        signals = []
        try:
            # 查找所有signal块
            signal_blocks = re.findall(r'<signal>(.*?)</signal>', output, flags=re.DOTALL)
            
            for signal_block in signal_blocks:
                try:
                    signal = self._parse_single_signal_block(signal_block, thinking)
                    if signal:
                        signals.append(signal)
                except Exception as e:
                    print(f"Error parsing individual signal: {e}")
                    continue
        
        except Exception as e:
            print(f"Error parsing multiple results: {e}")
        
        return signals

    def _parse_single_signal_block(self, signal_block: str, thinking: str):
        """解析单个信号块"""
        try:
            has_opportunity = re.search(r"<has_opportunity>(.*?)</has_opportunity>", signal_block, flags=re.DOTALL).group(1).strip()
            action = re.search(r"<action>(.*?)</action>", signal_block, flags=re.DOTALL).group(1).strip()
            symbol_code = re.search(r"<symbol_code>(.*?)</symbol_code>", signal_block, flags=re.DOTALL).group(1).strip()
            symbol_name = re.search(r"<symbol_name>(.*?)</symbol_name>", signal_block, flags=re.DOTALL).group(1).strip()

            risk_profile_match = re.search(r"<risk_profile>(.*?)</risk_profile>", signal_block, flags=re.DOTALL)
            risk_profile = risk_profile_match.group(1).strip() if risk_profile_match else "未指定"
            
            # 解析evidence_list
            evidence_list_str = re.search(r"<evidence_list>(.*?)</evidence_list>", signal_block, flags=re.DOTALL).group(1)
            evidence_list = []
            for item in evidence_list_str.split("<evidence>"):
                if '</evidence>' not in item:
                    continue
                evidence_description = item.split("</evidence>")[0].strip()
                try:
                    evidence_time = re.search(r"<time>(.*?)</time>", item, flags=re.DOTALL).group(1).strip()
                except:
                    evidence_time = "N/A"
                try:
                    evidence_from_source = re.search(r"<from_source>(.*?)</from_source>", item, flags=re.DOTALL).group(1).strip()
                except:
                    evidence_from_source = "N/A"
                    
                evidence_list.append({
                    "description": evidence_description,
                    "time": evidence_time,
                    "from_source": evidence_from_source,
                })

            # 解析limitations
            limitations_str = re.search(r"<limitations>(.*?)</limitations>", signal_block, flags=re.DOTALL).group(1)
            limitations = re.findall(r"<limitation>(.*?)</limitation>", limitations_str, flags=re.DOTALL)
            limitations = [l.strip() for l in limitations]
            
            # 解析probability
            probability = re.search(r"<probability>(.*?)</probability>", signal_block, flags=re.DOTALL).group(1).strip()
            
            # 修正symbol信息
            symbol_name, symbol_code = GLOBAL_MARKET_MANAGER.fix_symbol_code("CN-Stock", symbol_name, symbol_code)
            
            return {
                "thinking": thinking,
                "has_opportunity": has_opportunity,
                "action": action,
                "symbol_code": symbol_code,
                "symbol_name": symbol_name,
                "risk_profile": risk_profile,
                "evidence_list": evidence_list,
                "limitations": limitations,
                "probability": probability,
            }
        except Exception as e:
            print(f"Error parsing single signal block: {e}")
            return None

    def _signals_to_signal_data(self, signals: List[Dict]) -> Dict[str, object]:
        """把解析后的信号字典转换为 Research Contest 用的 SignalData 对象"""
        from contest.researcher.research_contest_types import SignalData
        result = {}
        for signal in signals:
            agent_name = signal.get("agent_name")
            if not agent_name:
                continue
            result[agent_name] = SignalData(
                agent_name=agent_name,
                trigger_time=signal.get("trigger_time", ""),
                thinking=signal.get("thinking", ""),
                has_opportunity=signal.get("has_opportunity", "no"),
                action=signal.get("action", "buy"),
                symbol_code=signal.get("symbol_code", ""),
                symbol_name=signal.get("symbol_name", ""),
                evidence_list=signal.get("evidence_list", []),
                limitations=signal.get("limitations", []),
                probability=signal.get("probability", "0"),
                belief=signal.get("belief", ""),
                background_information=signal.get("background_information", ""),
            )
        return result

    # LangGraph工作流创建
    def create_company_workflow(self):
        """创建公司工作流"""
        workflow = StateGraph(CompanyState)

        # 添加节点
        workflow.add_node("run_data_agents", self.run_data_agents_step)
        workflow.add_node("run_research_agents", self.run_research_agents_step)
        workflow.add_node("finalize", self.finalize_step)

        # 设置入口点
        workflow.set_entry_point("run_data_agents")

        # 定义边（data -> research -> finalize）
        workflow.add_edge("run_data_agents", "run_research_agents")
        workflow.add_edge("run_research_agents", "finalize")
        workflow.add_edge("finalize", END)

        return workflow.compile()

    async def run_company(self, trigger_time: str, config: RunnableConfig = None):
        """运行整个公司流程"""
        print("🚀 开始运行Simplified TradeCompany...")
        
        if config is None:
            config = RunnableConfig(recursion_limit=50)
        
        # 创建初始状态
        initial_state = CompanyState(
            trigger_time=trigger_time,
            data_factors=[],
            research_signals=[],
            all_events=[],
            step_results={}
        )
        
        # 运行工作流
        workflow = self.create_company_workflow()
        final_state = await workflow.ainvoke(initial_state, config=config)
        
        print("✅ Simplified TradeCompany完成")
        print(f"📊 最终结果:")
        
        # 从step_results中获取更准确的统计信息
        step_results = final_state.get('step_results', {})
        data_team_results = step_results.get("data_team", {})
        research_team_results = step_results.get("research_team", {})
        
        data_factors_count = data_team_results.get("factors_count", len(final_state.get('data_factors', [])))
        research_signals_count = research_team_results.get("signals_count", len(final_state.get('research_signals', [])))
        total_events_count = len(final_state.get('all_events', []))
        
        print(f"   数据因子: {data_factors_count}")
        print(f"   研究信号: {research_signals_count}")
        print(f"   总事件: {total_events_count}")
        
        return final_state

    async def run_company_with_events(self, trigger_time: str, config: RunnableConfig = None):
        """使用事件流运行公司"""
        if config is None:
            config = RunnableConfig(recursion_limit=50)
        
        # 创建初始状态
        initial_state = CompanyState(
            trigger_time=trigger_time,
            data_factors=[],
            research_signals=[],
            all_events=[],
            step_results={}
        )
        
        # 运行工作流并返回事件流
        workflow = self.create_company_workflow()
        async for event in workflow.astream_events(initial_state, version="v2", config=config):
            yield event

if __name__ == "__main__":
    async def main():
        company = SimpleTradeCompany()
        
        # 使用事件流运行
        print("🚀 开始测试Simplified TradeCompany事件流...")
        print("=" * 60)

        trigger_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        company_events = []
        final_state = None
        
        async for event in company.run_company_with_events(trigger_time):
            company_events.append(event)
            
            # 监听并打印事件
            event_type = event.get("event", "unknown")
            event_name = event.get("name", "unknown")
            
            if event_type == "on_chain_start":
                if event_name != "__start__":
                    print(f"🔄 Company开始: {event_name}")
            elif event_type == "on_chain_end":
                if event_name != "__start__":
                    print(f"✅ Company完成: {event_name}")
                    if event_name == "finalize":
                        final_state = event.get("data", {}).get("output", {})
            elif event_type == "on_custom":
                custom_name = event.get("name", "")
                custom_data = event.get("data", {})
                
                if custom_name.startswith("data_agent_"):
                    agent_id = custom_data.get("agent_id", "unknown")
                    print(f"📊 Data Agent {agent_id}: {custom_name}")
                elif custom_name.startswith("research_agent_"):
                    agent_id = custom_data.get("agent_id", "unknown")
                    print(f"🔍 Research Agent {agent_id}: {custom_name}")
                else:
                    print(f"🎯 自定义事件: {custom_name}")
        
        print("=" * 60)
        print(f"✅ 公司工作流完成:")
        if final_state:
            step_results = final_state.get('step_results', {})
            data_team_results = step_results.get("data_team", {})
            research_team_results = step_results.get("research_team", {})
            
            data_factors_count = data_team_results.get("factors_count", len(final_state.get('data_factors', [])))
            research_signals_count = research_team_results.get("signals_count", len(final_state.get('research_signals', [])))
            
            print(f"   数据因子: {data_factors_count}")
            print(f"   研究信号: {research_signals_count}")
        else:
            print(f"   无最终状态数据")
        print(f"   公司事件总数: {len(company_events)}")
        
    asyncio.run(main())