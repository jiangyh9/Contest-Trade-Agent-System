"""
基于 akshare 的价格市场数据源
整合K线数据、板块资金流向等，生成综合宏观市场分析
"""
import pandas as pd
import asyncio
import traceback
from datetime import datetime
from data_source.data_source_base import DataSourceBase
from utils.akshare_utils import akshare_cached
from models.llm_model import GLOBAL_LLM, GLOBAL_VISION_LLM
from loguru import logger
from config.config import cfg
from utils.date_utils import get_previous_trading_date
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import io
import base64
from matplotlib.patches import Rectangle

class PriceMarketAkshare(DataSourceBase):
    def __init__(self):
        super().__init__("price_market_akshare")
        
    async def get_data(self, trigger_time: str) -> pd.DataFrame:
        try:
            df = self.get_data_cached(trigger_time)
            if df is not None:
                return df
            
            trade_date = get_previous_trading_date(trigger_time)     
            logger.info(f"获取 {trade_date} 的价格市场数据")

            llm_summary_dict = await self.get_llm_summary(trade_date)
            data = [{
                "title": f"{trade_date}:市场宏观数据汇总",
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
    
    def get_kline_data(self, trade_date: str) -> dict:
        """
        获取三大指数的K线数据
        """
        try:
            indices = {
                "000001.SH": {"symbol": "sh000001", "name": "上证指数"},
                "399006.SZ": {"symbol": "sz399006", "name": "创业板指"},
                "000688.SH": {"symbol": "sh000688", "name": "科创50"}
            }
            
            kline_data = {}
            
            for stock_code, info in indices.items():
                try:
                    # 获取指数历史数据
                    df = akshare_cached.run(
                        func_name="stock_zh_index_daily",
                        func_kwargs={"symbol": info["symbol"]},
                        verbose=False
                    )
                    
                    if df.empty:
                        logger.warning(f"{info['name']} 数据为空")
                        continue
                    
                    # 转换日期格式并筛选最近90天的数据
                    df['date'] = pd.to_datetime(df['date'])
                    target_date = datetime.strptime(trade_date, '%Y%m%d')
                    
                    filtered_df = df[df['date'] <= target_date].tail(90)
                    
                    if filtered_df.empty:
                        logger.warning(f"{info['name']} 无{trade_date}之前的数据")
                        continue
                    
                    # 转换为所需格式
                    data_list = []
                    for _, row in filtered_df.iterrows():
                        data_list.append({
                            'trade_date': row['date'].strftime('%Y%m%d'),
                            'open_price': float(row['open']),
                            'high_price': float(row['high']),
                            'low_price': float(row['low']),
                            'close_price': float(row['close']),
                            'trade_lots': int(row['volume'])
                        })
                    
                    kline_data[stock_code] = {
                        'name': info['name'],
                        'data': data_list
                    }
                    
                    logger.info(f"获取 {info['name']} K线数据成功，{len(data_list)} 条记录")
                    
                except Exception as e:
                    logger.error(f"获取 {info['name']} K线数据失败: {e}")
                    continue
            
            return kline_data
            
        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            return {}
    
    def get_current_day_data(self, trade_date: str) -> dict:
        """
        获取三大指数当日收盘数据
        """
        try:
            indices = {
                "000001.SH": {"symbol": "sh000001", "name": "上证指数"},
                "399006.SZ": {"symbol": "sz399006", "name": "创业板指"},
                "000688.SH": {"symbol": "sh000688", "name": "科创50"}
            }
            
            current_day_data = {}
            
            for stock_code, info in indices.items():
                try:
                    # 获取指数历史数据
                    df = akshare_cached.run(
                        func_name="stock_zh_index_daily",
                        func_kwargs={"symbol": info["symbol"]},
                        verbose=False
                    )
                    
                    if df.empty:
                        logger.warning(f"{info['name']} 数据为空")
                        continue
                    
                    # 转换日期格式并查找指定日期的数据
                    df['date'] = pd.to_datetime(df['date'])
                    target_date = datetime.strptime(trade_date, '%Y%m%d')
                    
                    # 查找指定日期的数据
                    target_row = df[df['date'] == target_date]
                    
                    if target_row.empty:
                        # 如果没有当日数据，取最近的一条数据
                        target_row = df[df['date'] <= target_date].tail(1)
                        if target_row.empty:
                            logger.warning(f"{info['name']} 无{trade_date}的数据")
                            continue
                    
                    row = target_row.iloc[0]
                    
                    # 计算涨跌幅（需要前一天的数据）
                    prev_row = df[df['date'] < row['date']].tail(1)
                    if not prev_row.empty:
                        prev_close = float(prev_row.iloc[0]['close'])
                        price_change = float(row['close']) - prev_close
                        price_change_rate = price_change / prev_close
                    else:
                        price_change = 0.0
                        price_change_rate = 0.0
                    
                    current_day_data[stock_code] = {
                        'name': info['name'],
                        'open_price': float(row['open']),
                        'high_price': float(row['high']),
                        'low_price': float(row['low']),
                        'close_price': float(row['close']),
                        'price_change': price_change,
                        'price_change_rate': price_change_rate,
                        'trade_amount': float(row['volume']) * float(row['close']),  # 估算成交额
                        'trade_lots': int(row['volume'])
                    }
                    
                    logger.info(f"获取 {info['name']} 当日数据成功")
                    
                except Exception as e:
                    logger.error(f"获取 {info['name']} 当日数据失败: {e}")
                    continue
            
            return current_day_data
            
        except Exception as e:
            logger.error(f"获取当日数据失败: {e}")
            return {}
    
    def get_sector_summary(self, trade_date: str) -> str:
        """
        获取板块资金流向摘要
        """
        try:
            # 获取板块资金流向数据
            df = akshare_cached.run(
                func_name="stock_board_industry_name_em",
                func_kwargs={},
                verbose=False
            )
            
            if df.empty:
                return "无板块资金流向数据"
            
            summary_lines = [f"{trade_date} 板块资金流向情况（东方财富数据）：\n"]
            
            # 取前10个板块
            top_sectors = df.head(10)
            
            for _, row in top_sectors.iterrows():
                try:
                    sector_name = row['板块名称']
                    latest_price = row['最新价']
                    change_amount = row['涨跌额']
                    change_rate = row['涨跌幅']
                    market_cap = row['总市值'] / 100000000  # 转换为亿元
                    turnover_rate = row['换手率']
                    up_count = row['上涨家数']
                    down_count = row['下跌家数']
                    leading_stock = row['领涨股票']
                    leading_change = row['领涨股票-涨跌幅']
                    
                    change_sign = "+" if change_amount >= 0 else ""
                    rate_sign = "+" if change_rate >= 0 else ""
                    
                    summary_lines.append(
                        f"**{sector_name}**: 最新价 {latest_price:.2f}, "
                        f"涨跌 {change_sign}{change_amount:.2f} ({rate_sign}{change_rate:.2f}%), "
                        f"总市值 {market_cap:.0f}亿, 换手率 {turnover_rate:.2f}%, "
                        f"上涨 {up_count} 下跌 {down_count}, 领涨股 {leading_stock} ({leading_change:+.2f}%)"
                    )
                except Exception as e:
                    logger.warning(f"处理板块数据行失败: {e}")
                    continue
            
            return "\n".join(summary_lines)
            
        except Exception as e:
            logger.error(f"获取板块资金流向失败: {e}")
            return f"获取板块资金流向失败: {str(e)}"
    
    def generate_kline_charts_base64(self, kline_data: dict, trade_date: str) -> dict:
        """
        生成三大指数K线图并返回base64编码字典
        """
        try:
            if not kline_data:
                logger.warning("K线数据为空，无法生成图表")
                return {}
            try:
                plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans', 'sans-serif']
                plt.rcParams['axes.unicode_minus'] = False
            except:
                pass
            
            charts_base64 = {}
            
            for stock_code, stock_info in kline_data.items():
                stock_name = stock_info['name']
                data_list = stock_info['data']
                
                if not data_list:
                    logger.warning(f"{stock_name}数据不可用，跳过图表生成")
                    continue
                
                fig, ax = plt.subplots(1, 1, figsize=(12, 8))
                
                fig.patch.set_facecolor('white')
                ax.set_facecolor('white')
                
                df_data = []
                for item in data_list:
                    df_data.append({
                        'date': datetime.strptime(str(item['trade_date']), '%Y%m%d'),
                        'open': item['open_price'],
                        'high': item['high_price'],
                        'low': item['low_price'],
                        'close': item['close_price'],
                        'volume': item['trade_lots']
                    })
                
                df = pd.DataFrame(df_data)
                df = df.sort_values('date')
                
                x_positions = np.arange(len(df))
                
                # 绘制K线
                for j in range(len(df)):
                    open_price = df.iloc[j]['open']
                    high_price = df.iloc[j]['high']
                    low_price = df.iloc[j]['low']
                    close_price = df.iloc[j]['close']
                    
                    if close_price >= open_price:
                        color = '#ff6b6b'  # 上涨红色
                        edge_color = '#ff6b6b'
                    else:
                        color = '#51cf66'  # 下跌绿色
                        edge_color = '#51cf66'
                    
                    ax.plot([j, j], [low_price, high_price], color=edge_color, linewidth=1, alpha=0.8)
                    
                    body_height = abs(close_price - open_price)
                    body_bottom = min(open_price, close_price)
                    
                    if body_height > 0:
                        rect = Rectangle((j - 0.3, body_bottom), 0.6, body_height, 
                                       facecolor=color, edgecolor=edge_color, alpha=0.8, linewidth=0.8)
                        ax.add_patch(rect)
                    else:
                        ax.plot([j, j], [open_price, close_price], color=edge_color, linewidth=2, alpha=0.8)
                
                # 添加移动平均线
                if len(df) >= 5:
                    ma5 = df['close'].rolling(window=5).mean()
                    ax.plot(x_positions, ma5, color='#ffa500', linewidth=1.5, alpha=0.8, label='MA5')
                
                if len(df) >= 10:
                    ma10 = df['close'].rolling(window=10).mean()
                    ax.plot(x_positions, ma10, color='#ff69b4', linewidth=1.5, alpha=0.8, label='MA10')
                
                if len(df) >= 20:
                    ma20 = df['close'].rolling(window=20).mean()
                    ax.plot(x_positions, ma20, color='#4169e1', linewidth=1.5, alpha=0.8, label='MA20')
                
                ax.set_title(f'{stock_name} K线图 - {trade_date}', fontsize=14, fontweight='bold')
                ax.set_ylabel('价格 (点)', fontsize=12)
                ax.set_xlabel('日期', fontsize=12)
                ax.grid(True, alpha=0.3)
                ax.legend(loc='upper left', fontsize=10)
                
                if len(df) > 0:
                    step = max(1, len(df) // 8)
                    tick_positions = list(range(0, len(df), step))
                    tick_labels = [df.iloc[i]['date'].strftime('%m-%d') for i in tick_positions if i < len(df)]
                    
                    ax.set_xticks(tick_positions)
                    ax.set_xticklabels(tick_labels, rotation=45, fontsize=10)
                
                plt.tight_layout()
                
                buf = io.BytesIO()
                plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
                buf.seek(0)
                img_base64 = base64.b64encode(buf.read()).decode('utf-8')
                plt.close(fig)
                
                charts_base64[stock_code] = {
                    'name': stock_name,
                    'base64': img_base64
                }
                
                logger.info(f"成功生成{stock_name}K线图，大小: {len(img_base64)} 字符")
            
            logger.info(f"成功生成{len(charts_base64)}张K线图")
            return charts_base64
            
        except Exception as e:
            logger.error(f"生成K线图失败: {e}")
            return {}
    
    async def get_llm_summary(self, trade_date: str) -> dict:
        try:
            logger.info(f"获取 {trade_date} 的价格市场LLM分析总结")
            
            # 获取K线数据
            kline_data = self.get_kline_data(trade_date)
            
            # 获取当日数据
            current_day_data = self.get_current_day_data(trade_date)
            
            # 获取板块资金流向摘要
            sector_summary = self.get_sector_summary(trade_date)
            
            # 生成K线图
            kline_charts_base64 = self.generate_kline_charts_base64(kline_data, trade_date)
            
            has_kline_charts_base64 = bool(kline_charts_base64)
            has_current_day_data = bool(current_day_data)
            has_sector_summary = bool(sector_summary and sector_summary != "无板块资金流向数据")

            available_sources = has_kline_charts_base64 + has_current_day_data + has_sector_summary
            
            if available_sources == 0:
                return {
                    'trade_date': trade_date,
                    'raw_data': "无数据",
                    'llm_summary': "当日无价格市场数据",
                    'data_count': 0,
                    'kline_charts_base64': {}
                }
            
            prompt = f"""
请分析以下{trade_date}的A股市场综合数据，并给出专业的宏观市场分析报告（2000字符以内）：

## 一、三大指数当日收盘情况
{self._format_current_day_data(current_day_data, trade_date)}

## 二、板块资金流向
{sector_summary}

## 三、三大指数K线图分析（如果有提供K线图）
请仔细分析提供的三张K线图（上证指数、创业板指、科创50），关注：
- 近期走势趋势（上涨/下跌/震荡）
- 技术指标表现（MA5、MA10、MA20均线）
- 成交量变化特征
- 支撑阻力位情况

## 分析要求

请综合以上信息和K线图，客观描述市场宏观基本面事实：

## 输出要求
- 总结所参考的三大指数收盘情况、K线图技术分析和板块资金流向数据（东方财富），并给出当日宏观市场的整体描述
- **对于当日三大指数的收盘价格必须精确到具体点位，不可模糊描述**
- 基于K线图分析技术面特征和趋势
- 避免主观判断、情绪化描述和未来预测
- 重点突出宏观的客观基本面事实描述
- **请把输出的宏观描述严格控制在2000字符以内，不要超过2000字符**

请基于事实数据生成客观的市场描述报告：
"""
            
            if GLOBAL_VISION_LLM and has_kline_charts_base64:
                image_contents = []
                for stock_code, chart_info in kline_charts_base64.items():
                    image_contents.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{chart_info['base64']}",
                            "detail": "high"
                        }
                    })
                user_message = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt}
                    ] + image_contents
                }
                
                messages = [
                    {"role": "system", "content": "你是一位资深的金融市场分析师，专长于综合技术分析、资金流向分析和宏观市场判断。请基于多维度数据生成专业的市场分析报告。"},
                    user_message
                ]
                
                response = await GLOBAL_VISION_LLM.a_run(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=2000
                )
            else:
                user_message = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt}
                    ]
                }
                
                messages = [
                    {"role": "system", "content": "你是一位资深的金融市场分析师，专长于综合技术分析、资金流向分析和宏观市场判断。请基于多维度数据生成专业的市场分析报告。"},
                    user_message
                ]
                response = await GLOBAL_LLM.a_run(
                    messages=messages,
                    thinking=False,
                    temperature=0.3,
                    max_tokens=2000
                )
            
            if response and response.content:
                llm_summary = response.content
            else:
                logger.error(f"LLM分析未返回内容")
                llm_summary = "LLM分析失败"
            
            return {
                'trade_date': trade_date,
                'raw_data': prompt,
                'llm_summary': llm_summary,
                'data_count': available_sources,
                'data_sources': {
                    'kline_data': has_kline_charts_base64,
                    'current_day_data': has_current_day_data,
                    'sector_summary': has_sector_summary
                }
            }
                
        except Exception as e:
            traceback.print_exc()
            logger.error(f"获取LLM总结失败: {e}")
            return {
                'trade_date': trade_date,
                'raw_data': "数据获取失败",
                'llm_summary': f"分析失败: {str(e)}",
                'data_count': 0
            }
    
    def _format_current_day_data(self, current_day_data: dict, trade_date: str) -> str:
        if not current_day_data:
            return f"{trade_date} 无三大指数当日数据"
        
        descriptions = []
        
        for stock_code, data in current_day_data.items():
            change_sign = "+" if data['price_change'] >= 0 else ""
            rate_sign = "+" if data['price_change_rate'] >= 0 else ""
            
            desc = f"**{data['name']}** (代码: {stock_code})\n"
            desc += f"- 收盘价: {data['close_price']:.2f}点\n"
            desc += f"- 开盘价: {data['open_price']:.2f}点\n"
            desc += f"- 最高价: {data['high_price']:.2f}点\n"
            desc += f"- 最低价: {data['low_price']:.2f}点\n"
            desc += f"- 涨跌幅: {change_sign}{data['price_change']:.2f}点 ({rate_sign}{data['price_change_rate']*100:.2f}%)\n"
            desc += f"- 成交额: {data['trade_amount']/100000000:.1f}亿元\n"
            desc += f"- 成交量: {data['trade_lots']/10000:.0f}万手"
            
            descriptions.append(desc)
        
        return f"{trade_date}三大指数收盘情况：\n\n" + "\n\n".join(descriptions)

if __name__ == "__main__":
    price_market = PriceMarketAkshare()
    df = asyncio.run(price_market.get_data("2024-08-19 09:00:00"))
    print(df.content.values[0])
