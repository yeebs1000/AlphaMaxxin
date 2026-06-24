# AlphaMaxxin

A desktop app that runs a 32-agent AI research pipeline over your stock
portfolio and produces investment reports — entry/exit prices, position
sizing, risk scenarios, options strategies, the works. Live prices and
account data optionally come from moomoo; AI analysis comes from
Claude/Gemini/OpenAI; news comes from Finnhub/Alpha Vantage.

**Never used this before? You don't need to know what any of the above
means.** Just follow Quickstart below — it walks you through everything.

---

## Quickstart (first time on this computer)

1. **Install Python** if you don't have it: [python.org/downloads](https://www.python.org/downloads/).
   On Windows, tick **"Add Python to PATH"** during install.
2. **Download this project** — click the green **Code** button on GitHub →
   **Download ZIP**, then unzip it. (Or `git clone` if you know what that means.)
3. **Run the setup wizard:**
   - **Windows:** double-click `start.bat`
   - **Mac:** right-click `start.sh` → Open (or open Terminal, drag `start.sh`
     into the window, press Enter)
   - **Linux:** open a terminal in this folder and run `./start.sh`

The wizard checks your Python version, installs everything the app needs,
and walks you through getting free API keys (all optional — explained as
you go). At the end it offers to launch the app for you.

**Already done this once?** Just run `python gui.py` to launch — no need
to re-run setup unless something changed.

---

## What you'll be asked for

The setup wizard asks for a few API keys. Every single one is **optional**
— the app runs and shows you the GUI with zero keys configured. What
changes is what works:

| Key | What it unlocks | Cost |
|---|---|---|
| Claude (Anthropic) or Gemini | The AI agents that write reports | Gemini has a free tier; Claude is paid-per-use |
| OpenAI | Alternative to Claude/Gemini | Paid-per-use |
| Finnhub / Alpha Vantage | Live news headlines & sentiment | Both have free tiers |
| moomoo (no API key — separate app) | Live brokerage prices, your real positions, order book | Free, but you need a moomoo account |

If you skip all of them, the app still opens — you just won't get AI
reports or live news until you add at least one LLM key (Claude/Gemini/
OpenAI). Prices fall back to Yahoo Finance automatically either way.

Re-run the setup wizard anytime to add keys you skipped the first time.

---

## Project layout

- `gui.py` — the desktop app (run this to launch, or use `start.bat`/`start.sh`)
- `runner.py` — agent orchestration logic, LLM calls
- `moomoo_client.py` — live brokerage data (optional)
- `news_fetcher.py` — news/sentiment fetching
- `AGENTS_v3.0.md` — the system prompts for all 32 agents
- `Portfolio.md` — your holdings (edit directly, or via the in-app editor)
- `AlphaMaxxinMobile/` — a separate Android app, built independently with
  Android Studio (not part of the desktop Quickstart above)

## Troubleshooting

- **"python not found" / "python3 not found"** — Python isn't installed, or
  wasn't added to your system PATH. Reinstall from python.org and make sure
  to tick the PATH checkbox (Windows) or use the official installer (Mac).
- **Dependency install fails** — usually a connectivity issue. Re-run the
  setup wizard. If it keeps failing, copy the exact error message when
  asking for help.
- **App opens but reports never generate** — you need at least one of
  Claude/Gemini/OpenAI configured. Re-run setup to add a key.
- **No live prices/positions from moomoo** — that's expected unless you've
  separately installed and logged into moomoo's OpenD gateway app. The app
  falls back to Yahoo Finance automatically.
