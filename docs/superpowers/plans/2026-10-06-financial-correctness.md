# Financial Correctness Implementation Plan

> **For agentic workers:** use the ownership boundaries below and complete red/green regressions before claiming a task complete. Root coordinates integration and final independent review.

**Goal:** Fix the sixteen reproduced correctness defects and make the existing product easier to evaluate offline.

**Architecture:** Preserve the current modules. Add one shared return-alignment helper, explicit sync-source selection, and a checked recommendation boundary; keep authoritative numeric rendering in code. Gate legacy ML validation metadata and retain honest limitations.

**Tech Stack:** Python 3.11+, FastAPI, NumPy/scikit-learn, React/TypeScript, Node 24, pytest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-10-06-financial-correctness.md`.

## Global constraints

- Local-only API; read-only broker clients; no live APIs or model calls in tests/demo.
- Preserve existing user holdings, history, settings, credentials, and the published skills tag.
- No shared-file edits across workers; root alone stages, commits, pushes, creates and merges PRs.
- Use the existing release test venv, isolated TEMP/basetemp paths, and `ALPHAMAXXIN_OFFLINE=1`.

## Review focus

- Partial selected-source failures must preserve the existing book byte-for-byte.
- Tiny fractions and adjacent mixed-currency sections must survive serialization.
- A missed quote or missing FX must not become apparent performance or liquidity confidence.
- A holiday, missing date, cap infeasibility, and first loss must produce honest metrics or unavailability.
- Invalid, conflicting, cached, or malformed synthesis results cannot cross the recommendation boundary.

## Task 1 — State integrity

Files: `backend/app/portfolio.py`, `backend/app/api/portfolio.py`, `backend/app/equity_history.py`, `backend/app/reports/store.py`, `backend/app/data/base.py`, matching state/API tests.

- [x] Add regressions for JPY/CNY/MYR and tiny fractions; broker partial failure and explicit selection; quote-dropout history; unique report IDs; concurrent same-key writes.
- [x] Confirm failures on the current implementation with focused pytest runs.
- [x] Preserve full numeric text, parse emitted currency sections, use atomic writes, refuse incomplete selected-source replacement, skip incomplete snapshots, prepend equity baseline, add unique report suffixes, use independent cache temp files.
- [x] Run focused state tests and Python compilation; report changed interfaces and red/green evidence to root.

## Task 2 — Quantitative invariants and ML boundaries

Files: `backend/app/skills/risk.py`, `portfolio_construction.py`, new `return_alignment.py`, `scripts/train_ml_alpha.py`, `backend/app/data/ml_model.py`, matching tests.

- [x] Add failures for feasible/infeasible caps, redistribution, first-return drawdown, holiday/common-interval alignment, absent dates, date-grouped label purging, importance holdout, and legacy artifact metadata.
- [x] Verify red; implement capped redistribution and common-close-calendar alignment using the spec interface.
- [x] Carry each sample's actual label end date through training; construct purged date-grouped splits for validation and the importance holdout. Keep preprocessing train-only and report data-vintage/universe limitations.
- [x] Refuse unpurged legacy validation claims in inference; keep experimental status explicit.
- [x] Run focused quant/model tests and compile; report exact interface/metadata to root for pipeline integration.

## Task 3 — Existing UI and setup

Files: `frontend/src/pages/Portfolio.tsx`, `Settings.tsx`, `Charts.tsx`, minimal plain TypeScript helpers/tests, frontend package test command, `backend/app/settings.py`, setup/start scripts and setup tests.

- [x] Add regression checks for actual candle opens and gaps, all active role controls, arbitrary supported provider IDs, provider-aware defaults, selected sync request bodies, setup interpreter isolation and install/build failure handling.
- [x] Verify red before changing behavior; use backend sync contract from the spec.
- [x] Allow OpenAI/local model IDs and render every active role. Preserve saved choices. Use supplied opens. Explain selected broker completeness and remove false privacy copy.
- [x] Bootstrap `.venv`, use it on subsequent launches, use `npm ci`, and fail setup on install/build errors.
- [x] Run frontend tests/build and offline setup tests; report contract changes. No live provider/model tests.

## Task 4 — Pipeline and recommendation integration

Files: `backend/app/reports/pipeline.py`, any other production return consumers, `backend/app/skills/signals.py`, `backend/app/llm/analysts.py`, synthesis prompt/render helper, focused integration/contract tests.

- [x] Pin failures for incomplete valuation recording, missing ledger ID, FX turnover, absent fundamental coverage, nonpositive R:R, invalid/vetoed/high-conviction recommendations, numeric additions, malformed schemas, and invalid cached output.
- [x] Integrate `align_daily_returns` for risk and covariance. Convert ADV with known FX; report gaps. Attach persisted report ID before ledger recording.
- [x] Return unavailable fundamental score when no eligible fields exist; require valid long price ordering and positive R:R for sizing.
- [x] Validate structured synthesis against computed inputs and render recommendation tables/levels deterministically. Mark commentary as unverified and never present rejected recommendations.
- [x] Run focused integration tests, then coordinate fixes for the complete suite.

## Task 5 — Demonstration, documentation, verification, publication

- [x] Add a fixture-only demo that writes a shareable sample report without keys or personal data, and exercise its entry point offline.
- [x] Rewrite `RESEARCH_LIMITATIONS.md`, README and changelog around actual final behavior and remaining research/live-use gaps.
- [x] Run full backend tests, frontend tests/build, offline launcher/demo, compile changed Python, deterministic skills build, credential scan and diff checks.
Publication procedure: resolve independent review findings, publish a concrete PR,
attach it to this chat, wait for required CI, and merge the verified commit under
the user's full authority. Report changes, fresh verification and remaining
limits honestly; do not claim profitable alpha or point-in-time retraining.
