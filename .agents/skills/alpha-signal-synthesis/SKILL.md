---
name: alpha-signal-synthesis
description: Use when combining multiple investment research signals into asset-specific horizon scores, checking weight coverage, or resolving conflicting investment evidence.
---

# Investment Signal Synthesis

Read [weights and overrides](references/weights-and-overrides.md) when using the source's aggregation settings. Weights, confidence mappings and override thresholds are configurable model assumptions.

## Make signals comparable

Each input needs asset, horizon, source/date, asset-specific bullish/bearish direction, score in [-2,+2], evidence confidence and relevance. Translate macro posture, inflation, commodity and liquidity scores to the same target asset before combining them. A +2 hawkishness score is not inherently a +2 equity return score. Never combine distinct assets or time horizons.

Select only relevant, available inputs. Missing evidence remains unavailable; it is not zero. Group correlated evidence so the same release, platform story or macro mechanism is not counted as independent support. State the eligible weight universe and available-weight coverage. A single available bullish input can yield a high average with low coverage; it does not create high overall conviction.

## Aggregate and explain

For a declared confidence mapping, S_raw = sum(w_i*c_i*s_i)/sum(w_i*c_i) over available comparable inputs. The source uses High=1, Medium=0.65, Low=0.35. Report effective normalized weights, denominator, coverage and confidence separately; those multipliers are not probabilities. If no usable weighted inputs exist, return unavailable.

Use [scripts/aggregate_signals.py](scripts/aggregate_signals.py) for reproducible supplied-data aggregation: run `python scripts/aggregate_signals.py input.json`. Read its `--help` and input example in the reference. It validates direction mapping, asset/horizon alignment, ranges, missing values and adjustment limits; it does not verify sources or calibrate a model.

Log same-asset/horizon disagreements >1.5 points with driver, freshness and dependency. Examine all materially relevant conflicts; do not hide a contradiction just because a source weight is small. Prefer explanatory reconciliation or an unresolved status over an automatic regime override.

Any user-selected adjustment needs a named rule, observed trigger, numeric effect, empirical status and precedence. Show baseline, each adjustment and final clipped score. Explicit risk caps apply after bullish bonuses. Default to no political boost or automatic risk-on/off adjustments because source versions conflict and are unvalidated. Scenarios can illustrate proposed rules without activating them.

## Output

Give input/effective-weight table, excluded/missing inputs, coverage, separate tactical/positional/thematic scores, conflict register, adjustment log and unresolved limitations. A composite score is a research summary; alpha-portfolio-risk assesses sizing feasibility.

Source adaptation: Prompt 23 and Prompt 0 conflict handling.

## Evidence and signal contract

Record the asset/venue, currency, analysis timestamp, observation period, source links, and publication/availability dates. Refresh current claims from primary sources when permitted; with supplied-data or offline-only requests, label unverified current claims rather than assuming live verification. Identify estimates and unavailable inputs explicitly. Missing evidence is unavailable, not a neutral score. Source examples and portfolio names are illustrations, not current holdings or facts.

When a directional signal helps, give an asset-specific score from -2 (bearish) to +2 (bullish), confidence High/Medium/Low with a reason, horizon, key risk, and falsification condition. Keep tactical (0–4 weeks), positional (1–6 months), and thematic (6–24 months) assessments separate. Confidence is an evidence assessment, not a probability. Omit a score when evidence is inadequate.
