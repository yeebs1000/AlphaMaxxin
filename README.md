# AlphaMaxxin

**English** · [简体中文](README.zh-CN.md)

[![CI](https://github.com/yeebs1000/AlphaMaxxin/actions/workflows/ci.yml/badge.svg)](https://github.com/yeebs1000/AlphaMaxxin/actions/workflows/ci.yml) ![License](https://img.shields.io/badge/license-MIT-blue) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Read--only](https://img.shields.io/badge/broker%20access-read--only-brightgreen)

A local investment research workbench. Python computes metrics for
technicals, fundamentals, macro, risk, and catalysts from data feeds, and
AI "analyst lenses" interpret the supplied context into a structured
research report on your **portfolio**, any **ticker**, or a
**watchlist**. Broker positions sync live from moomoo / IBKR / Tiger.

**Project status:** experimental research software. Scores and sizing rules
are heuristics; model results and AI reports need independent verification.
See [research limitations](RESEARCH_LIMITATIONS.md) for the current gaps.

**Want just the skills?** [Download the standalone pack](https://github.com/yeebs1000/AlphaMaxxin/releases/download/skills-v0.1.0/alphamaxx-skills.zip)
or [give this install guide to Codex or Claude Code](INSTALL_SKILLS.md).

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
   Alpha. Each receives compact JSON from the skills and is prompted to
   report missing data and use the supplied numbers. AI output still needs
   verification against its sources.
   Lenses with no feasible free data feed stay disabled (not deleted) until
   one exists — shown as off in every report's Coverage section, costing
   zero tokens.
3. **Synthesis** (one call): proposes structured actions. Code validates ticker,
   action, conviction, size, stop ordering and distress vetoes, then renders
   the numeric recommendation table from computed inputs. Invalid responses
   produce a mechanical fallback. Free model prose is stored separately as
   `commentary_md` in the report JSON and remains unverified.

Report cost depends on the selected models, enabled lenses, and provider
pricing. Identical re-runs within 24h use a local response cache, and a cost
meter estimates usage for provider calls.

---

## Research skills for Codex and Claude Code

Ten reusable research skills live in [`.agents/skills`](.agents/skills/README.md),
covering macro, fundamentals, market signals, catalysts, quant validation,
and portfolio risk. Install the [standalone pack](INSTALL_SKILLS.md) without
setting up the app. In Codex, use `$alpha-macro` or `$alpha-research`; the Claude
Code plugin exposes `/alphamaxx-research:alpha-macro` and
`/alphamaxx-research:alpha-research`. These are agent research instructions;
the app's Python analytics and analyst pipeline run separately.

---

## Quickstart (first time on this computer)

1. **Install Python 3.11 or newer** ([python.org/downloads](https://www.python.org/downloads/),
   tick **"Add Python to PATH"** on Windows) and **Node.js**
   ([nodejs.org](https://nodejs.org), version 24) for the web interface.
2. **Download this project** — green **Code** button → **Download ZIP**,
   unzip (or `git clone`).
3. **Run the setup wizard:**
   - **Windows:** double-click `start.bat`
   - **Mac/Linux:** run `bash start.sh`

The wizard creates a project `.venv`, installs dependencies there, walks you
through optional API keys and broker SDKs, builds the web UI with `npm ci`,
and offers to launch. Installation/build failures stop setup. Existing
configuration and holdings are preserved. The launcher reuses `.venv`.

Fresh model settings follow your configured provider. All nine analyst roles
and synthesis support editable model IDs, including OpenAI and `local/...`;
saved choices take precedence. Set `LOCAL_LLM_MODEL` for a custom local default.

Try the [synthetic sample report](examples/offline-report.html), or regenerate it
with `.venv` Python:

```powershell
.venv\Scripts\python.exe scripts/demo_report.py
```

On macOS/Linux use `.venv/bin/python scripts/demo_report.py`. This uses synthetic
dated prices and canned analyst responses, makes no network/model/broker calls,
and writes to `data_store/demo/`. Open its `offline-report.html` in your browser.
It demonstrates software behavior, not investment performance.

Broker sync replaces the book only when every explicitly selected source
succeeds. Select all brokers whose holdings belong in that replacement;
selecting none intentionally produces an external-holdings-only book. A failed
selected source preserves the saved book. Missing price/FX data withholds sizing
and history snapshots; dashboard values are then labeled as priced subtotals.

**Already set up?** `python run.py` — the app opens in your browser at
`http://127.0.0.1:8000`.

The launcher binds to localhost. This is a personal desktop web app with
an unauthenticated API, not an internet service; keep it on your own machine.
See [Security and data handling](SECURITY.md) for the supported boundary.

---

## What you'll be asked for

Every key is **optional** — the app runs with zero keys; what changes is
what works:

| Key | What it unlocks | Cost |
|---|---|---|
| Gemini, Claude, or OpenAI | The analyst lenses + report writer | Provider pricing and quotas apply |
| Local OpenAI-compatible model endpoint | The analyst lenses + report writer | Depends on your local setup |
| Finnhub | News, earnings/IPO calendars, fundamentals fallback | Free tier |
| Alpha Vantage | News with per-ticker sentiment scores | Free tier |
| FRED | US macro data (works keyless too, a key is just politer) | Free |
| moomoo / IBKR / Tiger (no API key) | Live positions & prices from your broker | Free |

With no keys at all you still get: live prices and charts (Yahoo), the full
deterministic dashboard (position guidance, risk metrics, screening), and
broker sync, subject to provider availability and broker setup. AI reports
need a configured cloud provider or local model endpoint.

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

The MCP tools do not place trades, edit holdings, or start LLM report runs.
Queries can fetch live data and expose portfolio details to the connected
MCP client; provider access and entitlement rules still apply. Live queries
may refresh local data caches. The conviction ledger query computes a
current snapshot without changing the saved ledger.

---

## Linking your broker

`Portfolio.md` is what the analysis reads. Edit it in the app's Portfolio
tab, or let **⇄ Sync Brokers** rebuild it from live positions. Each broker
is independent — configure any subset.

### Moomoo (live)
No API key. Install and log into moomoo's [OpenD](https://www.moomoo.com/download/OpenAPI)
gateway, then set `MOOMOO_HOST`/`MOOMOO_PORT` in `.env` if you changed
OpenD's defaults (127.0.0.1:11111).

AlphaMaxxin uses the Python SDK directly; vendor agent skills are not
required or bundled. If you want those separate tools, follow the official
[Moomoo Agent Hub installation guide](https://github.com/MoomooOpen/moomoo-agent-hub#quick-start)
and install them in your personal agent setup. Those tools support order
placement, modification, and cancellation; they are outside AlphaMaxxin's
read-only broker integration. See [Third-party notices](THIRD_PARTY_NOTICES.md).

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

`Portfolio.md`, `external_holdings.json`, `.env`, generated reports, and
`data_store/` are gitignored to keep personal data out of normal commits.
This does not prevent network transmission: data providers receive market
queries, and cloud AI reports send computed context that can include your
holdings, quantities, costs, values, and portfolio weights to the selected
LLM provider. A local model endpoint processes that context at the address
you configure. See [Security and data handling](SECURITY.md).

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

The backend suite runs offline with fixtures and mocks; real provider calls
are blocked by `ALPHAMAXXIN_OFFLINE=1`:

```sh
cd backend
python -m pytest -q
```

From the repository root, `python run.py --check` verifies an offline app
boot. The frontend build is `npm ci` followed by `npm run build` from
`frontend/` (use `npm.cmd` in Windows PowerShell). Installing dependencies
requires network access; these checks do not verify live broker connections
or model responses. Routine development and CI do not use paid APIs. See
[CONTRIBUTING.md](CONTRIBUTING.md).

Original project code is licensed under [MIT](LICENSE). Dependencies and
optional vendor tools retain their own licenses; see
[Third-party notices](THIRD_PARTY_NOTICES.md). Release history is in
[CHANGELOG.md](CHANGELOG.md).

## Troubleshooting

- **"python not found"** — reinstall from python.org with the PATH box ticked.
- **Browser shows nothing at 127.0.0.1:8000** — the web UI isn't built:
  `cd frontend && npm install && npm run build`, or use the API docs at
  `/docs` meanwhile.
- **Reports don't generate** — configure a cloud LLM key
  (Gemini/Claude/OpenAI) in `.env`, or set `LOCAL_LLM_BASE_URL` and select
  a `local/...` model in Settings; re-run setup to change the configuration.
- **No live broker positions** — the broker's gateway app (OpenD / TWS)
  must be running and logged in; prices fall back to Yahoo automatically.
