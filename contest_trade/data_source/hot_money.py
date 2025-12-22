"""
热钱市场数据源
整合各种热钱市场数据，包括游资交易、涨跌停、龙虎榜等
"""
import pandas as pd
import asyncio
from datetime import datetime
from utils.date_utils import get_previous_trading_date
from data_source.data_source_base import DataSourceBase
from utils.tushare_provider import TushareDataProvider
from models.llm_model import GLOBAL_LLM
from loguru import logger

class HotMoney(DataSourceBase):
    def __init__(self):
        super().__init__("hot_money")

    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            df = self.get_data_cached(trigger_time)
            if df is not None:
                return df
            
            trade_date = get_previous_trading_date(trigger_time)   
            logger.info(f"获取 {trade_date} 的价格市场数据")

            llm_summary_dict = await self.get_llm_summary(trigger_time)
            data = [{
                "title": f"{trade_date}: 市场热点资金流向数据汇总",
                "content": llm_summary_dict["llm_summary"],
                "pub_time": trigger_time,
                "url": None
            }]
            df = pd.DataFrame(data)
            self.save_data_cached(trigger_time, df)
            return df
                
        except Exception as e:
            logger.error(f"获取价格市场数据失败: {e}")
            return pd.DataFrame()
        
    async def get_raw_data(self, trigger_time: str) -> pd.DataFrame:
        """
        异步获取热钱市场数据
        
        Args:
            trigger_time: 触发时间，格式为'YYYY-MM-DD HH:MM:SS'
            
        Returns:
            DataFrame: 热钱市场数据
        """
        try:
            trade_date = get_previous_trading_date(trigger_time)
            
            logger.info(f"异步获取 {trade_date} 的热钱市场数据")
            
            # 由于tushare数据获取是同步的，我们在异步方法中使用线程池来避免阻塞
            loop = asyncio.get_event_loop()
            
            # 使用线程池执行同步的数据获取
            df = await loop.run_in_executor(None, self._get_data_sync, trigger_time)
            
            return df
                
        except Exception as e:
            logger.error(f"异步获取热钱市场数据失败: {e}")
            return pd.DataFrame()
    
    def _get_data_sync(self, trigger_time: str) -> pd.DataFrame:
        """
        同步获取热钱市场数据（内部方法）
        
        Args:
            trigger_time: 触发时间，格式为'YYYY-MM-DD HH:MM:SS'
            
        Returns:
            DataFrame: 热钱市场数据
        """
        try:
            trade_date = get_previous_trading_date(trigger_time)
            
            logger.info(f"获取 {trade_date} 的热钱市场数据")
            
            # 获取各类热钱数据
            data_dict = {}
            
            # 1. 热门股明细数据
            hm_detail_df = TushareDataProvider.get_hm_detail_data(trade_date)
            if not hm_detail_df.empty:
                hm_detail_df['data_type'] = 'hm_detail'
                data_dict['hm_detail'] = hm_detail_df
                logger.info(f"获取热门股明细数据: {len(hm_detail_df)} 条")
            
            # 2. 最强板块统计数据
            limit_cpt_df = TushareDataProvider.get_limit_cpt_list_data(trade_date)
            if not limit_cpt_df.empty:
                limit_cpt_df['data_type'] = 'limit_cpt_list'
                data_dict['limit_cpt_list'] = limit_cpt_df
                logger.info(f"获取最强板块统计数据: {len(limit_cpt_df)} 条")
            
            # 3. 涨跌停列表数据
            limit_list_df = TushareDataProvider.get_limit_list_d_data(trade_date)
            if not limit_list_df.empty:
                limit_list_df['data_type'] = 'limit_list_d'
                data_dict['limit_list_d'] = limit_list_df
                logger.info(f"获取涨跌停列表数据: {len(limit_list_df)} 条")
            
            # 4. 连板天梯数据
            limit_step_df = TushareDataProvider.get_limit_step_data(trade_date)
            if not limit_step_df.empty:
                limit_step_df['data_type'] = 'limit_step'
                data_dict['limit_step'] = limit_step_df
                logger.info(f"获取连板天梯数据: {len(limit_step_df)} 条")
            
            # 5. 龙虎榜机构成交明细数据
            top_inst_df = TushareDataProvider.get_top_inst_data(trade_date)
            if not top_inst_df.empty:
                top_inst_df['data_type'] = 'top_inst'
                data_dict['top_inst'] = top_inst_df
                logger.info(f"获取龙虎榜机构成交明细数据: {len(top_inst_df)} 条")
            
            # 6. 龙虎榜每日交易明细数据
            top_list_df = TushareDataProvider.get_top_list_data(trade_date)
            if not top_list_df.empty:
                top_list_df['data_type'] = 'top_list'
                data_dict['top_list'] = top_list_df
                logger.info(f"获取龙虎榜每日交易明细数据: {len(top_list_df)} 条")
            
            # 合并所有数据
            if data_dict:
                all_data = []
                for data_type, df in data_dict.items():
                    all_data.append(df)
                
                combined_df = pd.concat(all_data, ignore_index=True)
                combined_df['trigger_time'] = trigger_time
                
                total_records = len(combined_df)
                logger.info(f"热钱市场数据获取完成，总计 {total_records} 条记录")
                
                return combined_df
            else:
                logger.warning(f"{trade_date} 无热钱市场数据")
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"获取热钱市场数据失败: {e}")
            return pd.DataFrame()
    
    async def get_data_by_date_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        异步获取指定日期范围内的热钱市场数据
        
        Args:
            start_date: 开始日期，格式为'YYYYMMDD'
            end_date: 结束日期，格式为'YYYYMMDD'
            
        Returns:
            DataFrame: 热钱市场数据汇总
        """
        try:
            from trade_agent.utils.tushare_utils import get_trade_date
            
            # 获取交易日期列表
            trade_dates = get_trade_date()
            target_dates = [d for d in trade_dates if start_date <= d <= end_date]
            
            logger.info(f"异步获取 {start_date} 到 {end_date} 的热钱市场数据，共 {len(target_dates)} 个交易日")
            
            # 使用线程池并发获取数据
            loop = asyncio.get_event_loop()
            tasks = []
            
            for trade_date in target_dates:
                # 构造trigger_time格式
                trigger_time = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]} 10:00:00"
                task = loop.run_in_executor(None, self._get_data_sync, trigger_time)
                tasks.append(task)
            
            # 等待所有任务完成
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            all_data = []
            for result in results:
                if isinstance(result, pd.DataFrame) and not result.empty:
                    all_data.append(result)
            
            if all_data:
                combined_df = pd.concat(all_data, ignore_index=True)
                logger.info(f"异步成功获取热钱市场数据，总计 {len(combined_df)} 条记录")
                return combined_df
            else:
                logger.warning("异步未获取到任何热钱市场数据")
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"异步获取热钱市场数据失败: {e}")
            return pd.DataFrame()
    
    async def get_summary_data(self, trigger_time: str) -> dict:
        """
        异步获取热钱市场数据摘要
        
        Args:
            trigger_time: 触发时间，格式为'YYYY-MM-DD HH:MM:SS'
            
        Returns:
            dict: 数据摘要信息
        """
        df = await self.get_raw_data(trigger_time)
        
        if df.empty:
            return {
                'trade_date': trigger_time[:10],
                'total_records': 0,
                'data_types': [],
                'summary': '无数据'
            }
        
        # 按数据类型统计
        data_type_counts = df['data_type'].value_counts().to_dict()
        
        summary = {
            'trade_date': trigger_time[:10],
            'total_records': len(df),
            'data_types': data_type_counts,
            'summary': f"共获取{len(df)}条记录，包含{len(data_type_counts)}种数据类型"
        }
        
        return summary
    
    async def get_llm_summary(self, trigger_time: str) -> dict:
        """
        获取热钱市场数据的LLM分析总结
        
        Args:
            trigger_time: 触发时间，格式为'YYYY-MM-DD HH:MM:SS'
            
        Returns:
            dict: 包含原始数据和LLM分析总结的字典
        """
        try:
            # 异步获取原始数据
            df = await self.get_raw_data(trigger_time)
            trade_date = get_previous_trading_date(trigger_time)
            
            if df.empty:
                return {
                    'trade_date': trade_date,
                    'raw_data': "无数据",
                    'llm_summary': "当日无热钱市场数据",
                    'data_count': 0
                }
            
            # 构造数据摘要文本
            data_summary = self._construct_data_summary_text(df, trade_date)
            
            # 构造LLM prompt
            prompt = f"""
