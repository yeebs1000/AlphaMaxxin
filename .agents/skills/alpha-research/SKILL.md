---
name: alpha-research
description: Use when requesting a full investment thesis, cross-asset research review, or portfolio research report that combines macro, company, market, and risk evidence.
---

# Investment Research

Turn the Alpha Maxxin prompt library into a research workflow sized to the user's question. A single-company question need not run every research domain.

## Select the relevant analysis

| Question | Skill |
|---|---|
| Economic cycle, policy, China/Japan/Korea, regional context | `alpha-macro` |
| Yield curves, credit, currencies, commodities | `alpha-rates-fx-commodities` |
| Accounting, valuation, sector economics, supply chains | `alpha-fundamentals` |
| Price setups, volume, options, liquidity | `alpha-technicals-liquidity` |
| Alternative data, social sentiment, political disclosures | `alpha-alternative-data` |
| Earnings/events, IPOs, M&A, private capital | `alpha-catalysts-capital` |
| Predictive models, strategy backtests, factor attribution | `alpha-quant-validation` |
| Comparable directional scores and conflicting evidence | `alpha-signal-synthesis` |
| Holdings, sizing, hedges, financing, execution feasibility | `alpha-portfolio-risk` |

Load relevant skills through the host's skill mechanism: `$alpha-macro` in Codex,
`/alpha-macro` for a personal Claude Code skill, or
`/alphamaxx-research:alpha-macro` for the Claude Code plugin. If direct routing is
unavailable, read the relevant sibling folder's `SKILL.md` and its needed
references. A separately installed specialist may be unavailable; report that
limitation and work with the guidance and tools actually present.

Use only available tools and relevant evidence. These are analytical capabilities; using this workflow does not itself require spawning agents, obtaining paid feeds, scheduling monitoring, or executing transactions.

## Develop the thesis

Start with the user-selected universe, horizon, benchmark, and decision. Infer reasonable analytical defaults when possible; request missing portfolio constraints only when a sizing decision depends on them. Verify identity, listing, share class, and corporate changes before reusing tickers from the source.

Link observations to mechanisms, mechanisms to earnings/cash flows or market pricing, and pricing to a thesis. Give a base case, bear case, bull case, catalyst, expected cost, principal risks, and evidence that would change the conclusion. Explain conflicting sources rather than averaging away the disagreement.

Research conclusions may be provided without a strategy backtest. Label backtesting not performed or not applicable honestly. Actionable sizing requires an actual portfolio constraint check; a research report cannot grant trading permission. If a tested strategy is claimed, route its historical validation through alpha-quant-validation.

## Output

Lead with the conclusion and its confidence. For a full review, include market regime, evidence/signal dashboard, ranked ideas only where supported, portfolio risk and cost findings, dated event watch, unresolved conflicts, and possible hedge tradeoffs. For a narrow request, keep only relevant parts. Distinguish completed checks from proposed work and unavailable checks. Never reproduce the source's sample PASS labels as results.


## Evidence and signal contract

Record the asset/venue, currency, analysis timestamp, observation period, source links, and publication/availability dates. Refresh current claims from primary sources when permitted; with supplied-data or offline-only requests, label unverified current claims rather than assuming live verification. Identify estimates and unavailable inputs explicitly. Missing evidence is unavailable, not a neutral score. Source examples and portfolio names are illustrations, not current holdings or facts.

When a directional signal helps, give an asset-specific score from -2 (bearish) to +2 (bullish), confidence High/Medium/Low with a reason, horizon, key risk, and falsification condition. Keep tactical (0–4 weeks), positional (1–6 months), and thematic (6–24 months) assessments separate. Confidence is an evidence assessment, not a probability. Omit a score when evidence is inadequate.
