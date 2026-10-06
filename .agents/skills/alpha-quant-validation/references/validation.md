# Validation and metrics

## Measurement conventions

Use a consistent periodic return frequency and currency. Identify simple versus log, arithmetic versus geometric, and total-return versus price data. Annualization using sqrt(periods/year) assumes suitable dependence properties; inspect autocorrelation and report sampling uncertainty.

- CAGR = product(1+r_t)^(periods_per_year/n)-1 for regular observations; actual elapsed years are preferable for irregular dates. Avoid treating arithmetic annualized mean as CAGR.
- Sharpe = mean(periodic excess returns)/sample standard deviation(periodic excess returns) * sqrt(periods_per_year), under stated annualization assumptions. Align risk-free returns at the same frequency. It is not CAGR divided by volatility without qualification.
- Sortino uses a declared minimum acceptable return and downside deviation definition. A conventional full-sample denominator is sqrt(mean(min(r_t-MAR_t,0)^2)); state alternatives and avoid silently calculating only over losing observations.
- Information ratio = mean(periodic active return)/sample standard deviation(periodic active return)*sqrt(periods_per_year). Tracking error is that active-return standard deviation annualized with the same convention.
- Construct NAV from total returns, HWM_t=max(NAV up to t), DD_t=NAV_t/HWM_t-1. Maximum drawdown is min(DD); state whether reported as a signed return or positive loss magnitude. Identify recovery periods and censor unrecovered drawdowns.
- Information coefficient needs an identified cross-sectional/time-series definition, forward horizon, sample count and confidence interval. Do not interpret correlation as return certainty.
- Regression alpha requires the named factors, units, frequency, aligned dates, intercept and inference method. Use heteroskedasticity/autocorrelation-aware errors when warranted. Report exposure magnitude and contribution separately from significance.

## Missing-data example

Request: "Score a strategy using a politician transaction from 45 days ago, with no price history."
Result: disclose the transaction/filing/public dates; explain when it became eligible; record historical validation not performed; propose required returns, point-in-time filings, baseline, splits and costs. An observation is not a backtest, and the source's example Sharpe cannot supply missing results.

## Source corrections

The source's sample backtest marks balanced factors/PASS while displaying momentum t=5.6, although its stated rejection test is >2.5; sample holdings also conflict with its single-name risk cap. Financing drag and trading-cost horizons are not consistently reconciled. Recompute from actual series and explicit definitions instead of copying these demonstrations.

The SEC distinguishes hypothetical/backtested results from actual performance and highlights assumptions and limitations. This is research context, not a claim that a particular legal regime applies to the user: https://www.sec.gov/resources-small-businesses/small-business-compliance-guides/investment-adviser-marketing
