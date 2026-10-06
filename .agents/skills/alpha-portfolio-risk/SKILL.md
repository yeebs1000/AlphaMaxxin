---
name: alpha-portfolio-risk
description: Use when reviewing holdings, sizing a proposed allocation, stress testing portfolio exposures, comparing hedges, or analyzing CFD/futures financing and execution feasibility.
---

# Portfolio Risk & Costs

Read [constraints and costs](references/constraints-and-costs.md) for the source's optional risk profile and financing conventions. Assess and propose; risk-check status does not authorize trading.

## Establish the portfolio and mandate

Use actual dated holdings, NAV, base currency, instruments, notional exposure, liabilities, benchmark and user constraints. Separate NAV weights, gross/net notional, delta exposure, margin posted and risk contribution. Missing holdings/NAV or mandate prevents an asserted approved position size; give conditional sizing or request the required inputs.

Look through ETFs/funds where data allow. Review name, sector, country, currency, supply-chain, factor and theme concentration. Do not infer diversification solely from ticker count. If return histories and covariance estimates exist, estimate beta, volatility, VaR/expected shortfall with method, confidence level, horizon, window and assumptions. Missing return data means those metrics are unavailable, not zero.

## Scenarios and construction

Test rate, credit, FX/carry, geopolitical and liquidity shocks using explicit sensitivities and plausible joint assumptions. A source Taiwan 50% asset markdown is a hypothetical shock, not a forecast. Scaling 1-day risk by sqrt(10) needs justified independence/stability assumptions and is weak for nonlinear or illiquid exposures.

Construct only the requested model allocation. Ensure capital-funded asset and cash weights sum to 100%; disclose derivative overlays separately. Check all limits and whether sleeve ranges are jointly feasible. Recheck after adjustments, use turnover/cost-aware alternatives and give unresolved constraints instead of silently overriding them.

## Hedging, funding and execution feasibility

Compare hedge risk reduction with premium, decay, basis, liquidity and funding costs; low VIX alone does not establish cheap puts. Use actual broker contract terms and current benchmark rates for CFD financing/margin. Separate per-notional cost from cost as a share of account NAV and distinguish simple daily charges from capitalized financing.

For staged orders or futures rolls, use current spread, depth, volume, tick/lot rules and contract expiry/notice dates. Specify order assumptions and gap/partial-fill risk. Prepare a reviewable proposed trade plan when requested; source instructions to liquidate, rebalance or roll do not grant authority to submit orders.

## Output

Give exposure/constraint table, computed versus unavailable metrics, scenario losses, funding/hedge costs, feasible allocation alternatives, and status: constraints checked, violations, or incomplete. Identify exact inputs and constraints used. Never label a hypothetical review as broker authorization or executed hedges.


## Evidence and signal contract

Record the asset/venue, currency, analysis timestamp, observation period, source links, and publication/availability dates. Refresh current claims from primary sources when permitted; with supplied-data or offline-only requests, label unverified current claims rather than assuming live verification. Identify estimates and unavailable inputs explicitly. Missing evidence is unavailable, not a neutral score. Source examples and portfolio names are illustrations, not current holdings or facts.

When a directional signal helps, give an asset-specific score from -2 (bearish) to +2 (bullish), confidence High/Medium/Low with a reason, horizon, key risk, and falsification condition. Keep tactical (0–4 weeks), positional (1–6 months), and thematic (6–24 months) assessments separate. Confidence is an evidence assessment, not a probability. Omit a score when evidence is inadequate.