请分析以下{trade_date}的热钱市场数据，并给出专业的市场洞察总结：

{data_summary}

请从以下几个维度进行分析：
1. 热门股票和板块的主要特征
2. 市场情绪和资金流向特征
3. 涨跌停板块的结构性特点
4. 龙虎榜资金的操作特征
5. 对后续市场走势的启示

请用简洁专业的语言总结，突出关键信息。
"""
            
            # 异步调用LLM进行分析
            messages = [
                {"role": "system", "content": "你是一位专业的金融分析师，擅长分析和总结股市热钱和游资动向。请帮助用户将复杂的交易数据总结为简洁明了的市场洞察。"},
                {"role": "user", "content": prompt}
            ]
            
            response = await GLOBAL_LLM.a_run(
                messages=messages,
                temperature=0.3,
                max_tokens=1000
            )
            
            if response and response.content:
                return {
                    'trade_date': trade_date,
                    'raw_data': data_summary,
                    'llm_summary': response.content,
                    'data_count': len(df),
                    'data_types': df['data_type'].value_counts().to_dict()
                }
            else:
                return {
                    'trade_date': trade_date,
                    'raw_data': data_summary,
                    'llm_summary': "LLM分析失败",
                    'data_count': len(df),
                    'data_types': df['data_type'].value_counts().to_dict()
                }
                
        except Exception as e:
            logger.error(f"获取LLM总结失败: {e}")
            return {
                'trade_date': trade_date if 'trade_date' in locals() else trigger_time[:10],
                'raw_data': "数据获取失败",
                'llm_summary': f"分析失败: {str(e)}",
                'data_count': 0
            }
    
    async def get_llm_summary_with_custom_prompt(self, trigger_time: str, custom_prompt: str = None) -> dict:
        """
        使用自定义prompt获取热钱市场数据的LLM分析总结
        
        Args:
            trigger_time: 触发时间，格式为'YYYY-MM-DD HH:MM:SS'
            custom_prompt: 自定义的分析提示词
            
        Returns:
            dict: 包含原始数据和LLM分析总结的字典
        """
        try:
            # 异步获取原始数据
            df = await self.get_raw_data(trigger_time)
            trade_date = get_previous_trading_date(trigger_time)
            
            if df.empty:
                return {
                    'trade_date': trade_date,
                    'raw_data': "无数据",
                    'llm_summary': "当日无热钱市场数据",
                    'data_count': 0
                }
            
            # 构造数据摘要文本
            data_summary = self._construct_data_summary_text(df, trade_date)
            
            # 使用自定义prompt或默认prompt
            if custom_prompt:
                prompt = f"""
{custom_prompt}

