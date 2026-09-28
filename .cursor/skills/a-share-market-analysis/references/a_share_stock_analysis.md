# Tool 参考：`a_share_stock_analysis`

## 基本信息

| 项 | 值 |
|---|---|
| `service_name` | `a_share_analysis` |
| `tool_name` | `a_share_stock_analysis` |
| 功能 | 对指定 A 股做利好/利空对照分析，不给投资建议 |
| 本地 SSE | `http://127.0.0.1:8000/server/mcp/a_share_analysis/sse` |

## 输入参数

| 字段 | 说明 |
|---|---|
| `symbol` | 股票代码或名称，如 `600519`、`600519.SH`、`贵州茅台` |
| `trigger_time` | 由 CLI 填入当前时间，不支持历史回测 |

```bash
python scripts/cli.py a_share_stock_analysis 600519
python scripts/cli.py a_share_stock_analysis 贵州茅台
```

缺标的时不要猜测，先向用户确认。

## background 从哪来

Tool **内部自己拼**，不依赖用户先跑综合分析，也不使用投资信念。

1. 并发调用本 Skill 已有 4 个能力：新浪新闻、同花顺资讯、大盘走势、热钱资金。
2. 这 4 路 Data Source 都带按 `trigger_time` 的缓存：同一时刻如果已经跑过市场分析，个股 Tool 会直接复用，不会重复爬。
3. 再并行取该股数据：K线、实时行情、技术指标、分时资金、财务、个股新闻。
4. 把「市场背景 + 个股数据」交给 Skill 专用 LLM，只做利好/利空对照。

结构等价于原来 Research Agent 的 `background_information`，但去掉 `<your_belief>`。

## 返回结构

```json
{
  "success": true,
  "count": 1,
  "data": [
    {
      "title": "贵州茅台(600519.SH) 个股分析",
      "content": "# 贵州茅台 分析（...）\n\n## 一、标的与市场背景\n...",
      "pub_time": "2026-09-28 17:40:00",
      "url": null
    }
  ]
}
```

## 输出约束

- 必须同时有利好、利空
- 禁止买入/卖出/看多/看空/目标价/仓位等建议
- 支撑阻力只能当技术事实，不当操作位

## 常见失败

| 现象 | 处理 |
|---|---|
| 无法解析股票 | 让用户改成 6 位代码或准确名称 |
| 市场摘要部分失败 | 报告里写入“待观察”，不编造 |
| 连接失败 | 先启动 `python local_mcp_server.py` |
