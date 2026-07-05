# Changelog

All notable changes to this project are documented in this file.

## [Unreleased] — v2 rebuild

Deterministic-first architecture: Python skills compute every number
(technicals, fundamentals, macro, risk, catalysts); a small set of LLM
"domain analysts" (Macro, Fundamentals, Technicals+Options, News/Catalysts,
Risk) interpret compact JSON and one synthesis call writes the report —
~80–95% token reduction vs the 33-agent prompt pipeline. New FastAPI
backend (`backend/`) + React frontend (`frontend/`) replace the
customtkinter GUI, which remains available for one release via
`python run.py --legacy` (tagged `v1-legacy`). Agents without a real data
feed become disabled "lenses" that show as off until a feed is wired,
instead of producing disclaimed LLM guesswork.

### Added (v2)
- 13 deterministic skills with known-answer tests (indicator math verified
  against the v1 implementation; Black-Scholes against textbook values).
- Data providers: Yahoo, Finnhub (news + earnings/IPO calendars + metrics),
  Alpha Vantage, FRED (new), yfinance fundamentals (new), congressional
  PTR disclosure dumps (new) — disk-cached outside the repo, rate-limited,
  and offline-tripwired in tests.
- Watchlists, report history with in-app viewing, SSE run progress,
  per-role model routing, LLM response cache, and a cost meter.
- React dashboard (8 pages) replacing the customtkinter GUI.
- Fully offline test suite (89 tests) wired into CI, plus a frontend
  build job and an offline boot smoke test (`python run.py --check`).

### Added
- `agents/` folder — agent prompts split out of the `AGENTS.md` monolith
  (one file per agent, grouped by pipeline layer) with a fast indexed
  lookup in `runner.py`; `AGENTS.md` itself is kept as a human-readable
  reference and legacy fallback.
- Market-scan mode: standalone scan/idea-generation presets (Opportunist,
  Macro Pulse, Dragon Watch, Sakura Signal, Kimchi Premium, Frontier Run,
  Quant Lab, Insider Edge) now scan the broad market instead of being
  anchored to the user's own `Portfolio.md` holdings.
- Region-scoped market screening: Japan and South Korea candidate
  universes added alongside US/SG/HK, with per-preset region scoping
  (Dragon Watch -> HK, Sakura Signal -> JP, Kimchi Premium -> KR).
- LICENSE (MIT), CONTRIBUTING.md, `.env.example`, and a minimal CI workflow.

### Changed
- Renamed `AGENTS_v3.0.md` -> `AGENTS.md`.
- `Portfolio.md` and `external_holdings.json` are now gitignored and ship
  as sanitized placeholders; real holdings are edited locally or via the
  in-app Portfolio Editor, never committed.

### Removed
- Stale duplicate `gui.py`/`runner.py`/`AGENTS_v2.2.md`/`Portfolio.md`
  copies under `AlphaMaxxinMobile/app/src/main/python/`.

## [3.0]
- moomoo live data wired in: quotes, positions, dividends, order book
  depth, industry classification, analyst consensus.
- `Portfolio.md` auto-syncs from moomoo; non-moomoo brokers supplement via
  `external_holdings.json`.
- Beginner setup wizard (`setup.py` / `start.bat` / `start.sh`).
- Position guidance, market screener, and technical indicators added.
