"""
ContestTrade Streamlit 前端（内部使用）
调用后端 FastAPI，提交任务、轮询进度、展示结果。
"""
import os
import time

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
POLL_INTERVAL = 2  # 秒

st.set_page_config(page_title="ContestTrade", layout="wide")
st.title("ContestTrade A 股分析平台")

# 侧边栏：提交任务
with st.sidebar:
    st.header("新建分析任务")
    market = st.selectbox("市场", ["CN-Stock"], index=0)
    trigger_time = st.text_input(
        "触发时间（可选）",
        placeholder="例如 2026-09-23 09:30:00，留空使用当前交易日",
        help="留空时后端会根据 A 股交易日自动计算当前触发时间",
    )
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
    if trigger_time and trigger_time.strip():
        payload["trigger_time"] = trigger_time.strip()

    try:
        resp = requests.post(f"{API_BASE}/api/analyze", json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        st.session_state.job_id = data["job_id"]
        st.session_state.submitted = True
        st.success(f"任务已提交：`{data['job_id']}`")
    except Exception as e:
        st.error(f"提交失败：{e}")

# 任务详情页
job_id = st.session_state.job_id
if job_id:
    st.header(f"任务 {job_id}")
    status_placeholder = st.empty()
    details_placeholder = st.empty()

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
                    with st.expander(agent.get("agent_name", "unknown")):
                        st.write(agent.get("context_preview", ""))

                st.subheader(f"Research Agent 信号（共 {len(result.get('signals', []))} 个）")
                for idx, sig in enumerate(result.get("signals", []), 1):
                    title = f"{sig.get('symbol_code', '')} {sig.get('symbol_name', '')} - {sig.get('risk_profile', '')}"
                    with st.expander(f"信号 {idx}：{title}"):
                        st.markdown(
                            f"- **标的**：{sig.get('symbol_code', '')} {sig.get('symbol_name', '')}\n"
                            f"- **动作**：{sig.get('action', '')}\n"
                            f"- **概率**：{sig.get('probability', '')}\n"
                            f"- **画像**：{sig.get('risk_profile', '')}\n"
                            f"- **有机会**：{sig.get('has_opportunity', '')}"
                        )
                        with st.expander("证据摘要"):
                            st.text(sig.get("evidence_preview", ""))
            else:
                st.warning("结果文件尚未生成")
        except Exception as e:
            st.error(f"读取结果失败：{e}")

        # 报告（HTML/Markdown）
        st.subheader("报告")
        report_resp = requests.get(f"{API_BASE}/api/jobs/{job_id}/report", timeout=10)
        if report_resp.status_code == 200:
            st.components.v1.html(report_resp.text, height=800, scrolling=True)
        else:
            st.info(report_resp.json().get("error", "暂无报告"))

    elif status_text == "failed":
        st.error(f"分析失败：{status.get('error', 'unknown error')}")
        try:
            log_resp = requests.get(f"{API_BASE}/api/jobs/{job_id}/log", timeout=10)
            if log_resp.status_code == 200:
                with st.expander("查看日志"):
                    st.code(log_resp.json().get("log", ""), language="text")
        except Exception:
            pass

# 历史任务列表
st.markdown("---")
st.header("最近任务")
try:
    jobs_resp = requests.get(f"{API_BASE}/api/jobs", timeout=10)
    jobs_resp.raise_for_status()
    jobs = jobs_resp.json().get("jobs", [])
    if jobs:
        for j in jobs[:10]:
            jid = j.get("job_id", "")
            cols = st.columns([2, 1, 1, 1, 2, 1])
            cols[0].code(jid)
            cols[1].write(j.get("market", ""))
            cols[2].write(j.get("status", ""))
            cols[3].write(j.get("stage", ""))
            cols[4].write(j.get("trigger_time", ""))
            if cols[5].button("查看", key=f"view_{jid}"):
                st.session_state.job_id = jid
                st.rerun()
    else:
        st.info("暂无任务")
except Exception as e:
    st.error(f"获取历史任务失败：{e}")
