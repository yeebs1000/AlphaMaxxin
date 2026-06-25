# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

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
