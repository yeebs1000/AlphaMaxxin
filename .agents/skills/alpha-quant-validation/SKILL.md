---
name: alpha-quant-validation
description: Use when evaluating predictive investment models, statistical arbitrage, factor regressions, historical strategy backtests, or claimed quantitative alpha.
---

# Quant Models & Backtesting

Read [validation and metrics](references/validation.md) when calculating performance or model diagnostics. Produce reproducible validation, not plausible-looking results.

## Define what is being tested

Specify universe, benchmark, target, decision/fill times, holding period, feature availability, portfolio rules and costs. Check corporate actions, delistings, missing observations, calendars, currencies and point-in-time constituent membership. Align features with when they were available, including publication lags and revisions.

Separate chronological training, validation and untouched testing. Purge overlapping labels and use a gap/embargo when the target horizon would leak across splits. Fit preprocessing and feature selection on training data; tune without accessing final test outcomes. Choose a simple baseline before XGBoost, LSTM or transformer complexity. Feature importance and attention weights do not establish causality.

Cointegration requires aligned price series, integration/stationarity checks, a specified relationship and stability testing. A low p-value is not a calibrated probability of profitable reversion. Test hedge ratios and exits out of sample, including borrow and financing.

For regime models, separate estimated state labels from future regime predictions, and compare with a transparent rule-based baseline. Evaluate calibration and transition stability out of sample. For alpha decay, measure information coefficient or net signal return across declared forward horizons using publication-aligned data; report uncertainty rather than assigning an unsupported half-life.

## Validate strategy outcomes

Apply realistic tradability, fill assumptions, spread, commission, market impact, taxes, borrow and funding. Compare gross and net results, turnover, benchmark/factor exposures, capacity, drawdowns and regime dependence. Test parameter sensitivity and incremental contribution of added signals, with attention to repeated-search bias.

Historical replay and hypothetical stress scenarios are separate outputs. If a strategy has no live history during a crash, a modeled replay must be labeled hypothetical. A loading t-statistic indicates statistical evidence, not concentration size or factor crowding; inspect magnitude, contribution and correlated risks.

## Decision and output

Use user-specified evaluation criteria or propose explicit research criteria before interpreting results. The source's Sharpe>=1.20, drawdown<=12% and t-stat<=2.50 are unvalidated conventions, not universal approval tests. Report Supported, Inconclusive, or Rejected under the stated criteria, plus period, data, code/method, splits, costs, metrics, uncertainty and limitations.

If no historical returns or model artifacts exist, offer a concrete test design and mark validation not performed. Do not report measured performance, PASS, fitted models, Sharpe, VaR or exact prediction probabilities. Research can proceed with an explicit unvalidated status.

Source adaptation: Prompts 22 and 24.

## Evidence and signal contract

Record the asset/venue, currency, analysis timestamp, observation period, source links, and publication/availability dates. Refresh current claims from primary sources when permitted; with supplied-data or offline-only requests, label unverified current claims rather than assuming live verification. Identify estimates and unavailable inputs explicitly. Missing evidence is unavailable, not a neutral score. Source examples and portfolio names are illustrations, not current holdings or facts.

When a directional signal helps, give an asset-specific score from -2 (bearish) to +2 (bullish), confidence High/Medium/Low with a reason, horizon, key risk, and falsification condition. Keep tactical (0–4 weeks), positional (1–6 months), and thematic (6–24 months) assessments separate. Confidence is an evidence assessment, not a probability. Omit a score when evidence is inadequate.
