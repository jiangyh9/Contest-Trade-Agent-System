# A 股市场综合分析 - 数据源参考

本文件详细说明 4 个 A 股 Data Source 的接口、字段和依赖。

---

## 1. 新浪财经新闻：`SinaNewsCrawl`

**文件**：`contest_trade/data_source/sina_news_crawl.py`

**数据源**：`http://feed.mix.sina.com.cn/api/roll/get`

**调用方式**：

```python
from contest_trade.data_source.sina_news_crawl import SinaNewsCrawl

df = SinaNewsCrawl().get_data("2026-09-28 09:30:00")
```

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | str | 新闻标题 |
| `content` | str | 新闻摘要/简介 |
| `pub_time` | str | 发布时间 `YYYY-MM-DD HH:MM:SS` |
| `url` | str | 原文链接 |

**抓取逻辑**：

- 每页 50 条，默认爬 50 页，约 2500 条
- JSONP 格式，需正则去掉 callback 包装
- 摘要过短或以 `…` 结尾时，会二次抓取正文页补全
- 过滤 `trigger_time` 前 1 天内的新闻

**依赖**：`aiohttp`, `BeautifulSoup`

**常见失败**：JSONP 解析异常、正文页被反爬返回空内容

---

## 2. 同花顺新闻：`ThxNewsCrawl`

**文件**：`contest_trade/data_source/thx_news_crawl.py`

**数据源**：

- API：`https://news.10jqka.com.cn/tapp/news/push/stock/`
- 前端网页：`stock.10jqka.com.cn/companynews_list/`、`/hsdp_list/`

**调用方式**：

```python
from contest_trade.data_source.thx_news_crawl import ThxNewsCrawl

df = ThxNewsCrawl().get_data("2026-09-28 09:30:00")
```

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | str | 新闻标题 |
| `content` | str | 摘要/导语 |
| `pub_time` | str | 发布时间 `YYYY-MM-DD HH:MM:SS` |
| `url` | str | 原文链接 |

**抓取逻辑**：

- API 通道：每页 400 条，默认 5 页，随机 1-3 秒延迟
- 前端通道：crawl4ai 爬取公司新闻 + 沪深动态，各 21 页
- API 和前端结果按 URL 去重合并
- 过滤 `trigger_time` 前 1 天内的新闻

**依赖**：`aiohttp`, `crawl4ai`

**常见失败**：crawl4ai 启动慢、前端页面结构变化导致解析失败

---

## 3. 大盘走势：`PriceMarketAkshare`

**文件**：`contest_trade/data_source/price_market_akshare.py`

**数据源**：akshare

- `stock_zh_index_daily`：上证指数、创业板指、科创50
- `stock_board_industry_name_em`：东方财富行业板块

**调用方式**：

```python
from contest_trade.data_source.price_market_akshare import PriceMarketAkshare

df = PriceMarketAkshare().get_data("2026-09-28 09:30:00")
content = df.content.values[0]
```

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | str | `{trade_date}:市场大盘数据汇总` |
| `content` | str | LLM 生成的市场大盘走势分析 |
| `pub_time` | str | 传入的 `trigger_time` |
| `url` | None | 无 |

**处理逻辑**：

- 取上一个交易日 `trade_date`
- 获取三大指数近 90 日 K线，计算 MA5/MA10/MA20
- 生成 K 线图并转 base64
- 获取板块资金流向 Top10
- 调用 Vision LLM 或普通 LLM 生成分析

**依赖**：`akshare`, `matplotlib`

**常见失败**：akshare 接口升级导致字段名变化、非交易日无数据

---

## 4. 热钱资金流：`HotMoneyAkshare`

**文件**：`contest_trade/data_source/hot_money_akshare.py`

**数据源**：akshare

- `stock_zt_pool_em`：涨停股
- `stock_zt_pool_dtgc_em`：跌停股
- `stock_lhb_detail_em`：龙虎榜明细
- `stock_lhb_jgmmtj_em`：机构买卖统计
- `stock_board_concept_name_em`：概念板块资金流
- `stock_lh_yyb_capital`：游资营业部资金

**调用方式**：

```python
from contest_trade.data_source.hot_money_akshare import HotMoneyAkshare

df = HotMoneyAkshare().get_data("2026-09-28 09:30:00")
content = df.content.values[0]
```

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | str | `{trade_date}:热钱市场数据汇总` |
| `content` | str | LLM 生成的热钱活跃度分析 |
| `pub_time` | str | 传入的 `trigger_time` |
| `url` | None | 无 |

**处理逻辑**：

- 取上一个交易日
- 分别获取 6 类数据
- 构造 5 段分析文本：涨跌停、龙虎榜、机构参与、概念板块、游资营业部
- 调用 LLM 生成最终摘要

**依赖**：`akshare`

**常见失败**：akshare 接口返回空表、非交易日无龙虎榜数据

---

## 缓存机制

所有 Data Source 继承自 `DataSourceBase`，缓存位置：

```
contest_trade/data_source/data_cache/
├── sina_news_crawl/
├── thx_news_crawl/
├── price_market_akshare/
└── hot_money_akshare/
```

缓存文件名：`{trigger_time.replace(' ', '_').replace(':', '-')}.pkl`

命中缓存时，`get_data` 会直接返回缓存 DataFrame，不会再调用外部接口。

---

## 合并摘要策略

新闻类数据通常有多行，需要分批合并：

```python
batch_size = 10
for i in range(0, len(news_df), batch_size):
    batch = news_df.iloc[i:i+batch_size]
    text = "\n\n".join(
        f"标题：{row.title}\n时间：{row.pub_time}\n摘要：{row.content}"
        for _, row in batch.iterrows()
    )
    # 调用 LLM 生成 batch 摘要
```

最后把所有 batch 摘要 + 大盘摘要 + 热钱摘要合并，调用一次最终统稿 LLM。
