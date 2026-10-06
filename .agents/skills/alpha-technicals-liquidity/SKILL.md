---
name: alpha-technicals-liquidity
description: Use when evaluating price trends, momentum, volume profiles, options positioning, bid-ask depth, or market liquidity for a specified instrument and horizon.
---

# Technical & Liquidity Analysis

## Verify the market data

Require instrument/venue, timezone, bar interval, sample period, and OHLCV source. Check corporate actions, split-adjusted versus raw prices, futures roll treatment, missing bars and volume units. Indicator periods mean bars, not automatically days or investment horizons. Insufficient lookback means the indicator is unavailable.

Use 20 EMA, 50/200 SMA, RSI(14), MACD, ADX, Bollinger bands and ATR as selectable tools. State settings and smoothing convention. Compare trends, relative strength, momentum and volatility across timeframes. A squeeze implies compressed realized volatility; it does not establish breakout direction, option-market intent, or certain returns.

## Volume, order flow and options

Distinguish trade-level volume-at-price from a profile approximated with bars. Define bins and value-area construction: VAH and VAL bound a combined chosen share of profile volume (often 70%); each boundary does not independently contain 70%. Historic volume is not a map of current resting orders.

Order-book analysis needs timestamped venue-specific quotes/depth or event messages, with handling of cancellations, executions and sequence gaps. OHLCV cannot reconstruct Level 2 depth, spoofing, dark-pool inventory or a calibrated VPIN model. Mark these unavailable when the relevant feed is absent.

VPIN requires method-specific intraday trade/volume buckets, buy/sell classification and calibration; whether quotes are needed depends on the chosen classification method. Level 2 depth is not a universal VPIN requirement.

Separate traded option volume and open interest. IV rank and IV percentile are different statistics; state lookback and convention. Dealer gamma requires a pricing model, contract multiplier, Greeks, open interest and an explicit dealer-position sign assumption. Open interest alone does not reveal dealer holdings or an exact gamma-flip level.

## Setups and invalidation

Give conditional setup, support/resistance ranges, confirmation, invalidation, event exposure, spread/depth and likely slippage. ATR stops and chart levels do not ensure fills during gaps. Calculate reward/risk after expected costs; compare option profit including premium and carrying costs, not gross payoff alone.

## Output

Produce the dated data/indicator table, setup explanation, range-based levels, alternatives, principal failure modes and horizon-specific directional view. Mark estimated liquidity and assumptions. Route sizing and execution feasibility through alpha-portfolio-risk; preparing a setup does not authorize an order.


## Evidence and signal contract

Record the asset/venue, currency, analysis timestamp, observation period, source links, and publication/availability dates. Refresh current claims from primary sources when permitted; with supplied-data or offline-only requests, label unverified current claims rather than assuming live verification. Identify estimates and unavailable inputs explicitly. Missing evidence is unavailable, not a neutral score. Source examples and portfolio names are illustrations, not current holdings or facts.

When a directional signal helps, give an asset-specific score from -2 (bearish) to +2 (bullish), confidence High/Medium/Low with a reason, horizon, key risk, and falsification condition. Keep tactical (0–4 weeks), positional (1–6 months), and thematic (6–24 months) assessments separate. Confidence is an evidence assessment, not a probability. Omit a score when evidence is inadequate.
