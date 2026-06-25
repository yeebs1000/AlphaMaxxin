# Contributing to AlphaMaxxin

Thanks for considering a contribution. A few things to know before you start.

## Setup

Run the setup wizard (`start.bat` on Windows, `start.sh` on Mac/Linux) or
follow the manual steps in [README.md](README.md). Copy `.env.example` to
`.env` and fill in only the keys you need — everything is optional.

## Running it locally

```
python gui.py
```

## Testing changes — please read this before opening a PR

This project calls paid, metered LLM APIs (Claude, Gemini, OpenAI) for its
core agent pipeline. **Do not run the full agent pipeline (`runner.run_agent()`
/ `call_llm()`) against a real API key just to "check" a change** — it costs
real money per call, and 32 agents fan out per run.

- Prefer testing with plain Python: data fetching, indicator math, prompt-text
  changes, mocked LLM responses, file I/O. None of that needs a live key.
- If you genuinely need to verify an end-to-end agent call, use a Gemini key
  (it has a free tier) rather than Claude or OpenAI.
- `tests/test_cli.py` and `tests/test_news.py` are manual smoke-test scripts,
  not an automated suite — `test_cli.py` invokes the real LLM pipeline and
  `test_news.py` calls live news APIs. Neither runs in CI for this reason; run
  them yourself, deliberately, when you need to.

CI only compiles the code (`py_compile`) — it doesn't exercise the agents.

## Code style

- No unrequested abstractions, comments, or error handling for cases that
  can't happen — match the existing code's style of staying close to what's
  actually needed.
- Run `py -m py_compile <changed files>` before opening a PR.

## Pull requests

- Keep PRs scoped to one change. Describe the *why*, not just the *what*, in
  the description.
- If you're touching `agents/*.md` prompt content, note which agent(s) and
  why — these directly change what the AI outputs.
