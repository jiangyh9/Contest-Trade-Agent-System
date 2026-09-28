# A 股市场综合分析 Skill

从宏观新闻、股票相关资讯、大盘走势和资金流向分析 A 股市场；也可对指定个股做利好/利空对照。只做分析，不给投资建议。

Skill 目录：`~/.cursor/skills/a-share-market-analysis/`  
MCP 服务：项目根目录的 `local_mcp_server.py`

---

## 能做什么

| 你问什么 | 实际调用 |
|---|---|
| 今天 A 股怎么样 / 综合分析 | 新浪新闻 + 同花顺资讯 + 大盘 + 热钱 |
| 最近有什么财经新闻 | 新浪 + 同花顺 |
| 大盘走势怎么样 | 仅大盘 |
| 热钱 / 龙虎榜 / 资金流向 | 仅热钱 |
| 分析一下茅台 / 600519 | 个股利好/利空（内部会自己拼市场背景） |

不支持：历史回测、美股港股、买入卖出/目标价/仓位建议。

---

## 使用前

先在一个终端里启动本地 MCP（不要关）：

```bash
cd /Users/jiangyueheng/Downloads/ContestTrade
python local_mcp_server.py
```

服务地址：`http://127.0.0.1:8000/server/mcp/a_share_analysis/sse`

在 Cursor 对话里：

```text
/a-share-market-analysis 今天A股怎么样？
/a-share-market-analysis 分析一下贵州茅台
```

---

## Tool 一览

| Tool | 作用 | CLI |
|---|---|---|
| `sina_news_summary` | 新浪财经新闻摘要（最新 50 条再 LLM 总结） | `python scripts/cli.py sina_news_summary` |
| `thx_news_summary` | 同花顺资讯摘要 | `python scripts/cli.py thx_news_summary` |
| `a_share_market_overview` | 大盘走势（上证/创业板/科创50，近 90 日 K 线 + 上一交易日收盘） | `python scripts/cli.py a_share_market_overview` |
| `a_share_hot_money` | 涨跌停、龙虎榜、游资、概念热度 | `python scripts/cli.py a_share_hot_money` |
| `a_share_stock_analysis` | 个股利好/利空对照，不给投资建议 | `python scripts/cli.py a_share_stock_analysis 600519` |

新闻不区分新浪/同花顺：用户说“新闻/资讯”时两个一起调。

---

## 个股分析怎么拼 background

用户只需给代码或名称。Tool 内部并行：

1. 市场背景：新浪、同花顺、大盘、热钱（Data Source 按当前时间缓存，刚跑过综合分析会复用）
2. 个股数据：K 线、实时行情、技术指标、分时资金、财务、个股新闻
3. 用 Skill 专用 LLM 写成利好 / 利空 / 待观察，禁止买卖建议

没有投资信念（belief），也不做看多/看空评级。

---

## 时间口径

- 触发时间固定为**当前提问时间**，不能指定历史日期
- 新闻：当前时间往前 1 天
- 大盘/热钱：自动取**上一个交易日**；K 线看该日之前约 90 个交易日

---

## LLM 用哪套

| 场景 | 模型 |
|---|---|
| 本地 CLI / 项目里的 Data Agent | `config.yaml` 里你自己的 API |
| 本 Skill 的新闻摘要、个股分析 | `local_mcp_server.py` 里的公司测试网关 `internal-qwen3.6-35b-a3b` |

大盘、热钱内部仍可能走 `config.yaml` 的 `GLOBAL_LLM`。

---

## 目录

```text
a-share-market-analysis/
├── README.md
├── SKILL.md                 # Agent 执行说明
├── skill.yml
├── requirements.txt
├── examples.md
├── scripts/cli.py           # 调 MCP 的入口
└── references/              # 每个 Tool 一份说明
    ├── sina_news_summary.md
    ├── thx_news_summary.md
    ├── a_share_market_overview.md
    ├── a_share_hot_money.md
    ├── a_share_stock_analysis.md
    └── data_sources.md
```

项目里还有一份副本：`ContestTrade/.cursor/skills/a-share-market-analysis/`。

---

## 注意

- MCP 没启动时，CLI 会报连接失败
- 个股分析第一次较慢（约数分钟），因为要拉市场背景和个股数据
- 部分 akshare / 东方财富接口可能中断，报告会写进“待观察”，不编造数据
- 本 Skill 输出仅供分析，不构成投资建议
