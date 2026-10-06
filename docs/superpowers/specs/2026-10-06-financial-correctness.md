# Financial correctness improvements

The user authorized implementing the repository review's improvements with full authority. This work fixes the sixteen reproduced defects, improves the existing setup path, and supplies a reproducible offline demonstration. It preserves the local-only, read-only-broker architecture and the separately published research skills.

## Required outcomes

- Holdings retain their currency, quantity, and cost through Save. Markdown remains readable and backward-compatible; numeric display rounding must not change authoritative holdings. Writes are atomic.
- A failed selected broker cannot cause partial replacement of the book. Broker selection is explicit in the UI/request so installed optional SDKs are not mistaken for the user's intended sources. The existing no-body sync API remains conservative and never replaces after partial failure.
- Incomplete valuations do not become equity snapshots. Previously recorded historical rows are preserved rather than guessed or rewritten. Snapshot-based returns remain explicitly approximate because dated cash flows are not tracked.
- Allocation suggestions satisfy their final caps; infeasible full investment leaves a reported cash remainder or returns unavailable. First-period losses enter drawdown calculations.
- All production portfolio risk/covariance consumers use a shared common-date return alignment helper. Missing timestamps exclude an input rather than inventing dates. Benchmark intervals match portfolio intervals. Local-currency historical returns remain labeled; historical FX risk is not claimed without historical FX observations.
- Average traded value and holding value use the same currency, with absent FX treated as unavailable.
- Missing fundamental observations do not count as neutral evidence. Nonpositive risk/reward and invalid long entry/target/stop ordering cannot receive buy sizing.
- Structured model recommendations are checked against computed tickers, vetoes, sizing, conviction gates, and allowed fields. Authoritative recommendation tables and price blocks are rendered from computed data. Generated commentary remains identified as unverified; this change does not claim general natural-language fact checking.
- Report IDs are unique; the ledger receives the persisted ID; same-key concurrent cache writes use independent temporary files.
- ML validation uses complete date groups and purges sample outcome end dates before every test period, including the importance holdout. Feature selection does not inspect final test outcomes. Legacy unpurged model artifacts are not presented as validated. Current-universe and revised-macro limitations remain explicit; no live training or claims of profitable alpha.
- Settings cover all active roles and allow supported OpenAI/local model IDs. New defaults follow the configured provider without overwriting existing user choices.
- Candles use the supplied opens. Setup uses a project virtual environment, deterministic frontend installation, and stops on failed build/install steps.
- Tests and demo use fixture data only. No live providers, broker connections, model inference, or paid APIs.

## Shared interfaces and ownership

State worker owns portfolio parsing/saving/sync and its API, equity history, report storage, disk cache, and their tests. Frontend worker owns Portfolio UI, Settings UI/backend settings, Charts, setup/start scripts, and frontend/onboarding tests. Quant worker owns risk, portfolio construction, a new `skills/return_alignment.py`, ML training/inference metadata, and their tests. Root owns pipeline integration, other alignment consumers, signals, synthesis validation/rendering, docs/demo, and integration tests.

`sync_from_brokers(..., broker_sources: list[str] | None = None)` accepts `moomoo`, `ibkr`, `tiger`. Explicit selected failures preserve the saved file; omission attempts installed sources conservatively. `POST /api/portfolio/sync` accepts optional JSON `{ "broker_sources": [...] }`. A selected empty list supports external-only books; selected sources are part of the complete replacement contract, explained in the UI.

`align_daily_returns(daily_by_ticker: dict, benchmark_daily: dict | None = None) -> dict` returns `returns`, `benchmark_returns`, `dates`, `excluded`, and `basis`. It normalizes daily timestamps to UTC dates, sorts/deduplicates valid closes, intersects close dates before calculating returns, and never aligns different intervals by array position.

`equity_history.record(summary, ...) -> bool` returns whether a complete snapshot was recorded. Existing call sites can ignore the result; the pipeline records a status for reporting.

## Acceptance

Each reproduced failure gets a failing regression before its implementation. Focused checks run during development; root runs the whole backend suite, frontend tests/build, offline boot/demo, Python compilation, and credential scan. An independent whole-branch review precedes GitHub PR publication and merge. Public limitations are rewritten around remaining gaps, not stale fixed bugs.
