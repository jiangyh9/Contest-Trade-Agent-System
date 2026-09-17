"""
config module for trade agent
"""
from pathlib import Path
import yaml
import os

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 如果项目根目录存在 .env，自动加载环境变量（不提交到仓库）
_env_path = PROJECT_ROOT.parent / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path, override=False)


class ProjectConfig:

    def __init__(self) -> None:
        # Get market type from environment variable, default to CN-Stock
        market_type = os.environ.get('CONTEST_TRADE_MARKET', 'CN-Stock')
        
        # Backtest mode: use dedicated backtest config
        is_backtest = os.environ.get('CONTEST_TRADE_BACKTEST', 'false').lower() == 'true'
        
        # Choose config file based on market type and backtest mode
        if is_backtest:
            config_filename = "config_backtest.yaml"
        elif market_type == 'US-Stock':
            config_filename = "config_us.yaml"
        else:
            config_filename = "config.yaml"
        
        yaml_path = PROJECT_ROOT.parent / config_filename
        mode_label = "Backtest" if is_backtest else market_type
        print(f"Loading config from: {yaml_path} (Mode: {mode_label})")
        self.is_backtest = is_backtest

        with open(yaml_path, "r", encoding="utf-8") as fr:
            config = yaml.load(fr, Loader=yaml.FullLoader)
        for k in config:
            setattr(self, k, config[k])

        # 敏感信息优先从环境变量读取，避免把 key 写进仓库
        self._load_secrets_from_env()
        
        # Store the market type for reference
        self.market_type = market_type

    def _load_secrets_from_env(self) -> None:
        """从环境变量读取 API key，覆盖配置文件中的占位符。"""
        # 顶层 key
        for key_name in [
            "tushare_key",
            "bocha_key",
            "serp_key",
            "fmp_key",
            "finnhub_key",
            "alpha_vantage_key",
            "polygon_key",
        ]:
            env_val = os.environ.get(key_name.upper())
            if env_val:
                setattr(self, key_name, env_val)

        # LLM api_key (支持嵌套 dict)
        for section in ["llm", "llm_thinking", "vlm"]:
            section_cfg = getattr(self, section, None)
            if isinstance(section_cfg, dict):
                env_val = os.environ.get(f"{section.upper()}_API_KEY")
                if env_val:
                    section_cfg["api_key"] = env_val
                # 也支持通用的 OPENAI_API_KEY
                if not section_cfg.get("api_key") and os.environ.get("OPENAI_API_KEY"):
                    section_cfg["api_key"] = os.environ.get("OPENAI_API_KEY")

cfg = ProjectConfig()

if __name__ == "__main__":
    print(f"Market Type: {cfg.market_type}")
    print(f"Data Agents Config: {cfg.data_agents_config}")
    print(f"Research Agent Config: {cfg.research_agent_config}")
    print(f"Market Config File: {cfg.market_config_file}")
    print(f"System Language: {cfg.system_language}")
    print(f"LLM Config: {cfg.llm}")
    print(f"Available attributes: {[attr for attr in dir(cfg) if not attr.startswith('_')]}")