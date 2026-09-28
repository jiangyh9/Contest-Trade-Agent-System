# Tool 参考：`a_share_market_overview`

## 基本信息

| 项 | 值 |
|---|---|
| `service_name` | `a_share_analysis` |
| `tool_name` | `a_share_market_overview` |
| 功能 | 获取 A 股大盘走势分析 |
| 对应 Data Agent | `price_market_agent` |
| 本地 Data Source | `contest_trade/data_source/price_market_akshare.py` |

## 本地 SSE 地址

```text
http://127.0.0.1:8000/server/mcp/a_share_analysis/sse
```

## 输入参数

`trigger_time` 固定为当前调用时间，不支持历史回测。大盘/热钱类 Tool 会自动取上一个交易日。

CLI 调用时不传参数：

```bash
python scripts/cli.py a_share_market_overview
```

## 返回结构

```json
{
  "success": true,
  "count": 1,
  "data": [
    {
      "title": "20260924:市场大盘数据汇总",
      "content": "# 2026年9月24日A股市场宏观分析报告...",
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
| `data[0].content` | string | LLM 生成的大盘走势分析文本 |

## 数据源

- `stock_zh_index_daily`：上证指数、创业板指、科创50
- `stock_board_industry_name_em`：东方财富行业板块资金流向

## 常见失败与排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 板块资金流向获取失败 | akshare 接口连接中断 | K线数据通常仍可用，LLM 会基于已有数据生成摘要 |
| 非交易日返回旧日期 | 自动取上一个交易日 | 正常行为，在报告中说明实际交易日 |
| 连接失败 | 本地 MCP 服务未启动 | 先运行 `python local_mcp_server.py` |

## 与相近 Tool 的区分

- `a_share_hot_money`：偏短线资金和游资，不是大盘指数分析
- `sina_news_summary` / `thx_news_summary`：新闻类，不是行情类
