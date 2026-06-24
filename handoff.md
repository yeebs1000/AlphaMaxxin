# AlphaMaxxin — Handoff

A 32-agent AI investment research desktop app. Private repo:
https://github.com/yeebs1000/AlphaMaxxin

## Stack
- `gui.py` — CustomTkinter desktop GUI
- `runner.py` — asyncio agent orchestration, LLM provider abstraction (`call_llm`: Claude → Gemini → OpenAI)
- `moomoo_client.py` — live brokerage data (quotes, positions, dividends, order book, industry, analyst consensus) via moomoo OpenD
- `news_fetcher.py` — Finnhub/Alpha Vantage news+sentiment
- `AGENTS_v3.0.md` — system prompts for all 32 agents (Prompt 0 = Master Orchestrator + 4 layers of sub-agents)
- `setup.py` / `start.bat` / `start.sh` — beginner onboarding wizard (ASCII-only output, plain `input()`, no `getpass`)

## v3.0 status (done)
- moomoo live data wired in: quotes, positions, dividends, order book depth, industry classification, analyst consensus
- `Portfolio.md` auto-syncs from moomoo; non-moomoo brokers (IBKR) supplement via external file, not hardcoded
- GUI perf fixes: News Feed pagination, `CTkScrollableFrame` `bind_all` leak fixed via explicit `unbind_all` in `_build_ui()`, startup race fixed via `self.after(0, ...)` deferral
- Master Orchestrator + Prompt 29 rewritten for concise institutional tone with hard per-section word caps (was previously bloated AND truncating mid-report)
- Concurrency exists today: Master Orchestrator fan-out uses `asyncio.gather` bounded by `_subagent_semaphore` (`_SUBAGENT_CONCURRENCY = 6`, `runner.py:568-569`), with retry-on-empty and retry-on-429/529
- Pushed to GitHub (private), `requirements.txt` fixed (matplotlib/google-genai/openai added, pywin32 made win32-only), `start.sh` exec bit fixed
- Removed stray `__pycache__/lark_bot.cpython-314.pyc` — leftover bytecode from an unrelated project, not part of this codebase

## Pending — next session should start here

**Hard constraint while doing this work: do NOT invoke the real agent pipeline (`runner.run_agent()` / `call_llm()` against Claude) during development/testing — it burns real tokens/cost. Pure-Python testing (data fetch, indicator math, no LLM calls) is fine. If end-to-end agent testing is unavoidable, use Gemini only, never Claude.**

1. **Concurrency tuning.** Confirmed concurrency already exists (`_subagent_semaphore`, 6 concurrent calls) — user reported slowness anyway. Need to determine: is the bottleneck the flat semaphore cap, or does the user actually want a dependency-graph-aware scheduler (agents that don't consume another agent's output run immediately, others wait)? Check whether any of the 32 agents' prompts in `AGENTS_v3.0.md` actually declare upstream dependencies, or whether all 32 are currently independent (in which case the fan-out is already maximally parallel and the fix is elsewhere, e.g. raising `_SUBAGENT_CONCURRENCY` or reducing per-call latency).

2. **Token-budget enforcement so reports never truncate.** `call_llm`'s Claude branch already raised `max_tokens=8192` (`runner.py:511`). Need to verify whether 8192 is actually sufficient for a full 32-agent synthesis given the new (already-trimmed) section word caps in Prompt 0, or whether sections still need further cuts. User has explicitly authorized further edits to the Master Orchestrator portion of `AGENTS_v3.0.md` if specific sections need to go. Do this via word-count math on the prompt's caps, not by running the agents.

3. **Technical Analysis indicators (Prompt 18, not yet located/edited this session — re-grep `AGENTS_v3.0.md` for "Technical Analysis Agent" since line numbers shifted after Prompt 0/29 edits).**
   - Add RSI, MACD, Moving Averages, Bollinger Bands, and Volume profile on higher timeframes.
   - No kline/historical-OHLCV function exists yet in `moomoo_client.py` — will need one (moomoo SDK has historical K-line APIs) or reuse the Yahoo Finance OHLC fetch pattern already in `gui.py`'s `fetch_history()` (`https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=...&interval=1d`).
   - Volume should be used to infer where market participants' positions are concentrated, to ground more realistic target-price levels — not just as a raw stat.
   - **Verbatim user constraint, do not violate:** "dont mix up volume and turnover columns. You may also not [mix up] pre_volume, Volume and after_volume in analysis" — i.e. volume (share count) ≠ turnover (price × volume, a value metric); and pre-market / regular / after-hours volume fields must be kept distinct, not summed or conflated, if the data source exposes them separately.
   - Once indicator scripts exist and are unit-tested with plain Python (no LLM calls), factor the new capability into Prompt 18's instructions — but only if it makes sense for that agent's existing scope (user's own qualifier).

## Notes for whoever picks this up
- `AGENTS_v3.0.md` is ~4500+ lines; Prompt 0 and Prompt 29 were heavily edited this version. Prompts 30/31/32 are known to still have unrelated wordiness/jargon issues — explicitly out of scope unless asked.
- Don't re-run real Claude agent calls just to "verify" prompt edits look right during this next phase — read the prompt text and reason about word counts/logic instead, per the cost constraint above.
