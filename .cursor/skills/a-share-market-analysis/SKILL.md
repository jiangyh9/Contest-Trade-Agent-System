---
name: a-share-market-analysis
description: >-
  从宏观新闻、股票相关资讯、大盘走势和资金流向来对 A 股市场进行综合分析。
disable-model-invocation: true
---

# A 股市场综合分析

> 🚨 本 Skill 通过 `scripts/cli.py` 调用本地 MCP SSE 服务取数，禁止手写裸请求。
>
> 📁 运行位置：Skill 根目录（`~/.cursor/skills/a-share-market-analysis/`）。
>
> 🔑 本地测试时先启动 `local_mcp_server.py`。

## 一句话能力

整合新浪财经新闻、同花顺资讯、A 股大盘走势、热钱资金流向 4 类数据，生成 A 股市场综合分析报告。

## 何时使用

### ✅ 触发场景

- “A股市场综合分析”
- “今天A股怎么样”
- “汇总下市场数据、新闻和资金流向”
- “看看大盘、热点、龙虎榜”
- “新闻/资讯” / “最近有什么财经新闻”
- “大盘走势分析” / “热钱资金流向”

### ❌ 不触发场景

- 个股诊断、个股财报分析（应使用 `individual_stock_research` 类工具）
- 美股、港股分析（应使用 US Market 相关 Skill）
- 纯概念解释、常识问答（不调用 MCP）

## 快速调用

**步骤 1**：启动本地 MCP 服务

```bash
cd /Users/jiangyueheng/Downloads/ContestTrade
python local_mcp_server.py
```

**步骤 2**：调用 Tool

```bash
# 新闻/资讯（同时调用新浪 + 同花顺）
python scripts/cli.py sina_news_summary
python scripts/cli.py thx_news_summary

# 大盘走势
python scripts/cli.py a_share_market_overview

# 热钱资金流向
python scripts/cli.py a_share_hot_money

# 综合分析：上面 4 个一起调
```

## MCP 服务与 Tool

| 项 | 值 |
|---|---|
| `service_name` | `a_share_analysis` |
| 本地 SSE | `http://127.0.0.1:8000/server/mcp/a_share_analysis/sse` |

| Tool 名称 | 功能 | 对应原 Data Agent |
|---|---|---|
| `sina_news_summary` | 新浪财经新闻摘要 | `sina_summary_agent` |
| `thx_news_summary` | 同花顺股票资讯摘要 | `thx_summary_agent` |
| `a_share_market_overview` | A 股大盘走势分析 | `price_market_agent` |
| `a_share_hot_money` | A 股热钱资金流向分析 | `hot_money_agent` |

每个 Tool 的详细参数、返回结构、失败排查见 `references/` 目录：

- [`references/sina_news_summary.md`](references/sina_news_summary.md)
- [`references/thx_news_summary.md`](references/thx_news_summary.md)
- [`references/a_share_market_overview.md`](references/a_share_market_overview.md)
- [`references/a_share_hot_money.md`](references/a_share_hot_money.md)

4 个 Data Source 的本地实现细节见 [`references/data_sources.md`](references/data_sources.md)。

## 执行工作流

### 步骤 1：判断用户意图

根据用户问题，决定调用哪些 Tool：

| 用户意图 | 调用的 Tool |
|---|---|
| “新闻” / “资讯” / “财经新闻” | 同时调用 `sina_news_summary` + `thx_news_summary` |
| “大盘走势” / “市场走势” | 仅 `a_share_market_overview` |
| “热钱” / “龙虎榜” / “资金流向” | 仅 `a_share_hot_money` |
| “综合分析” / “今天A股怎么样” | 同时调用 4 个 Tool |

### 步骤 2：调用 Tool

对每个选定的 Tool 执行：

```bash
python scripts/cli.py <tool_name>
```

`trigger_time` 固定为当前提问/调用时间，不支持历史回测。大盘/热钱类 Tool 会自动取上一个交易日。

### 步骤 3：解析结果

`cli.py` 输出为 JSON：

```json
{
  "success": true,
  "count": 1052,
  "data": [
    {"title": "...", "content": "...", "pub_time": "...", "url": "..."}
  ]
}
```

- 新闻类 Tool：`count` 可能大于 1
- 大盘/热钱类 Tool：`count` 通常为 1，`content` 是 LLM 生成的分析文本

### 步骤 4：合并输出报告

把 4 个 Tool 的结果按以下结构合并，再交给 LLM 做一次最终统稿：

```markdown
# A 股市场综合分析报告（{trade_date}）

## 一、市场概述
用 1-2 句话总结当天 A 股整体状态。

## 二、宏观政策与行业新闻
整合新浪 + 同花顺摘要。

## 三、大盘走势
引用 `a_share_market_overview` 的 LLM 摘要。

## 四、板块与资金流向
引用 `a_share_hot_money` 的 LLM 摘要。

## 五、热点与短线情绪
从 `a_share_hot_money` 里提炼涨停、龙虎榜、游资、概念板块信息。

## 六、综合判断与关注点
结合以上四点，给出 3-5 条核心判断。
```

## 输出要求

最终输出应为一份 Markdown 格式的中文分析报告，包含：

1. **报告标题**：A 股市场综合分析报告（日期）
2. **数据时间**：当前提问/调用时间，以及大盘/热钱的实际交易日
3. **市场概述**：1-2 句话核心判断
4. **新闻摘要**：宏观政策与行业新闻 + 股票资讯
5. **大盘走势**：指数、成交额、技术指标
6. **资金流向**：板块、游资、龙虎榜
7. **热点板块与个股**：概念热度、涨停/跌停概况
8. **风险提示**：数据延迟、市场情绪变化等

## 注意事项

| 情况 | 处理 |
|---|---|
| 本地服务未启动 | 提示用户先运行 `python local_mcp_server.py` |
| 新闻类 Tool 返回 `count: 0` | 可能是非交易时间，提示“新闻数据为空” |
| 大盘/热钱类 Tool 失败 | 依赖 akshare，可能是接口升级或网络问题 |
| 缺参 | 不要凭印象瞎填，先向用户确认 |

## 响应前自查

- [ ] 用户意图已明确，知道该调哪几个 Tool
- [ ] `scripts/cli.py` 命令中的 tool 名称正确
- [ ] 本地服务已启动
- [ ] 返回结果已解析为 JSON
- [ ] 输出包含结论、关键数据、风险提示
