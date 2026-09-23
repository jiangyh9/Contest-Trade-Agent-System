"""
ContestTrade 分析任务子进程
由 api/main.py 通过 subprocess 调用。
关键：在导入 config / contest_trade 代码之前，先设置 CONTEST_TRADE_MARKET。
"""
import json
import os
import pickle
import re
import sys
import traceback
from pathlib import Path

# 项目根目录（Docker 里 /app，本地是仓库根目录）
SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _extract_signal_basics(final_result_text: str) -> list[dict]:
    """从 Research Agent 输出文本中简单提取信号列表"""
    if not isinstance(final_result_text, str) or not final_result_text.strip():
        return []

    signals = []
    # 按 <signal> 块切分
    blocks = re.split(r"<signal>", final_result_text)
    for block in blocks[1:]:
        s = {}
        for tag in ["symbol_code", "symbol_name", "action", "risk_profile", "probability"]:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S | re.I)
            if m:
                s[tag] = m.group(1).strip()
        if s:
            signals.append(s)
    return signals


def _save_summary(final_state: dict, job_dir: Path) -> None:
    """保存结果摘要和完整 pickle（保留完整上下文，前端不再截断）"""
    data_factors = final_state.get("data_factors", []) or []
    research_signals = final_state.get("research_signals", []) or []

    def _full_context(factor) -> str:
        ctx = getattr(factor, "context_string", "") or factor.get("context_string", "")
        return ctx or ""

    summary = {
        "data_factors_count": len(data_factors),
        "research_signals_count": len(research_signals),
        "data_agents": [
            {
                "agent_name": getattr(f, "agent_name", None) or f.get("agent_name", "unknown"),
                "context": _full_context(f),
            }
            for f in data_factors
        ],
        "signals": [],
    }

    for sig in research_signals:
        # 兼容 dataclass / dict / 对象
        if hasattr(sig, "to_dict"):
            sig_dict = sig.to_dict()
        elif isinstance(sig, dict):
            sig_dict = sig
        else:
            sig_dict = {}

        evidence = sig_dict.get("evidence_list", [])
        if not isinstance(evidence, list):
            evidence = []

        summary["signals"].append({
            "symbol_code": sig_dict.get("symbol_code", ""),
            "symbol_name": sig_dict.get("symbol_name", ""),
            "action": sig_dict.get("action", ""),
            "risk_profile": sig_dict.get("risk_profile", ""),
            "probability": sig_dict.get("probability", ""),
            "has_opportunity": sig_dict.get("has_opportunity", ""),
            "belief": sig_dict.get("belief", ""),
            "thinking": sig_dict.get("thinking", ""),
            "limitations": sig_dict.get("limitations", ""),
            "evidence_list": evidence,
        })

    (job_dir / "result_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (job_dir / "result.pkl").write_bytes(pickle.dumps(final_state))


def update_status(status_file: Path, **kwargs) -> None:
    status = json.loads(status_file.read_text(encoding="utf-8"))
    status.update(kwargs)
    status_file.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    job_dir = Path(sys.argv[1]).resolve()
    request = json.loads((job_dir / "request.json").read_text(encoding="utf-8"))
    market = request["market"]

    # 关键：先设环境变量，再导入项目代码
    os.environ["CONTEST_TRADE_MARKET"] = market

    from cli.utils import get_trigger_time_for_market
    from contest_trade.main import SimpleTradeCompany

    trigger_time = request.get("trigger_time") or get_trigger_time_for_market(market, use_now=True)

    status_file = job_dir / "status.json"
    update_status(status_file, status="running", stage="data_agents")

    try:
        company = SimpleTradeCompany()
        final_state = asyncio.run(company.run_company(trigger_time))

        update_status(
            status_file,
            stage="done",
            data_factors_count=len(final_state.get("data_factors", [])),
            research_signals_count=len(final_state.get("research_signals", [])),
        )
        _save_summary(final_state, job_dir)
        update_status(status_file, status="completed")
    except Exception as e:
        traceback_str = traceback.format_exc()
        (job_dir / "error.log").write_text(traceback_str, encoding="utf-8")
        update_status(status_file, status="failed", error=str(e), traceback=traceback_str[:2000])
        raise


if __name__ == "__main__":
    import asyncio
    main()
