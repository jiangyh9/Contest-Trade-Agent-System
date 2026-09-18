"""
基于 AKShare 的历史新闻/公告数据源

用途：回测模式专用。只读取 trigger_time 之前（含上一个交易日）已发布的
宏观新闻、财经日历、分红除权、停牌公告等信息，避免未来数据泄漏。

注意：AKShare 的 news_cctv 等接口返回的是发布日期维度数据，无法精确到
盘中分钟。因此回测时统一以上一个交易日的收盘为分界点。
"""

import pandas as pd
import asyncio
import traceback
from datetime import datetime
from data_source.data_source_base import DataSourceBase
from utils.akshare_utils import akshare_cached
from models.llm_model import GLOBAL_LLM
from loguru import logger
from utils.date_utils import get_previous_trading_date


class AkshareNews(DataSourceBase):
    def __init__(self):
        super().__init__("akshare_news")

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            df = self.get_data_cached(trigger_time)
            if df is not None:
                return df

            trade_date = get_previous_trading_date(trigger_time)
            logger.info(f"获取 {trade_date} 的 AKShare 历史新闻/公告")

            llm_summary_dict = await self.get_llm_summary(trade_date, trigger_time)
            data = [{
                "title": f"{trade_date}:AKShare历史新闻公告汇总",
                "content": llm_summary_dict["llm_summary"],
                "pub_time": trigger_time,
                "url": None,
            }]
            df = pd.DataFrame(data)
            self.save_data_cached(trigger_time, df)
            return df

        except Exception as e:
            logger.error(f"获取AKShare历史新闻失败: {e}")
            traceback.print_exc()
            return pd.DataFrame()

    def _get_cctv_news(self, trade_date: str) -> pd.DataFrame:
        """获取 CCTV 新闻联播/财经新闻（按日期）"""
        try:
            df = akshare_cached.run(
                func_name="news_cctv",
                func_kwargs={"date": trade_date},
                verbose=False,
            )
            if df.empty:
                logger.warning(f"{trade_date} 无 CCTV 新闻")
                return pd.DataFrame()
            logger.info(f"获取 {trade_date} CCTV 新闻 {len(df)} 条")
            return df
        except Exception as e:
            logger.warning(f"获取CCTV新闻失败: {e}")
            return pd.DataFrame()

    def _get_economic_calendar(self, trade_date: str) -> pd.DataFrame:
        """获取百度财经日历（国内外重要经济数据/事件）"""
        try:
            df = akshare_cached.run(
                func_name="news_economic_baidu",
                func_kwargs={"date": trade_date},
                verbose=False,
            )
            if df.empty:
                return pd.DataFrame()
            logger.info(f"获取 {trade_date} 财经日历 {len(df)} 条")
            return df
        except Exception as e:
            logger.warning(f"获取财经日历失败: {e}")
            return pd.DataFrame()

    def _get_dividend_notify(self, trade_date: str) -> pd.DataFrame:
        """获取分红除权公告"""
        try:
            df = akshare_cached.run(
                func_name="news_trade_notify_dividend_baidu",
                func_kwargs={"date": trade_date},
                verbose=False,
            )
            if df.empty:
                return pd.DataFrame()
            logger.info(f"获取 {trade_date} 分红公告 {len(df)} 条")
            return df
        except Exception as e:
            logger.warning(f"获取分红公告失败: {e}")
            return pd.DataFrame()

    def _get_suspend_notify(self, trade_date: str) -> pd.DataFrame:
        """获取停牌复牌公告"""
        try:
            df = akshare_cached.run(
                func_name="news_trade_notify_suspend_baidu",
                func_kwargs={"date": trade_date},
                verbose=False,
            )
            if df.empty:
                return pd.DataFrame()
            logger.info(f"获取 {trade_date} 停牌公告 {len(df)} 条")
            return df
        except Exception as e:
            logger.warning(f"获取停牌公告失败: {e}")
            return pd.DataFrame()

    def _construct_analysis_text(
        self,
        trade_date: str,
        cctv_df: pd.DataFrame,
        eco_df: pd.DataFrame,
        div_df: pd.DataFrame,
        susp_df: pd.DataFrame,
    ) -> str:
        sections = [f"## {trade_date} AKShare 历史新闻/公告汇总\n"]

        if not cctv_df.empty:
            sections.append("### 一、CCTV 新闻要点")
            for _, row in cctv_df.head(10).iterrows():
                title = row.get("title", "")
                content = row.get("content", "")
                sections.append(f"- {title}: {content[:200]}")
            sections.append("")

        if not eco_df.empty:
            sections.append("### 二、国内外财经数据/事件")
            for _, row in eco_df.head(10).iterrows():
                region = row.get("地区", "")
                event = row.get("事件", "")
                pub = row.get("公布", "")
                prev = row.get("前值", "")
                sections.append(f"- {region} {event}: 公布 {pub}, 前值 {prev}")
            sections.append("")

        if not div_df.empty:
            sections.append("### 三、A股分红除权公告")
            for _, row in div_df.head(10).iterrows():
                name = row.get("股票简称", "")
                code = row.get("股票代码", "")
                dividend = row.get("分红", "")
                sections.append(f"- {name}({code}): 分红 {dividend}")
            sections.append("")

        if not susp_df.empty:
            sections.append("### 四、A股停牌复牌公告")
            for _, row in susp_df.head(10).iterrows():
                name = row.get("股票简称", "")
                code = row.get("股票代码", "")
                reason = row.get("停牌事项说明", "")
                sections.append(f"- {name}({code}): {reason}")
            sections.append("")

        return "\n".join(sections)

    async def get_llm_summary(self, trade_date: str, trigger_time: str) -> dict:
        try:
            cctv_df = self._get_cctv_news(trade_date)
            eco_df = self._get_economic_calendar(trade_date)
            div_df = self._get_dividend_notify(trade_date)
            susp_df = self._get_suspend_notify(trade_date)

            analysis_text = self._construct_analysis_text(
                trade_date, cctv_df, eco_df, div_df, susp_df
            )
            available_sources = sum([
                0 if cctv_df.empty else 1,
                0 if eco_df.empty else 1,
                0 if div_df.empty else 1,
                0 if susp_df.empty else 1,
            ])

            if available_sources == 0:
                return {
                    "trade_date": trade_date,
                    "raw_data": "无数据",
                    "llm_summary": f"{trade_date} 无 AKShare 历史新闻/公告数据",
                    "data_count": 0,
                }

            prompt = f"""
请分析以下 {trade_date}（对应回测触发时间 {trigger_time}，以上一个交易日为数据截止日）的A股宏观新闻与公告数据，
生成一份客观的市场背景摘要（1500字符以内）。

{analysis_text}

## 输出要求
- 总结当日 CCTV 新闻要点、国内外财经事件、A股分红除权和停牌公告
- 只陈述已发生的事实，不做未来预测
- 控制在1500字符以内
"""

            messages = [
                {"role": "system", "content": "你是一位金融市场宏观分析师，擅长从新闻公告中提取客观事实。"},
                {"role": "user", "content": prompt},
            ]
            response = await GLOBAL_LLM.a_run(
                messages=messages,
                thinking=False,
                temperature=0.3,
                max_tokens=1500,
            )
            llm_summary = response.content if response and response.content else "LLM分析失败"

            return {
                "trade_date": trade_date,
                "raw_data": analysis_text,
                "llm_summary": llm_summary,
                "data_count": available_sources,
            }

        except Exception as e:
            logger.error(f"AKShare新闻 LLM 总结失败: {e}")
            traceback.print_exc()
            return {
                "trade_date": trade_date,
                "raw_data": "分析失败",
                "llm_summary": f"分析失败: {str(e)}",
                "data_count": 0,
            }


if __name__ == "__main__":
    news_source = AkshareNews()
    df = asyncio.run(news_source.get_data("2024-08-19 09:00:00"))
    if len(df) > 0:
        print(df.content.values[0])
