# AlphaMaxxin

[![CI](https://github.com/yeebs1000/AlphaMaxxin/actions/workflows/ci.yml/badge.svg)](https://github.com/yeebs1000/AlphaMaxxin/actions/workflows/ci.yml) ![License](https://img.shields.io/badge/license-MIT-blue) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Read--only](https://img.shields.io/badge/broker%20access-read--only-brightgreen)

A local, multi-lens investment analyst. Python computes every number —
technicals, fundamentals, macro, risk, catalysts — from real data feeds, and
a small set of AI "analyst lenses" interprets those numbers into a single
high-conviction research report on your **portfolio**, any **ticker**, or a
**watchlist**. Broker positions sync live from moomoo / IBKR / Tiger.

**Never used this before?** Just follow Quickstart below — it walks you
through everything.

> **Disclaimer:** AlphaMaxxin is a research and educational tool, not a
> financial advisor. Its output — including prices, targets, and any
> "recommendation" language — is AI-assisted analysis, not investment
> advice, and may be wrong, outdated, or based on incomplete data. It never
> places trades or transfers funds; you remain solely responsible for any
> investment decision you make. Use at your own risk, and consult a
> licensed financial advisor before acting on anything it produces.

---

## How it works (v2 architecture)

```
data feeds ──▶ deterministic skills ──▶ analyst lenses ──▶ 1 synthesis call
(free APIs)    (pure Python, $0)        (cheap LLM, JSON in)   (writes the report)
```

1. **Skills** (pure Python, zero AI cost): RSI/MACD/Bollinger/ATR/volume
   profile, valuation ratios and quality flags, FRED macro regime, VaR/beta/
   concentration, earnings & IPO calendars, market screening, news digests,
   congressional-trade lookups, position sizing with ATR stops.
2. **Analyst lenses** (one cheap LLM call each): Macro, Fundamentals,
   Technicals & Options, News & Catalysts, Risk, Order Book & Liquidity, ML
   Alpha. Each receives only compact JSON from the skills and is prompt-bound
   to **never invent a number** — missing data is reported as missing.
   Lenses with no feasible free data feed stay disabled (not deleted) until
   one exists — shown as off in every report's Coverage section, costing
   zero tokens.
3. **Synthesis** (one better-tier call): merges the lenses into a
   decision-ready report — verdict, recommendation table, per-lens case,
   explicit conflicts, and a coverage section listing what the report could
   *not* see.

A full portfolio report costs a few cents, not tens of dollars: ~15–30K
tokens versus the ~300K of the old 33-agent pipeline. Identical re-runs
within 24h are served from a local cache for free, and a cost meter tracks
every call.

---

## Quickstart (first time on this computer)

1. **Install Python** ([python.org/downloads](https://www.python.org/downloads/),
   tick **"Add Python to PATH"** on Windows) and **Node.js**
   ([nodejs.org](https://nodejs.org)) for the web interface.
2. **Download this project** — green **Code** button → **Download ZIP**,
   unzip (or `git clone`).
3. **Run the setup wizard:**
   - **Windows:** double-click `start.bat`
   - **Mac/Linux:** run `./start.sh`

The wizard checks Python, installs dependencies, walks you through the free
API keys (all optional), builds the web UI, and offers to launch.

**Already set up?** `python run.py` — the app opens in your browser at
`http://127.0.0.1:8000`.

---

## What you'll be asked for

Every key is **optional** — the app runs with zero keys; what changes is
what works:

| Key | What it unlocks | Cost |
|---|---|---|
| Gemini or Claude (or OpenAI) | The analyst lenses + report writer | Gemini has a free tier; Claude is paid-per-use |
| Finnhub | News, earnings/IPO calendars, fundamentals fallback | Free tier |
| Alpha Vantage | News with per-ticker sentiment scores | Free tier |
| FRED | US macro data (works keyless too, a key is just politer) | Free |
| moomoo / IBKR / Tiger (no API key) | Live positions & prices from your broker | Free |

With no keys at all you still get: live prices and charts (Yahoo), the full
deterministic dashboard (position guidance, risk metrics, screening), and
broker sync. You need one LLM key for AI reports.

---

## Presets

Ten one-click report configurations, e.g.:

- **Lite** — fast core read of your portfolio (fundamentals + technicals + risk)
- **Portfolio Medic** — full health check on existing holdings
- **Opportunist** — scan the broad market for new setups (US/SG/HK/JP/KR universes)
- **Macro Pulse** — rates/FX/regime backdrop only
- **Dragon Watch / Sakura Signal / Kimchi Premium** — HK / JP / KR region scans
- **Quant Lab** — signals and risk, minimal narrative
- **Insider Edge** — congressional trading disclosures + news + catalysts

---

## MCP server (use AlphaMaxxin from any AI agent)

The deterministic skills are also exposed as read-only [MCP](https://modelcontextprotocol.io)
tools, so Claude Code / Claude Desktop / any MCP client can query your live
portfolio, technicals, macro snapshot, conviction ledger, and backtest results
directly. From the `backend/` directory:

```
claude mcp add alphamaxxin -- py -m app.mcp_server
```

Every tool is read-only and free (computed data from the cached feeds).
Nothing that spends LLM money or mutates state is exposed — report runs and
portfolio edits stay in the app.

---

## Linking your broker

`Portfolio.md` is what the analysis reads. Edit it in the app's Portfolio
tab, or let **⇄ Sync Brokers** rebuild it from live positions. Each broker
is independent — configure any subset.

### Moomoo (live)
No API key. Install and log into moomoo's [OpenD](https://www.moomoo.com/download/OpenAPI)
gateway, then set `MOOMOO_HOST`/`MOOMOO_PORT` in `.env` if you changed
OpenD's defaults (127.0.0.1:11111).

### Interactive Brokers / IBKR (live)
No API key. Requires **TWS** or **IB Gateway** running and logged in, with
**Configuration → API → Settings → "Enable ActiveX and Socket Clients"**
checked. Leave **"Read-Only API"** on — AlphaMaxxin only reads positions.
Set `IBKR_HOST`/`IBKR_PORT`/`IBKR_CLIENT_ID` in `.env` if you changed the
defaults (7497 TWS paper / 7496 live / 4002 Gateway paper / 4001 live).

### Tiger Brokers (live)
Requires a free **Tiger Open API** account and RSA keypair — follow
[Tiger's setup guide](https://quant.itigerup.com/openapi/en/python/operation/step1.html),
then set `TIGER_ID`, `TIGER_ACCOUNT`, `TIGER_PRIVATE_KEY_PATH` in `.env`.

### Webull, Robinhood, or any other broker
No stable official API — add positions to `external_holdings.json` instead;
they merge with live brokers (same ticker in two places gets summed
quantity and weighted-average cost):

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

`Portfolio.md` and `external_holdings.json` are gitignored — your real
holdings never leave this machine.

---

## Project layout

```
backend/
  app/skills/     deterministic engines (technicals, risk, macro, options math, …)
  app/data/       providers: Yahoo, Finnhub, Alpha Vantage, FRED, yfinance
                  (disk-cached, rate-limited, offline-tripwired in tests)
  app/brokers/    read-only clients: moomoo, IBKR, Tiger
  app/llm/        router (Claude/Gemini/OpenAI), 6 role prompts,
                  3 disabled-lens specs, response cache, cost meter
  app/reports/    pipeline, presets, storage, HTML rendering, SSE progress
  tests/          offline test suite — fixtures and mocks, zero API calls
frontend/         Vite + React dashboard
run.py            launcher (python run.py)
```

The previous customtkinter desktop app (gui.py/runner.py/agents/) has been
removed; it's preserved at the `v1-legacy` git tag if you ever need it.

## Contributing & testing

The test suite is **fully offline and free to run** — `cd backend &&
python -m pytest`. It never calls LLMs, data providers, or brokers
(a tripwire makes any attempted network fetch fail the test). See
[CONTRIBUTING.md](CONTRIBUTING.md). Licensed under [MIT](LICENSE);
release history in [CHANGELOG.md](CHANGELOG.md).

## Troubleshooting

- **"python not found"** — reinstall from python.org with the PATH box ticked.
- **Browser shows nothing at 127.0.0.1:8000** — the web UI isn't built:
  `cd frontend && npm install && npm run build`, or use the API docs at
  `/docs` meanwhile.
- **Reports don't generate** — you need at least one LLM key
  (Gemini/Claude/OpenAI) in `.env`; re-run setup to add one.
- **No live broker positions** — the broker's gateway app (OpenD / TWS)
  must be running and logged in; prices fall back to Yahoo automatically.
