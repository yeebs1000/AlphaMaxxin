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
| IBKR / Tiger Brokers (no API key / Open API account — see "Linking your broker" below) | Live positions from those brokers | Free |

If you skip all of them, the app still opens — you just won't get AI
reports or live news until you add at least one LLM key (Claude/Gemini/
OpenAI). Prices fall back to Yahoo Finance automatically either way.

Re-run the setup wizard anytime to add keys you skipped the first time.

---

## Linking your broker

`Portfolio.md` is what every agent reads. You can always edit it by hand or
through the in-app Portfolio Editor, but the app can also pull your real
positions live and rebuild it for you (the **⇄ Sync Brokers** button in the
Portfolio Editor tab, also run once automatically on launch). Each broker
below is independent — set up as many or as few as you actually use.

### Moomoo (live)
No API key. Install and log into moomoo's [OpenD](https://www.moomoo.com/download/OpenAPI)
gateway app with your moomoo account, then set `MOOMOO_HOST`/`MOOMOO_PORT`
in `.env` if you changed OpenD's defaults (127.0.0.1:11111).

### Interactive Brokers / IBKR (live)
No API key. Requires **TWS** or **IB Gateway** running locally:
1. Install [TWS](https://www.interactivebrokers.com/en/trading/tws.php) or
   [IB Gateway](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php)
   and log in.
2. In TWS/Gateway: **Configuration → API → Settings** → check **"Enable
   ActiveX and Socket Clients"**. Leave **"Read-Only API"** checked —
   AlphaMaxxin only reads positions, it never places orders.
3. Set `IBKR_HOST`/`IBKR_PORT`/`IBKR_CLIENT_ID` in `.env` if you changed the
   defaults (127.0.0.1, 7497 for TWS paper / 7496 live / 4002 Gateway paper
   / 4001 Gateway live).
4. `pip install ib_async` (already in `requirements.txt`).

### Tiger Brokers (live)
Requires a separate, free **Tiger Open API** account and an RSA keypair —
follow [Tiger's own setup guide](https://quant.itigerup.com/openapi/en/python/operation/step1.html)
to generate the keypair and get your Tiger ID. Then set `TIGER_ID`,
`TIGER_ACCOUNT`, and `TIGER_PRIVATE_KEY_PATH` (path to the private key file)
in `.env`. `pip install tigeropen` (already in `requirements.txt`).

### Webull, Robinhood, or any other broker
These don't have a wired-up live integration (no stable official API).
Add your positions to `external_holdings.json` instead — it's merged in
alongside whatever live brokers you've configured, with quantities summed
and cost-basis weighted-averaged if the same ticker appears in two sources:

```json
{
  "EX": {
    "company": "Example Inc",
    "quantity": 10,
    "cost_price": 25.50,
    "currency": "USD",
    "broker": "Robinhood"
  }
}
```

To find quantity/cost-basis to copy in:
- **Webull**: app → Account → Positions → tap a holding for cost basis, or
  Account → Reports/Tax Documents → Account Statement for a CSV export.
- **Robinhood**: app → Account → History → Statements (monthly CSV with
  positions), or open a position's detail page for average cost.

This file is gitignored — your real holdings never get committed.

---

## Project layout

- `gui.py` — the desktop app (run this to launch, or use `start.bat`/`start.sh`)
- `runner.py` — agent orchestration logic, LLM calls
- `moomoo_client.py` / `ibkr_client.py` / `tiger_client.py` — live brokerage
  data (all optional; see "Linking your broker" above)
- `news_fetcher.py` — news/sentiment fetching
- `AGENTS.md` — the system prompts for all 32 agents (also split per-agent
  under `agents/`, which is what's actually loaded at runtime)
- `Portfolio.md` — your holdings (edit directly, or via the in-app editor;
  gitignored, so your real data never gets committed)
- `external_holdings.json` — supplementary holdings for brokers without a
  live integration (gitignored)
- `tests/` — manual smoke-test scripts (see `tests/README.md` — these hit
  paid APIs and are not run automatically)

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines and
[CHANGELOG.md](CHANGELOG.md) for release history. Licensed under
[MIT](LICENSE).

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