{trade_date}的热钱市场数据：

{data_summary}
"""
            else:
                prompt = f"""
请分析以下{trade_date}的热钱市场数据，并给出专业的市场洞察总结：

{data_summary}

请从以下几个维度进行分析：
1. 热门股票和板块的主要特征
2. 市场情绪和资金流向特征
3. 涨跌停板块的结构性特点
4. 龙虎榜资金的操作特征
5. 对后续市场走势的启示

请用简洁专业的语言总结，突出关键信息。
"""
            
            # 异步调用LLM进行分析
            messages = [
                {"role": "system", "content": "你是一位专业的金融分析师，擅长分析和总结股市热钱和游资动向。请帮助用户将复杂的交易数据总结为简洁明了的市场洞察。"},
                {"role": "user", "content": prompt}
            ]
            
            response = await GLOBAL_LLM.a_run(
                messages=messages,
                temperature=0.3,
                max_tokens=1000
            )
            
            if response and response.content:
                return {
                    'trade_date': trade_date,
                    'raw_data': data_summary,
                    'llm_summary': response.content,
                    'data_count': len(df),
                    'data_types': df['data_type'].value_counts().to_dict()
                }
            else:
                return {
                    'trade_date': trade_date,
                    'raw_data': data_summary,
                    'llm_summary': "LLM分析失败",
                    'data_count': len(df),
                    'data_types': df['data_type'].value_counts().to_dict()
                }
                
        except Exception as e:
            logger.error(f"获取自定义LLM总结失败: {e}")
            return {
                'trade_date': trade_date if 'trade_date' in locals() else trigger_time[:10],
                'raw_data': "数据获取失败",
                'llm_summary': f"分析失败: {str(e)}",
                'data_count': 0
            }
    
    def get_llm_summary_sync(self, trigger_time: str) -> dict:
        """
        同步版本的LLM总结获取方法
        
        Args:
            trigger_time: 触发时间，格式为'YYYY-MM-DD HH:MM:SS'
            
        Returns:
            dict: 包含原始数据和LLM分析总结的字典
        """
        try:
            return asyncio.run(self.get_llm_summary(trigger_time))
        except Exception as e:
            logger.error(f"同步LLM总结失败: {e}")
            return {
                'trade_date': trigger_time[:10],
                'raw_data': "数据获取失败",
                'llm_summary': f"分析失败: {str(e)}",
                'data_count': 0
            }
    
    def _construct_data_summary_text(self, df: pd.DataFrame, trade_date: str) -> str:
        """
        构造数据摘要文本，用于LLM分析
        
        Args:
            df: 热钱市场数据
            trade_date: 交易日期
            
        Returns:
            str: 格式化的数据摘要文本
        """
        if df.empty:
            return f"{trade_date} 无热钱市场数据"
        
        summary_parts = []
        
        # 按数据类型分组处理
        for data_type in df['data_type'].unique():
            type_df = df[df['data_type'] == data_type]
            
            if data_type == 'hm_detail':
                summary_parts.append(self._format_hm_detail_data(type_df, trade_date))
            elif data_type == 'limit_cpt_list':
                summary_parts.append(self._format_limit_cpt_list_data(type_df, trade_date))
            elif data_type == 'limit_list_d':
                summary_parts.append(self._format_limit_list_d_data(type_df, trade_date))
            elif data_type == 'limit_step':
                summary_parts.append(self._format_limit_step_data(type_df, trade_date))
            elif data_type == 'top_inst':
                summary_parts.append(self._format_top_inst_data(type_df, trade_date))
            elif data_type == 'top_list':
                summary_parts.append(self._format_top_list_data(type_df, trade_date))
        
        return "\n\n".join(summary_parts)
    
    def _format_hm_detail_data(self, df: pd.DataFrame, trade_date: str) -> str:
        """格式化热门股明细数据"""
        if df.empty:
            return ""
        
        # 按净买卖金额排序，取前10
        if 'net_amount' in df.columns:
            top_10 = df.nlargest(10, 'net_amount')
            sort_field = "净买卖金额"
        elif 'buy_amount' in df.columns:
            top_10 = df.nlargest(10, 'buy_amount')
            sort_field = "买入金额"
        else:
            top_10 = df.head(10)
            sort_field = "默认"
        
        descriptions = []
        for _, row in top_10.iterrows():
            stock_name = row.get('ts_name', '')
            stock_code = row.get('ts_code', '')
            hm_name = row.get('hm_name', '')
            
            if stock_name and stock_code:
                stock_identifier = f"{stock_name}({stock_code})"
            elif stock_name:
                stock_identifier = stock_name
            else:
                stock_identifier = f"股票({stock_code})"
            
            desc_parts = []
            if hm_name:
                desc_parts.append(f"游资机构{hm_name}")
            
            desc_parts.append(f"对{stock_identifier}")
            
            if 'buy_amount' in row and pd.notna(row['buy_amount']):
                desc_parts.append(f"买入{row['buy_amount']:.2f}元")
            if 'sell_amount' in row and pd.notna(row['sell_amount']):
                desc_parts.append(f"卖出{row['sell_amount']:.2f}元")
            if 'net_amount' in row and pd.notna(row['net_amount']):
                desc_parts.append(f"净买卖{row['net_amount']:.2f}元")
            
            descriptions.append("，".join(desc_parts))
        
        return f"{trade_date}，前十的游资交易中：" + "；".join(descriptions)
    
    def _format_limit_cpt_list_data(self, df: pd.DataFrame, trade_date: str) -> str:
        """格式化最强板块统计数据"""
        if df.empty:
            return ""
        
        descriptions = []
        for _, row in df.iterrows():
            name = row.get('name', '')
            code = row.get('ts_code', '')
            
            if name and code:
                block_identifier = f"板块{name}({code})"
            elif name:
                block_identifier = f"板块{name}"
            else:
                block_identifier = f"板块({code})"
            
            desc_parts = [block_identifier]
            
            if 'days' in row and pd.notna(row['days']):
                desc_parts.append(f"上榜{row['days']}天")
            if 'up_stat' in row and pd.notna(row['up_stat']):
                desc_parts.append(f"连板高度{row['up_stat']}")
            if 'cons_nums' in row and pd.notna(row['cons_nums']):
                desc_parts.append(f"连板家数{row['cons_nums']}家")
            if 'up_nums' in row and pd.notna(row['up_nums']):
                desc_parts.append(f"涨停家数{row['up_nums']}家")
            if 'pct_chg' in row and pd.notna(row['pct_chg']):
                desc_parts.append(f"涨跌幅{row['pct_chg']:.2f}%")
            
            descriptions.append("，".join(desc_parts))
        
        return f"{trade_date}，最强板块统计：" + "；".join(descriptions)
    
    def _format_limit_list_d_data(self, df: pd.DataFrame, trade_date: str) -> str:
        """格式化涨跌停列表数据"""
        if df.empty:
            return ""
        
        descriptions = []
        for _, row in df.iterrows():
            stock_name = row.get('name', '')
            stock_code = row.get('ts_code', '')
            
            if stock_name and stock_code:
                stock_identifier = f"{stock_name}({stock_code})"
            elif stock_name:
                stock_identifier = stock_name
            else:
                stock_identifier = f"股票({stock_code})"
            
            desc_parts = [stock_identifier]
            
            if 'industry' in row and pd.notna(row['industry']):
                desc_parts.append(f"属于{row['industry']}行业")
            if 'close' in row and pd.notna(row['close']):
                desc_parts.append(f"收盘价{row['close']:.2f}元")
            if 'pct_chg' in row and pd.notna(row['pct_chg']):
                desc_parts.append(f"涨跌幅{row['pct_chg']:.2f}%")
            if 'open_times' in row and pd.notna(row['open_times']):
                desc_parts.append(f"炸板{row['open_times']}次")
            if 'limit_times' in row and pd.notna(row['limit_times']):
                desc_parts.append(f"连板数{row['limit_times']}")
            
            descriptions.append("，".join(desc_parts))
        
        return f"{trade_date}，涨跌停情况：" + "；".join(descriptions)
    
    def _format_limit_step_data(self, df: pd.DataFrame, trade_date: str) -> str:
        """格式化连板天梯数据"""
        if df.empty:
            return ""
        
        descriptions = []
        for _, row in df.iterrows():
            stock_name = row.get('name', '')
            stock_code = row.get('ts_code', '')
            
            if stock_name and stock_code:
                stock_identifier = f"{stock_name}({stock_code})"
            elif stock_name:
                stock_identifier = stock_name
            else:
                stock_identifier = f"股票({stock_code})"
            
            desc_parts = [stock_identifier]
            
            if 'nums' in row and pd.notna(row['nums']):
                desc_parts.append(f"连板{row['nums']}次")
            
            descriptions.append("，".join(desc_parts))
        
        return f"{trade_date}，连板天梯：" + "；".join(descriptions)
    
    def _format_top_inst_data(self, df: pd.DataFrame, trade_date: str) -> str:
        """格式化龙虎榜机构成交明细数据"""
        if df.empty:
            return ""
        
        # 筛选净成交额net_buy前十和buy_rate前十
        combined_data = []
        
        if 'net_buy' in df.columns:
            top_net_buy = df.nlargest(10, 'net_buy')
            combined_data.append(top_net_buy)
        
        if 'buy_rate' in df.columns:
            top_buy_rate = df.nlargest(10, 'buy_rate')
            combined_data.append(top_buy_rate)
        
        if combined_data:
            if len(combined_data) > 1:
                top_stocks = pd.concat(combined_data).drop_duplicates(subset=['ts_code'])
            else:
                top_stocks = combined_data[0]
        else:
            top_stocks = df.head(10)
        
        descriptions = []
        for _, row in top_stocks.iterrows():
            desc_parts = []
            
            if 'exalter' in row and pd.notna(row['exalter']):
                desc_parts.append(f"营业部{row['exalter']}")
            
            stock_code = row.get('ts_code', 'N/A')
            desc_parts.append(f"对{stock_code}")
            
            if 'buy' in row and pd.notna(row['buy']):
                desc_parts.append(f"买入{row['buy']:.2f}元")
            if 'sell' in row and pd.notna(row['sell']):
                desc_parts.append(f"卖出{row['sell']:.2f}元")
            if 'net_buy' in row and pd.notna(row['net_buy']):
                desc_parts.append(f"净成交{row['net_buy']:.2f}元")
            
            descriptions.append("，".join(desc_parts))
        
        return f"{trade_date}，龙虎榜机构成交明细：" + "；".join(descriptions)
    
    def _format_top_list_data(self, df: pd.DataFrame, trade_date: str) -> str:
        """格式化龙虎榜每日交易明细数据"""
        if df.empty:
            return ""
        
        # 筛选net_amount前十和amount前十的股票
        combined_data = []
        
        if 'net_amount' in df.columns:
            top_net = df.nlargest(10, 'net_amount')
            combined_data.append(top_net)
        
        if 'amount' in df.columns:
            top_amount = df.nlargest(10, 'amount')
            combined_data.append(top_amount)
        
        if combined_data:
            if len(combined_data) > 1:
                top_stocks = pd.concat(combined_data).drop_duplicates(subset=['ts_code'])
            else:
                top_stocks = combined_data[0]
        else:
            top_stocks = df.head(20)
        
        descriptions = []
        for _, row in top_stocks.iterrows():
            stock_name = row.get('name', '')
            stock_code = row.get('ts_code', '')
            
            if stock_name and stock_code:
                stock_identifier = f"{stock_name}({stock_code})"
            elif stock_name:
                stock_identifier = stock_name
            else:
                stock_identifier = f"股票({stock_code})"
            
            desc_parts = [stock_identifier]
            
            if 'close' in row and pd.notna(row['close']):
                desc_parts.append(f"收盘价{row['close']:.2f}元")
            if 'pct_change' in row and pd.notna(row['pct_change']):
                desc_parts.append(f"涨跌幅{row['pct_change']:.2f}%")
            if 'turnover_rate' in row and pd.notna(row['turnover_rate']):
                desc_parts.append(f"换手率{row['turnover_rate']:.2f}%")
            if 'net_amount' in row and pd.notna(row['net_amount']):
                desc_parts.append(f"龙虎榜净买入{row['net_amount']:.2f}元")
            
            descriptions.append("，".join(desc_parts))
        
        return f"{trade_date}，龙虎榜每日交易明细：" + "；".join(descriptions)

if __name__ == "__main__":
    hot_money = HotMoney()  
    df = asyncio.run(hot_money.get_data("2025-05-09 10:00:00"))
    print(df.head())
    print(df.to_json(orient="records", force_ascii=False, indent=4))