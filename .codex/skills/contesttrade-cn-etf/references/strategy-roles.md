# Strategy roles

The numerical `screen_score` ranks candidates for review; it is not a recommendation.

## 强势动量

- Horizon: 5 trading days. Return source: short-term trend continuation.
- Prefer positive 5-day and 10-day returns, rising turnover, price above MA20, and positive benchmark-relative strength.
- Reject one-day spikes without confirmation, thin trading, and stale prices.

## 趋势确认

- Horizon: 10 trading days. Return source: persistence after medium-term confirmation.
- Prefer consistent 10-day/20-day returns, price above MA10 and MA20, controlled volatility, and stable liquidity.
- Reject sharp reversals, large drawdowns, and insufficient history.

## 防御轮动

- Horizon: 10 trading days. Return source: movement toward lower-risk assets when equity conditions deteriorate.
- Review bonds, qualifying commodities such as gold, money-market ETFs, multi-asset ETFs, and defensive or Smart Beta equity ETFs.
- Prefer low volatility and drawdown, non-negative relative strength, and reliable liquidity.
- Reject products whose realized risk conflicts with the defensive thesis.

## 反转修复

- Horizon: 5 trading days. Return source: mean reversion after measurable drawdown.
- Prefer negative 20-day return followed by improving 5-day return, recovery above MA5, stronger turnover, and reduced downside velocity.
- Reject accelerating downtrends, weak liquidity, and single-observation rebounds.

## Cross-strategy review

- Preserve each strategy's original reasoning.
- Flag duplicate tickers and correlated exposures; do not turn them into a portfolio unless requested.
- Allow overlap only when evidence independently satisfies both mandates, and explain it.
- Use 5-day evaluation for 强势动量/反转修复 and 10-day evaluation for 趋势确认/防御轮动.
