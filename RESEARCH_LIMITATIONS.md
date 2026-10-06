# Current research and product limitations

AlphaMaxxin is experimental local research software. Fixture tests and the
[synthetic offline demo](examples/offline-report.html) establish software
behavior, not investment edge or reliable live outcomes. The standalone skills
are analytical guidance and cannot enforce the application checks themselves.

## Signals and allocation

Signal weights and Full/Half/Starter tiers (5%/3%/1.5%) are heuristics, not
calibrated probabilities or optimal allocations. Long buy sizing requires
positive risk/reward, valid stop/target order, positive composite direction
and no distress veto. Allocation redistribution enforces final name caps;
infeasible full investment leaves explicit cash or an unavailable covariance tilt.
The event-study backtest excludes sizing, costs and overlapping-position netting.

## Reports and missing data

Structured recommendations are checked against computed ticker, action,
conviction, size and veto rules. Numeric tables are rendered from computed
inputs; invalid model output produces a mechanical fallback and is not cached.
Free model prose remains unverified and is stored separately as `commentary_md`
in report JSON. These checks cannot establish the truth of upstream sources,
analyst narratives or qualitative claims.

Missing quotes/FX withhold whole-book weights, sizing and new equity snapshots;
priced subtotals remain visible. Existing history is preserved, including legacy
snapshots whose completeness cannot be reconstructed. Cost-basis-adjusted book
returns approximate cash flows and are not verified time-weighted returns.
Material sales and absent cash balances limit interpretation.

Risk and covariance inputs use matching common close-date intervals. Historical
FX returns are not included: these are local-currency price-return approximations
weighted with current USD exposures. Cross-market close times differ even on the
same date. Non-daily aligned intervals withhold one-day VaR and annualized
volatility; matching-interval beta/correlation still need careful interpretation.

## ML evaluation

The trainer now splits complete feature dates and purges every training label
whose actual forward window reaches the next test period. Feature selection is
fit within training folds, including the permutation-importance holdout. Legacy
bundled models remain experimental; unpurged accuracy, AUC and importances are
withheld from inference context rather than presented as validated evidence.
No bundled artifact has been retrained as part of these software fixes.

The fixed current universe does not reconstruct historical membership. Current
FRED histories and uniform release delays do not reconstruct unrevised vintages.
Purging alone does not solve these limitations. Classifier scores are not
calibrated probabilities or net alpha; costs, baselines and genuinely held-out
point-in-time data remain necessary for investment conclusions.

## Setup and verification

Setup uses the project `.venv`, opt-in broker SDKs and `npm ci`, and stops after
install/build failures. Fresh defaults follow configured providers; saved model
IDs take precedence. Python dependencies are not fully locked across platforms.

CI runs offline backend regressions, production frontend helper checks, builds,
boot/demo smoke checks and secret scans. Manual browser workflow checks use local mocked
APIs; they do not verify broker gateways, market providers or real model behavior.
Live connections and a full fresh-machine setup remain user-run validation.
