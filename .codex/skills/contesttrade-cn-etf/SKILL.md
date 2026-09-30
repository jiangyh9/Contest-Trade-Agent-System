---
name: contesttrade-cn-etf
description: Run China-listed ETF research from the local ContestTrade-ETF workspace using WindDB data, deterministic factor calculation, four independent strategy roles, and cross-strategy review. Use when the user asks to scan, analyze, rank, backtest, or report on China exchange-listed stock, bond, commodity, money-market, or multi-asset ETFs. Do not use for US-listed ETFs or individual stocks.
---

# ContestTrade China ETF

Run inside the `ContestTrade-ETF` repository. Python owns retrieval and calculations; Codex owns research judgment. Do not call `GLOBAL_LLM`, `LLM`, `LLM_THINKING`, `VLM`, or an external model API.

## Workflow

1. Resolve the analysis date. Default to the latest completed China trading day. For historical work, use only data available on or before the requested date.
2. Run the bundled factor script with the repository's `contesttrade` Conda Python:

   ```bash
   /Users/jiangyueheng/miniconda3/envs/contesttrade/bin/python \
     .codex/skills/contesttrade-cn-etf/scripts/build_factor_pack.py \
     --project-root . --as-of YYYY-MM-DD
   ```

   The script reads WindDB with `SELECT` statements only. If network access is blocked, request execution permission and rerun once. If Wind remains unavailable, report the failure; do not label the 23-item static fallback as full-market data.
3. Read the generated factor pack. Read [strategy roles](references/strategy-roles.md) whenever producing signals or a market report. Read [output schema](references/output-schema.md) when writing machine-readable results.
4. Analyze each strategy independently. Finish one strategy's selection and rejection reasons before considering another strategy's conclusions. Use only evidence in the factor pack or sources explicitly requested by the user.
5. Cross-review the outputs for duplicate exposure, conflicts, liquidity, concentration, and compliance with each strategy mandate. Do not invent portfolio allocation unless requested.
6. Write `signals.json` and `report.md` beside the generated `factor_pack.json` under `agents_workspace/codex_etf/<date>/`.
7. Present the report with the data cutoff, universe and category counts, material rejected candidates, and missing data.

## Constraints

- Keep `risk_profile` as the compatibility field for strategy source. Allowed values: `强势动量`, `趋势确认`, `防御轮动`, `反转修复`.
- Recommend no more than three ETFs per strategy. Fewer or zero is valid.
- Require liquidity and at least two independent supporting observations from the factor pack. A high rank alone is insufficient.
- Distinguish commodity ETFs from equity ETFs holding commodity-related companies.
- Compare momentum primarily within asset class. Use cross-asset ranks for regime interpretation.
- This workflow produces research, not trade execution.

## Modes

- **Daily scan:** four strategy outputs plus cross-review.
- **Single strategy:** apply only the requested strategy section.
- **Historical review:** set `--as-of`; label current-master survivorship limitations.
- **Factor-only:** summarize deterministic factors without investment judgment.
