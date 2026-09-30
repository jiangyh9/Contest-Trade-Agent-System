"""
基于 Wind 数据库的 A股 ETF 风格轮动数据源

从 Wind Oracle 拉取指定 ETF 池的历史行情，计算多窗口动量、相对强弱、
成交量趋势等指标，并生成一段文本摘要供 LLM 作为 Data Agent 输入。

依赖：
    - JayDeBeApi / JPype1
    - Wind JDBC 驱动（ojdbc8.jar）与 JRE 11
    - 配置项 wind_jdbc / etf_universe_path
"""

import os
import json
import asyncio
import pandas as pd
import numpy as np
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from data_source.data_source_base import DataSourceBase
from utils.wind_jdbc_client import get_wind_client
from utils.etf_universe_provider import load_etf_universe
from utils.date_utils import get_previous_trading_date
from models.llm_model import GLOBAL_LLM
from loguru import logger


class WindETFDataSource(DataSourceBase):
    """Wind ETF 风格轮动数据源"""

    def __init__(self, etf_universe_path: Optional[str] = None, lookback_days: int = 60):
        super().__init__("wind_etf")
        self.lookback_days = lookback_days
        if etf_universe_path:
            self.etf_universe_path = Path(etf_universe_path)
        else:
            from config.config import PROJECT_ROOT
            self.etf_universe_path = Path(PROJECT_ROOT) / "config" / "etf_universe.json"
        self._etf_meta: Optional[List[Dict[str, Any]]] = None
        self._benchmark_code: Optional[str] = None

    def _load_universe(self, as_of_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """加载 ETF 池配置"""
        if self._etf_meta is not None:
            return self._etf_meta
        from config.config import cfg
        data = load_etf_universe(cfg, as_of_date=as_of_date, static_path=self.etf_universe_path)
        self._benchmark_code = data.get("benchmark")
        self._etf_meta = data.get("etfs", [])
        return self._etf_meta

    @property
    def all_codes(self) -> List[str]:
        meta = self._load_universe()
        codes = [m["code"] for m in meta]
        if self._benchmark_code and self._benchmark_code not in codes:
            codes.append(self._benchmark_code)
        return list(dict.fromkeys(codes))

    def _query_price(
        self,
        client,
        codes: List[str],
        start_dt: str,
        end_dt: str,
    ) -> pd.DataFrame:
        """从 CHINACLOSEDFUNDEODPRICE 查询 ETF 日线"""
        # 大池使用数据库端 ETF 主表联查，避免多个超长 IN 列表拖慢 Oracle 解析。
        if len(codes) > 300:
            sql = f"""
        SELECT
            P.S_INFO_WINDCODE,
            P.TRADE_DT,
            P.S_DQ_OPEN,
            P.S_DQ_HIGH,
            P.S_DQ_LOW,
            P.S_DQ_CLOSE,
            P.S_DQ_PCTCHANGE,
            P.S_DQ_VOLUME,
            P.S_DQ_AMOUNT,
            P.S_DQ_ADJPRECLOSE,
            P.S_DQ_ADJCLOSE
        FROM WIND.CHINACLOSEDFUNDEODPRICE P
        WHERE P.TRADE_DT >= '{start_dt}'
          AND P.TRADE_DT <= '{end_dt}'
          AND EXISTS (
              SELECT 1
              FROM WIND.CHINAMUTUALFUNDDESCRIPTION F
              WHERE F.F_INFO_WINDCODE = P.S_INFO_WINDCODE
                AND F.F_INFO_NAME LIKE '%ETF%'
          )
        ORDER BY P.S_INFO_WINDCODE, P.TRADE_DT
        """
            df = client.query_to_df(sql)
            if not df.empty:
                df = df[df["S_INFO_WINDCODE"].isin(set(codes))].copy()
        else:
            frames = []
            for start in range(0, len(codes), 800):
                batch = codes[start:start + 800]
                placeholders = ",".join([f"'{c}'" for c in batch])
                sql = f"""
            SELECT
                S_INFO_WINDCODE,
                TRADE_DT,
                S_DQ_OPEN,
                S_DQ_HIGH,
                S_DQ_LOW,
                S_DQ_CLOSE,
                S_DQ_PCTCHANGE,
                S_DQ_VOLUME,
                S_DQ_AMOUNT,
                S_DQ_ADJPRECLOSE,
                S_DQ_ADJCLOSE
            FROM WIND.CHINACLOSEDFUNDEODPRICE
            WHERE S_INFO_WINDCODE IN ({placeholders})
              AND TRADE_DT >= '{start_dt}'
              AND TRADE_DT <= '{end_dt}'
            ORDER BY S_INFO_WINDCODE, TRADE_DT
            """
                frames.append(client.query_to_df(sql))
            df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if df.empty:
            return df
        df["TRADE_DT"] = pd.to_datetime(df["TRADE_DT"], format="%Y%m%d")
        numeric_cols = [
            "S_DQ_OPEN", "S_DQ_HIGH", "S_DQ_LOW", "S_DQ_CLOSE",
            "S_DQ_PCTCHANGE", "S_DQ_VOLUME", "S_DQ_AMOUNT",
            "S_DQ_ADJPRECLOSE", "S_DQ_ADJCLOSE",
        ]
        for c in numeric_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df

    def _compute_momentum(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算 ETF 动量/相对强弱指标"""
        df = df.sort_values(["S_INFO_WINDCODE", "TRADE_DT"]).copy()

        def _calc(group: pd.DataFrame) -> pd.DataFrame:
            g = group.copy()
            close = g["S_DQ_CLOSE"]
            g["ret_1d"] = close.pct_change(1)
            g["ret_5d"] = close.pct_change(5)
            g["ret_10d"] = close.pct_change(10)
            g["ret_20d"] = close.pct_change(20)
            g["vol_ma5"] = g["S_DQ_VOLUME"].rolling(5).mean()
            g["vol_ratio_5d"] = g["S_DQ_VOLUME"] / g["vol_ma5"]
            g["close_ma5"] = close.rolling(5).mean()
            g["close_ma10"] = close.rolling(10).mean()
            g["close_ma20"] = close.rolling(20).mean()
            g["above_ma5"] = close > g["close_ma5"]
            g["above_ma10"] = close > g["close_ma10"]
            g["above_ma20"] = close > g["close_ma20"]
            return g

        df = df.groupby("S_INFO_WINDCODE", group_keys=False).apply(_calc)
        return df

    def _attach_meta(self, df: pd.DataFrame) -> pd.DataFrame:
        meta = self._load_universe()
        meta_df = pd.DataFrame(meta)
        meta_df = meta_df.rename(columns={"code": "S_INFO_WINDCODE"})
        df = df.merge(meta_df, on="S_INFO_WINDCODE", how="left")
        return df

    def _compute_relative_strength(
        self,
        df: pd.DataFrame,
        benchmark_code: str,
    ) -> pd.DataFrame:
        """计算相对基准的相对强弱（RS）"""
        if benchmark_code not in df["S_INFO_WINDCODE"].values:
            df["rs_vs_benchmark_5d"] = np.nan
            df["rs_vs_benchmark_10d"] = np.nan
            return df

        bench = df[df["S_INFO_WINDCODE"] == benchmark_code][["TRADE_DT", "ret_5d", "ret_10d"]].copy()
        bench = bench.rename(columns={"ret_5d": "bench_ret_5d", "ret_10d": "bench_ret_10d"})
        df = df.merge(bench, on="TRADE_DT", how="left")
        df["rs_vs_benchmark_5d"] = df["ret_5d"] - df["bench_ret_5d"]
        df["rs_vs_benchmark_10d"] = df["ret_10d"] - df["bench_ret_10d"]
        df = df.drop(columns=["bench_ret_5d", "bench_ret_10d"])
        return df

    def _construct_etf_analysis_text(
        self,
        df: pd.DataFrame,
        trigger_time: str,
        trade_date: str,
    ) -> str:
        """构造 ETF 市场/动量文本摘要"""
        latest = df[df["TRADE_DT"] == df["TRADE_DT"].max()].copy()
        latest = latest.sort_values("ret_5d", ascending=False)

        lines = [
            f"## {trade_date} 全市场 ETF 动量扫描（截至 {trigger_time}）",
            "",
            f"监控 ETF 数量：{len(latest)} 只，覆盖股票/债券/商品/货币/多资产，"
            f"基准：{self._benchmark_code or '沪深300ETF'}",
            "",
            "### 一、近 5 日涨幅 TOP10",
        ]
        for _, row in latest.head(10).iterrows():
            lines.append(
                f"- {row.get('name', row['S_INFO_WINDCODE'])} ({row['S_INFO_WINDCODE']}, "
                f"{row.get('sector', '未知')}/{row.get('theme', '未知')}): "
                f"5日 {row.get('ret_5d', 0):.2%}, 10日 {row.get('ret_10d', 0):.2%}, "
                f"20日 {row.get('ret_20d', 0):.2%}, 相对基准 5日 {row.get('rs_vs_benchmark_5d', 0):.2%}, "
                f"量价比 {row.get('vol_ratio_5d', 0):.2f}"
            )

        lines.extend(["", "### 二、近 5 日跌幅 TOP10"])
        for _, row in latest.tail(10).iterrows():
            lines.append(
                f"- {row.get('name', row['S_INFO_WINDCODE'])} ({row['S_INFO_WINDCODE']}, "
                f"{row.get('sector', '未知')}/{row.get('theme', '未知')}): "
                f"5日 {row.get('ret_5d', 0):.2%}, 10日 {row.get('ret_10d', 0):.2%}, "
                f"20日 {row.get('ret_20d', 0):.2%}"
            )

        # 动量结构统计
        above_ma20 = (latest["above_ma20"].sum() / len(latest)) if "above_ma20" in latest.columns else 0
        lines.extend([
            "",
            "### 三、技术面概览",
            f"- 收盘价站上 20 日均线的 ETF 占比：{above_ma20:.1%}",
        ])

        # 行业聚合
        if "asset_class" in latest.columns:
            sector_df = latest.groupby("asset_class").agg(
                etf_count=("S_INFO_WINDCODE", "count"),
                avg_ret_5d=("ret_5d", "mean"),
                avg_ret_10d=("ret_10d", "mean"),
            ).reset_index().sort_values("avg_ret_5d", ascending=False)
            lines.extend(["", "### 四、行业板块平均动量"])
            for _, row in sector_df.iterrows():
                lines.append(
                    f"- {row['asset_class']}: {row['etf_count']} 只, 5日平均 {row['avg_ret_5d']:.2%}, "
                    f"10日平均 {row['avg_ret_10d']:.2%}"
                )

        return "\n".join(lines)

    async def _llm_summary(self, analysis_text: str, trigger_time: str) -> str:
        """让 LLM 生成 ETF 轮动市场摘要"""
        prompt = f"""你是一位 ETF 量化策略分析师。请根据以下 ETF 动量扫描数据，生成一份客观的市场风格摘要（1200字符以内），用于行业/主题 ETF 轮动决策。

{analysis_text}

输出要求：
- 指出当前强势/弱势的板块与主题
- 指出大盘 vs 中小盘、成长 vs 价值的相对强弱
- 不要预测未来，只陈述截至 {trigger_time} 的客观数据事实
"""
        messages = [
            {"role": "system", "content": "你擅长从 ETF 动量数据中提取行业轮动线索。"},
            {"role": "user", "content": prompt},
        ]
        try:
            response = await GLOBAL_LLM.a_run(
                messages=messages,
                thinking=False,
                temperature=0.3,
                max_tokens=1500,
            )
            return response.content if response and response.content else "LLM分析失败"
        except Exception as e:
            logger.error(f"Wind ETF LLM 摘要失败: {e}")
            return f"LLM分析失败: {str(e)}"

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        """DataSourceBase 接口：返回 DataFrame"""
        try:
            df = self.get_data_cached(trigger_time)
            if df is not None:
                return df

            from config.config import cfg
            client = get_wind_client(cfg)

            trade_date_dt = datetime.strptime(get_previous_trading_date(trigger_time), "%Y%m%d")
            start_dt = (trade_date_dt - timedelta(days=self.lookback_days * 1.5)).strftime("%Y%m%d")
            end_dt = trade_date_dt.strftime("%Y%m%d")
            trade_date = end_dt

            self._load_universe(as_of_date=trade_date_dt.strftime("%Y-%m-%d"))
            logger.info(f"从 Wind 拉取 ETF 数据: {start_dt} ~ {end_dt}, 共 {len(self.all_codes)} 只")
            price_df = self._query_price(client, self.all_codes, start_dt, end_dt)
            if price_df.empty:
                logger.warning("Wind ETF 价格数据为空")
                return pd.DataFrame()

            price_df = self._compute_momentum(price_df)
            price_df = self._attach_meta(price_df)
            price_df = self._compute_relative_strength(price_df, self._benchmark_code)

            analysis_text = self._construct_etf_analysis_text(price_df, trigger_time, trade_date)
            llm_summary = await self._llm_summary(analysis_text, trigger_time)

            # 构建符合 DataSourceBase 规范的 DataFrame
            # Agent 已经获得结构化摘要，只保留最新截面的有限字段，避免把十几万行
            # 历史数据转成 Python dict 后造成数倍内存放大。
            latest_snapshot = price_df[price_df["TRADE_DT"] == price_df["TRADE_DT"].max()].copy()
            compact_columns = [
                "S_INFO_WINDCODE", "TRADE_DT", "S_DQ_CLOSE", "S_DQ_AMOUNT",
                "ret_5d", "ret_10d", "ret_20d", "vol_ratio_5d",
                "rs_vs_benchmark_5d", "rs_vs_benchmark_10d", "name",
                "asset_class", "market_scope", "strategy_type",
            ]
            compact_columns = [column for column in compact_columns if column in latest_snapshot.columns]
            latest_snapshot = latest_snapshot.sort_values("S_DQ_AMOUNT", ascending=False).head(300)

            data = [{
                "title": f"{trade_date}: Wind ETF 风格轮动扫描",
                "content": f"## 原始动量数据\n\n{analysis_text}\n\n## LLM 摘要\n\n{llm_summary}",
                "pub_time": trigger_time,
                "url": None,
                "raw_data": latest_snapshot[compact_columns].to_dict(orient="records"),
            }]
            df = pd.DataFrame(data)
            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            logger.error(f"Wind ETF 数据源失败: {e}")
            traceback.print_exc()
            return pd.DataFrame()


if __name__ == "__main__":
    ds = WindETFDataSource()
    df = asyncio.run(ds.get_data("2026-09-10 09:00:00"))
    if not df.empty:
        print(df.iloc[0]["content"][:2000])
