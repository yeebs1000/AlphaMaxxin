# Constraints and financing

## Optional Alpha Maxxin profile

Activate numeric settings only if the user requests this source profile, or display them as explicitly hypothetical constraints. They are not universal portfolio requirements.

| Parameter | Source convention | Adaptation |
|---|---|---|
| Single name | <=5% NAV | Distinguish diversified funds, look-through names and derivative notional. |
| Sector | <=25% NAV | Specify taxonomy and overlap. |
| Country | <=30% NAV | Define revenue/listing/domicile risk basis. |
| Theme cluster | <=15% NAV | Justify membership and correlated risk. |
| Beta | 0.8–1.2 | Equity-oriented target, inappropriate as a blanket defensive mandate. |
| Margin buffer | 35% above maintenance | Define (equity-maintenance)/maintenance>=0.35; verify broker-specific rules and stress margin changes. |
| Financing/expected alpha | Reject/downgrade >25% | Compare consistent horizons and uncertainty; undefined if expected alpha<=0. |
| Rebalance drift | Name>1.5 percentage points; sleeve>5 | State percentage points versus relative percentages; model turnover and taxes. |

Core 50–60%, tactical 25–35%, opportunistic 10–15%. Cash differs: 5–15% in Prompt 26, 5–10% in the appendix. Choose one explicit configuration and make it sum 100%: the source range midpoints sum above 100%, so they are not a ready portfolio. Sample 31.6% MSFT and 18.3% DBS conflict with the 5% name limit.

## Risk definitions

If L=-portfolio return, VaR_q is the q quantile of the loss distribution. Expected shortfall averages the worst 1-q tail, with a declared empirical/interpolation convention. Parametric Gaussian estimates rely on distribution assumptions; historical simulation relies on a representative sample. Neither guarantees a maximum loss. Account for options/nonlinearities, liquidity and changing correlations.

Risk checks require enough aligned histories and actual positions. Portfolio beta=sum(exposure weight_i*beta_i) only under consistent benchmark/currency/exposure conventions. A statistically significant factor loading alone is not excessive concentration.

## Financing and roll costs

Simple daily financing charge = applicable notional * signed contractual annual funding rate / day-count base * charged days. Rates are decimals. Sum over actual daily notionals/rates, applying long/short terms, holidays/weekend charging, FX, borrow, fees and broker methodology. Compound only if charges actually capitalize; the source labels a simple one-day formula compounding.

Verify current SOFR/SORA and actual broker markups; never use the source's illustrative ~3.60% as current. Stress margin requirements with declared scenarios; source +50–100% margin hikes are assumptions, not universal behavior. Exact liquidation prices require complete account-level margin rules, other positions, equity/FX and broker discretion.

For futures, check exchange settlement/delivery, first-notice/last-trade dates and actual liquidity migration. A universal 3–5-day roll rule is unsafe for contract-specific notice dates. Report front/next prices, multiplier, commissions, spread and model assumptions; do not claim an execution window eliminates slippage.

For a proposed options structure, identify underlying, expiry, strikes, call/put, long/short quantity and contract multiplier for every leg. Include premium, bid/ask assumptions, assignment/exercise, margin and payoff/profit bounds; unlimited risks require explicit recognition. For long/short scale-outs, apply targets in the correct direction and declare whether percentages refer to the original or remaining position. A 33%/33%/remainder split leaves 34% of the original. Session windows must use exchange timezones and daylight-saving calendars.

Fees and expenses affect investment returns: https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins/updated
