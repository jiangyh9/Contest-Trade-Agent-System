"""
ContestTrade Streamlit 前端（内部使用）
调用后端 FastAPI，即时触发分析、轮询进度、展示结果。
"""
import os
import time
from datetime import datetime

import markdown
import requests
import streamlit as st
import streamlit.components.v1 as components

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
POLL_INTERVAL = 2  # 秒

st.set_page_config(page_title="多Agent投研辅助平台", layout="wide")
st.title("多Agent投研辅助平台")


def _fmt_time(ts: str | None) -> str:
    """把时间字符串格式化为紧凑显示"""
    if not ts:
        return "-"
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return str(ts)


def _render_evidence(evidence: list) -> str:
    """把证据列表渲染成 Markdown"""
    if not isinstance(evidence, list) or not evidence:
        return "暂无证据"
    lines = []
    for idx, item in enumerate(evidence, 1):
        if isinstance(item, dict):
            desc = item.get("description", "")
            src = item.get("from_source", "")
            t = item.get("time", "")
            lines.append(f"**{idx}.** {desc}  `{src}` {t}".strip())
        else:
            lines.append(f"**{idx}.** {item}")
    return "\n\n".join(lines)


def _scrollable_markdown(md_text: str, height: int = 360) -> None:
    """在固定高度的可滚动区域内渲染 Markdown，避免页面过长"""
    html = markdown.markdown(md_text or "无内容", extensions=["tables", "fenced_code"])
    components.html(
        f"""
        <div style="
            height: {height}px;
            overflow-y: auto;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 12px 16px;
            background: #fafafa;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        ">
            {html}
        </div>
        """,
        height=height,
        scrolling=True,
    )


# 侧边栏：提交任务
with st.sidebar:
    st.header("新建分析任务")
    market = st.selectbox("市场", ["CN-Stock"], index=0)
    st.caption("点击“开始分析”即以当前时间触发，不支持历史回测。")
    start_btn = st.button("开始分析", type="primary")

    st.markdown("---")
    st.markdown(f"后端地址：`{API_BASE}`")

# 初始化 session state
if "job_id" not in st.session_state:
    st.session_state.job_id = None
if "submitted" not in st.session_state:
    st.session_state.submitted = False

# 提交任务
if start_btn:
    payload = {"market": market}
    try:
        resp = requests.post(f"{API_BASE}/api/analyze", json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        st.session_state.job_id = data["job_id"]
        st.session_state.submitted = True
        st.success("任务已提交，正在分析…")
    except Exception as e:
        st.error(f"提交失败：{e}")

# 任务详情页
job_id = st.session_state.job_id
if job_id:
    st.header("任务详情")
    status_placeholder = st.empty()

    # 轮询直到完成/失败
    while True:
        try:
            status_resp = requests.get(f"{API_BASE}/api/jobs/{job_id}", timeout=10)
            status_resp.raise_for_status()
            status = status_resp.json()
        except Exception as e:
            status_placeholder.error(f"查询状态失败：{e}")
            break

        status_text = status.get("status", "unknown")
        stage = status.get("stage", "")
        data_count = status.get("data_factors_count", "-")
        signal_count = status.get("research_signals_count", "-")

        status_placeholder.info(
            f"状态：**{status_text}** | 阶段：**{stage}** | "
            f"Data 因子：{data_count} | Research 信号：{signal_count}"
        )

        if status_text in ("completed", "failed"):
            break

        time.sleep(POLL_INTERVAL)

    # 最终结果展示
    if status_text == "completed":
        st.success("分析完成")

        try:
            result_resp = requests.get(f"{API_BASE}/api/jobs/{job_id}/result", timeout=10)
            if result_resp.status_code == 200:
                result = result_resp.json()

                st.subheader("Data Agent 因子摘要")
                for agent in result.get("data_agents", []):
                    title = agent.get("agent_name", "unknown")
                    with st.expander(title, expanded=True):
                        ctx = agent.get("context") or agent.get("context_preview", "")
                        _scrollable_markdown(ctx, height=360)

                st.subheader(f"Research Agent 信号（共 {len(result.get('signals', []))} 个）")
                for idx, sig in enumerate(result.get("signals", []), 1):
                    with st.container(border=True):
                        st.markdown(
                            f"#### {idx}. {sig.get('symbol_code', '')} {sig.get('symbol_name', '')}"
                            f" <span style='color:gray'>| {sig.get('risk_profile', '')}</span>",
                            unsafe_allow_html=True,
                        )
                        cols = st.columns([1, 1, 1, 1])
                        cols[0].metric("动作", sig.get("action", "-"))
                        cols[1].metric("概率", sig.get("probability", "-"))
                        cols[2].metric("有机会", sig.get("has_opportunity", "-"))

                        thinking = sig.get("thinking", "")
                        if thinking:
                            with st.expander("推理过程"):
                                _scrollable_markdown(thinking, height=240)

                        evidence = sig.get("evidence_list")
                        if evidence:
                            with st.expander("证据链"):
                                _scrollable_markdown(_render_evidence(evidence), height=240)

                        limitations = sig.get("limitations", "")
                        if limitations:
                            with st.expander("风险提示 / 局限"):
                                _scrollable_markdown(limitations, height=160)
            else:
                st.warning("结果文件尚未生成")
        except Exception as e:
            st.error(f"读取结果失败：{e}")

    elif status_text == "failed":
        st.error(f"分析失败：{status.get('error', 'unknown error')}")
        try:
            log_resp = requests.get(f"{API_BASE}/api/jobs/{job_id}/log", timeout=10)
            if log_resp.status_code == 200:
                with st.expander("查看日志"):
                    st.code(log_resp.json().get("log", ""), language="text")
        except Exception:
            pass

# 历史任务列表（只展示成功有结果的）
st.markdown("---")
st.header("最近任务")
try:
    jobs_resp = requests.get(f"{API_BASE}/api/jobs", timeout=10)
    jobs_resp.raise_for_status()
    all_jobs = jobs_resp.json().get("jobs", [])
    completed_jobs = [
        j for j in all_jobs
        if j.get("status") == "completed" and j.get("market") == "CN-Stock"
    ]

    if completed_jobs:
        for j in completed_jobs[:20]:
            jid = j.get("job_id", "")
            signal_count = j.get("research_signals_count", "-")
            cols = st.columns([2, 2, 1])
            cols[0].write(_fmt_time(j.get("created_at")))
            cols[1].write(f"{signal_count} 个信号")
            if cols[2].button("查看", key=f"view_{jid}"):
                st.session_state.job_id = jid
                st.rerun()
    else:
        st.info("暂无已完成任务")
except Exception as e:
    st.error(f"获取历史任务失败：{e}")
