# Tool 参考：`thx_news_summary`

## 基本信息

| 项 | 值 |
|---|---|
| `service_name` | `a_share_analysis` |
| `tool_name` | `thx_news_summary` |
| 功能 | 获取同花顺股票资讯摘要 |
| 对应 Data Agent | `thx_summary_agent` |
| 本地 Data Source | `contest_trade/data_source/thx_news_crawl.py` |

## 本地 SSE 地址

```text
http://127.0.0.1:8000/server/mcp/a_share_analysis/sse
```

## 输入参数

`trigger_time` 固定为当前调用时间，不支持历史回测。

CLI 调用时不传参数：

```bash
python scripts/cli.py thx_news_summary
```

## 返回结构

```json
{
  "success": true,
  "count": 446,
  "data": [
    {
      "title": "...",
      "content": "...",
      "pub_time": "2026-09-28 15:38:35",
      "url": "https://stock.10jqka.com.cn/..."
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
| API 通道返回 0 条 | 同花顺 API 接口临时失效或被反爬 | 前端通道会兜底，通常仍有数据 |
| crawl4ai 超时 | 前端页面加载慢或被拦截 | 等待后重试，或换时间重试 |
| 连接失败 | 本地 MCP 服务未启动 | 先运行 `python local_mcp_server.py` |

## 与相近 Tool 的区分

- `sina_news_summary`：新浪财经新闻，覆盖更偏宏观/政策
- `thx_news_summary`：同花顺资讯，更偏个股/公司/板块
