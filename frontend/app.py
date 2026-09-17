"""
ContestTrade 回测前端（Streamlit）

启动方式：
    cd /Users/jiangyueheng/Downloads/ContestTrade
    conda activate contesttrade
    streamlit run frontend/app.py

功能：
- 选择回测日期区间和市场
- 一键运行历史回测
- 查看淘汰赛 leaderboard 演化
- 查看每日信号及风险画像分布
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
BACKTEST_RESULTS_DIR = PROJECT_ROOT / "backtest_results"

st.set_page_config(
    page_title="ContestTrade 回测面板",
    page_icon="📈",
    layout="wide",
)

st.title("📈 ContestTrade 历史回测面板")


# ---------- 侧边栏：回测配置 ----------
st.sidebar.header("回测配置")

market = st.sidebar.selectbox(
    "市场",
    options=["CN-Stock", "US-Stock"],
    index=0,
)

col1, col2 = st.sidebar.columns(2)
with col1:
    start_date = st.date_input(
        "开始日期",
        value=datetime(2025, 8, 1),
        max_value=datetime.today(),
    )
with col2:
    end_date = st.date_input(
        "结束日期",
        value=datetime(2025, 8, 15),
        max_value=datetime.today(),
    )

force_recompute = st.sidebar.checkbox("强制重新计算（清除缓存）", value=False)

run_button = st.sidebar.button("🚀 运行回测", type="primary")

st.sidebar.markdown("---")
st.sidebar.info(
    "回测模式只使用支持历史 trigger_time 的数据源（Tushare/AKShare），\n"
    "并禁用 web search，避免未来信息泄漏。"
)


# ---------- 运行回测 ----------
if run_button:
    if start_date > end_date:
        st.error("开始日期不能晚于结束日期")
    else:
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        st.info(f"正在运行回测: {start_str} ~ {end_str}, 市场: {market}")

        env = os.environ.copy()
        env["CONTEST_TRADE_MARKET"] = market
        env["CONTEST_TRADE_BACKTEST"] = "true"
        # 让子进程也激活 contesttrade 环境
        conda_python = "/Users/jiangyueheng/miniconda3/envs/contesttrade/bin/python"

        cmd = [
            conda_python,
            "-m",
            "cli.main",
            "backtest",
            "--start", start_str,
            "--end", end_str,
            "--market", market,
            "--output", str(BACKTEST_RESULTS_DIR),
        ]
        if force_recompute:
            cmd.append("--force")

        progress_placeholder = st.empty()
        progress_placeholder.text("回测进行中，请稍候...")

        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            capture_output=True,
        )

        progress_placeholder.empty()

        if result.returncode != 0:
            st.error("回测失败")
            with st.expander("查看错误日志"):
                st.code(result.stderr)
        else:
            st.success("回测完成！")
            with st.expander("查看运行日志"):
                st.code(result.stdout)


# ---------- 加载结果 ----------
summary_file = BACKTEST_RESULTS_DIR / "summary.json"
if not summary_file.exists():
    st.warning("尚未生成回测结果，请在左侧配置后点击“运行回测”。")
    st.stop()

with open(summary_file, "r", encoding="utf-8") as f:
    summary = json.load(f)

# 构建 DataFrame
daily_rows = []
for r in summary.get("daily_results", []):
    if "error" in r:
        continue
    daily_rows.append({
        "date": r["trigger_time"][:10],
        "data_factors": r["data_factors_count"],
        "research_signals": r["research_signals_count"],
        "valid_signals": r["valid_signals_count"],
    })
df_daily = pd.DataFrame(daily_rows)

# ---------- Tab 1: 汇总 ----------
tab_summary, tab_leaderboard, tab_signals, tab_tiers = st.tabs([
    "📊 汇总", "🏆 Leaderboard", "📋 每日信号", "📈 层级演化"
])

with tab_summary:
    st.subheader("回测概览")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总交易日", summary.get("total_days", 0))
    col2.metric("成功交易日", summary.get("success_days", 0))
    col3.metric("总有效信号", sum(r.get("valid_signals_count", 0) for r in summary.get("daily_results", []) if "error" not in r))
    col4.metric("日均有效信号", round(df_daily["valid_signals"].mean(), 2) if not df_daily.empty else 0)

    st.subheader("各风险画像信号统计")
    profile_data = []
    for profile, stats in summary.get("profile_signal_counts", {}).items():
        profile_data.append({
            "风险画像": profile,
            "总计": stats["total"],
            "日均": stats["avg_per_day"],
        })
    if profile_data:
        st.dataframe(pd.DataFrame(profile_data), use_container_width=True)
    else:
        st.info("暂无风险画像统计")

    st.subheader("每日信号数量趋势")
    if not df_daily.empty:
        fig = px.line(
            df_daily,
            x="date",
            y=["valid_signals", "research_signals"],
            labels={"value": "数量", "date": "日期", "variable": "类型"},
            markers=True,
        )
        st.plotly_chart(fig, use_container_width=True)


# ---------- Tab 2: Leaderboard ----------
with tab_leaderboard:
    st.subheader("淘汰赛积分榜演化")
    st.info("下方展示每个 Research Agent 在不同日期的 contest_score 变化。")

    # 读取 contest state
    contest_state_file = PROJECT_ROOT / "agents_workspace" / "contest_state" / "research_agent_knockout_state.json"
    if contest_state_file.exists():
        with open(contest_state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        score_rows = []
        for round_info in state.get("round_history", []):
            date = round_info.get("date")
            for group_name, group in round_info.get("groups", {}).items():
                for agent_name, score in group.get("ranking", []):
                    score_rows.append({
                        "date": date,
                        "agent": agent_name,
                        "group": group_name,
                        "score": score,
                    })
        df_scores = pd.DataFrame(score_rows)
        if not df_scores.empty:
            fig = px.line(
                df_scores,
                x="date",
                y="score",
                color="agent",
                facet_col="group",
                facet_col_wrap=2,
                markers=True,
                labels={"score": "得分", "date": "日期"},
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无 leaderboard 数据")
    else:
        st.warning("未找到淘汰赛状态文件，请先运行回测")


# ---------- Tab 3: 每日信号 ----------
with tab_signals:
    st.subheader("查看某日信号")
    available_dates = df_daily["date"].tolist() if not df_daily.empty else []
    selected_date = st.selectbox("选择日期", options=available_dates)

    if selected_date:
        day_file = BACKTEST_RESULTS_DIR / f"day_{selected_date}.json"
        if day_file.exists():
            with open(day_file, "r", encoding="utf-8") as f:
                day_data = json.load(f)

            signals = day_data.get("signals", [])
            st.write(f"当日有效信号: {len(signals)} 个")

            for i, signal in enumerate(signals, 1):
                profile = signal.get("risk_profile", "未指定")
                color = {
                    "风险偏好者": "red",
                    "稳健投资者": "blue",
                    "激进套利者": "orange",
                    "防御套利者": "green",
                }.get(profile, "gray")

                with st.expander(
                    f"{i}. [{profile}] {signal.get('symbol_name', 'N/A')} "
                    f"({signal.get('symbol_code', 'N/A')}) - {signal.get('action', 'N/A')}"
                ):
                    st.markdown(f"**风险画像**: :{color}[{profile}]")
                    st.markdown(f"**置信度**: {signal.get('probability', 'N/A')}")
                    st.markdown(f"**层级**: {signal.get('contest_tier', 'N/A')} "
                                f"(得分: {signal.get('contest_score', 'N/A')})")
                    st.markdown("**证据**:")
                    for ev in signal.get("evidence_list", []):
                        st.markdown(f"- {ev.get('description', '')}")
                    st.markdown("**风险/局限**:")
                    for lim in signal.get("limitations", []):
                        st.markdown(f"- {lim}")
        else:
            st.warning("未找到该日数据")


# ---------- Tab 4: 层级演化 ----------
with tab_tiers:
    st.subheader("Agent 层级变化")

    if contest_state_file.exists():
        tier_rows = []
        for round_info in state.get("round_history", []):
            date = round_info.get("date")
            for group_name, group in round_info.get("groups", {}).items():
                for tier in ["CHAMPION", "BENCH", "ELIMINATED"]:
                    for agent in group.get(tier.lower(), []):
                        tier_rows.append({
                            "date": date,
                            "agent": agent,
                            "group": group_name,
                            "tier": tier,
                        })
        df_tiers = pd.DataFrame(tier_rows)
        if not df_tiers.empty:
            # 为每个 risk_profile 画一个时间线
            groups = df_tiers["group"].unique()
            for g in groups:
                st.markdown(f"**{g}**")
                df_g = df_tiers[df_tiers["group"] == g]
                fig = px.scatter(
                    df_g,
                    x="date",
                    y="agent",
                    color="tier",
                    color_discrete_map={
                        "CHAMPION": "gold",
                        "BENCH": "lightblue",
                        "ELIMINATED": "salmon",
                    },
                    labels={"agent": "Agent", "date": "日期"},
                    height=300,
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无层级数据")
    else:
        st.warning("未找到淘汰赛状态文件")
