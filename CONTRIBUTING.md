# Contributing to AlphaMaxxin

Thanks for considering a contribution. A few things to know before you start.

## Setup

Run the setup wizard (`start.bat` on Windows, `start.sh` on Mac/Linux) or
follow the manual steps in [README.md](README.md). Copy `.env.example` to
`.env` and fill in only the keys you need — everything is optional.

## Running it locally

The project is mid-rebuild ("v2"): a FastAPI backend under `backend/` plus a
React frontend under `frontend/` are replacing the legacy customtkinter GUI.
Until the rebuild ships, the legacy app still runs with:

```
python gui.py
```

## Testing changes — please read this before opening a PR

**Development and testing never call live APIs.** Not the LLMs (Claude,
Gemini, OpenAI — paid and metered), and not the data providers or brokers
either. All automated tests are offline: fixture data, mocked providers,
canned LLM responses.

- The v2 backend suite lives in `backend/tests/` and runs free:
  `cd backend && python -m pytest`. It sets `ALPHAMAXXIN_OFFLINE=1`, which
  makes real providers raise if anything accidentally reaches for the
  network — if your test trips it, add a fixture instead.
- New deterministic code (skills, providers, report pipeline) must come with
  offline unit tests.
- Legacy `tests/test_cli.py` / `tests/test_news.py` are manual smoke scripts
  that DO hit paid APIs — never run them casually and never wire them into CI.
- End-to-end live verification (real brokers, real LLM calls) is done
  deliberately and manually by whoever owns the API keys — never as part of
  routine development.

CI compiles the whole repo and runs the offline `backend/tests` suite — it
never exercises live agents or providers.

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
