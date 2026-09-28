# Tool 参考：`a_share_hot_money`

## 基本信息

| 项 | 值 |
|---|---|
| `service_name` | `a_share_analysis` |
| `tool_name` | `a_share_hot_money` |
| 功能 | 获取 A 股热钱资金流向分析 |
| 对应 Data Agent | `hot_money_agent` |
| 本地 Data Source | `contest_trade/data_source/hot_money_akshare.py` |

## 本地 SSE 地址

```text
http://127.0.0.1:8000/server/mcp/a_share_analysis/sse
```

## 输入参数

`trigger_time` 固定为当前调用时间，不支持历史回测。大盘/热钱类 Tool 会自动取上一个交易日。

CLI 调用时不传参数：

```bash
python scripts/cli.py a_share_hot_money
```

## 返回结构

```json
{
  "success": true,
  "count": 1,
  "data": [
    {
      "title": "20260924:热钱市场数据汇总",
      "content": "**20260924 热钱市场活跃度分析报告**...",
      "pub_time": "2026-09-28 15:38:35",
      "url": null
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `success` | bool | 是否成功 |
| `count` | int | 固定为 1 |
| `data[0].content` | string | LLM 生成的热钱分析报告 |

## 数据源

| akshare 接口 | 内容 |
|---|---|
| `stock_zt_pool_em` | 涨停股 |
| `stock_zt_pool_dtgc_em` | 跌停股 |
| `stock_lhb_detail_em` | 龙虎榜明细 |
| `stock_lhb_jgmmtj_em` | 机构买卖统计 |
| `stock_board_concept_name_em` | 概念板块资金流 |
| `stock_lh_yyb_capital` | 游资营业部资金 |

## 常见失败与排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 概念板块数据获取失败 | akshare 接口连接中断 | 其他数据源通常可用，LLM 会基于已有数据生成摘要 |
| 龙虎榜当日上榜为 0 | 数据披露时点或交易结算因素 | 报告中说明“可能因披露时点导致”，不代表游资缺席 |
| 连接失败 | 本地 MCP 服务未启动 | 先运行 `python local_mcp_server.py` |

## 与相近 Tool 的区分

- `a_share_market_overview`：大盘指数和板块资金，不是短线情绪
- `sina_news_summary` / `thx_news_summary`：新闻类，不是资金类
