# Output schema

Write `signals.json` as UTF-8 JSON:

```json
{
  "as_of_date": "YYYY-MM-DD",
  "data_cutoff": "YYYY-MM-DD",
  "universe": {"total": 0, "by_asset_class": {}},
  "strategies": [
    {
      "strategy": "强势动量",
      "holding_period_days": 5,
      "market_view": "",
      "signals": [
        {
          "symbol_code": "510300.SH",
          "symbol_name": "",
          "action": "buy",
          "probability": 0,
          "evidence": [""],
          "limitations": [""],
          "invalidation": ""
        }
      ],
      "rejected_candidates": [{"symbol_code": "", "reason": ""}]
    }
  ],
  "cross_review": {
    "duplicate_exposures": [],
    "conflicts": [],
    "data_limitations": []
  }
}
```

Use integer probability from 0 to 100. `buy` and `sell` are research directions, not execution instructions. Never add fields claiming orders, fills, or positions.
