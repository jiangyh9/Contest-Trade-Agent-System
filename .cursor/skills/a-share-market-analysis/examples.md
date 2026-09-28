# A 股市场综合分析 - 使用示例

## 示例 1：直接生成当日综合分析报告

### 用户请求

> “帮我做一下今天的 A 股市场综合分析。”

### Agent 执行步骤

```bash
# 1. 确保本地 MCP 服务已启动
# cd /Users/jiangyueheng/Downloads/ContestTrade
# python local_mcp_server.py

# 2. 并发调用 4 个 Tool
python scripts/cli.py sina_news_summary
python scripts/cli.py thx_news_summary
python scripts/cli.py a_share_market_overview
python scripts/cli.py a_share_hot_money

# 3. 合并 4 个 Tool 的输出，生成综合分析报告
```

> 注意：`trigger_time` 固定为当前调用时间，不支持历史回测。

### 预期输出片段

```markdown
# A 股市场综合分析报告（2026-09-28）

## 一、市场概述
今日 A 股整体呈现震荡走势，三大指数小幅收涨，成交额较前一日略有放大。

## 二、宏观政策与行业新闻
- 央行公开市场开展 1000 亿元逆回购操作
- 工信部发布新能源汽车产业新规划
- 消费电子板块受新品发布催化

## 三、大盘走势
上证指数收于 3200 点附近，创业板相对强势。技术指标显示短期处于震荡整理区间，
MA5 与 MA10 粘合，需关注后续方向选择。

## 四、板块与资金流向
- 资金净流入前三大板块：半导体、通信设备、汽车零部件
- 机构净买入约 15 亿元，主要布局科技和新能源
- 游资营业部活跃度提升，主要参与题材炒作

## 五、热点与短线情绪
- 涨停 58 只，跌停 3 只，短线情绪回暖
- 热门概念：光刻胶、机器人、低空经济
- 龙虎榜显示多家知名游资介入科技股

## 六、综合判断与关注点
1. 市场情绪偏暖，但上方仍有压力
2. 科技成长方向资金关注度较高
3. 关注成交量能否持续放大
4. 留意政策面对新能源、半导体的进一步催化
5. 短线注意高位题材股分化风险
```

---

## 示例 2：只想要新闻/资讯

### 用户请求

> “最近有什么 A 股新闻？”

### Agent 执行步骤

不区分新浪和同花顺，同时调用两个新闻 Tool：

```bash
python scripts/cli.py sina_news_summary
python scripts/cli.py thx_news_summary
```

然后合并两个 Tool 的新闻列表，按 `pub_time` 排序，生成新闻摘要。

### 关键说明

- 新浪新闻更偏宏观/政策/国际市场
- 同花顺新闻更偏个股/板块/公司动态
- 合并后可以互补覆盖

---

## 示例 3：只想要资金流向和热点

### 用户请求

> “今天 A 股热钱和概念板块怎么样？”

### Agent 处理方式

不需要完整跑 4 个 Tool，只调用：

```bash
python scripts/cli.py a_share_hot_money
```

输出为 `a_share_hot_money` 生成的热钱分析报告，包含涨跌停、龙虎榜、机构、概念板块、游资营业部 5 个部分。
