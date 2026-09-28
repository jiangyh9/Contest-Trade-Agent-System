# Tool 参考：`sina_news_summary`

## 基本信息

| 项 | 值 |
|---|---|
| `service_name` | `a_share_analysis` |
| `tool_name` | `sina_news_summary` |
| 功能 | 获取新浪财经新闻摘要 |
| 对应 Data Agent | `sina_summary_agent` |
| 本地 Data Source | `contest_trade/data_source/sina_news_crawl.py` |

## 本地 SSE 地址

```text
http://127.0.0.1:8000/server/mcp/a_share_analysis/sse
```

## 输入参数

`trigger_time` 固定为当前调用时间，不支持历史回测。

CLI 调用时不传参数：

```bash
python scripts/cli.py sina_news_summary
```

## 返回结构

```json
{
  "success": true,
  "count": 1083,
  "data": [
    {
      "title": "...",
      "content": "...",
      "pub_time": "2026-09-28 16:23:27",
      "url": "https://finance.sina.com.cn/..."
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `success` | bool | 是否成功 |
| `count` | int | 新闻条数 |
| `data` | list | 每条新闻的 `title/content/pub_time/url` |

## 常见失败与排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `count: 0` | 非交易时间或新闻窗口内无数据 | 换一个时间重试 |
| 部分请求失败 | 新浪 JSONP 解析或正文页补全失败 | 多页抓取有容错，通常仍能返回部分数据 |
| 连接失败 | 本地 MCP 服务未启动 | 先运行 `python local_mcp_server.py` |

## 与相近 Tool 的区分

- `thx_news_summary`：同花顺股票资讯，来源不同
- `a_share_market_overview`：大盘走势，不是新闻
- `a_share_hot_money`：热钱资金，不是新闻
