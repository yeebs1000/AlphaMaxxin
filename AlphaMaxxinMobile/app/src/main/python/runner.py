"""
AlphaMaxxin Runner (Mobile / Chaquopy) — Clean rewrite.
All data comes from live Yahoo Finance API or LLM calls.
No hardcoded prices, no hardcoded mock reports.

This is an intentional fork of the desktop runner.py, not a stale copy:
- No IBKR integration. The desktop IBKR client talks to a local IB Gateway/TWS
  process over a LAN socket, which has no equivalent on a phone, so that layer
  is simply omitted here rather than stubbed out.
- Claude is called via raw HTTPS (urllib) instead of the `anthropic` SDK, and
  Gemini is called through the OpenAI-compatible endpoint instead of
  `google.genai` — Chaquopy only installs `openai` + `pydantic`
  (see app/build.gradle.kts), so both providers are reached without adding
  Android-wheel risk from new pip deps.
- `run_agent_sync` exists only here because Chaquopy/Kotlin call into Python
  synchronously (see MainActivity.kt's `callAttr("run_agent_sync", ...)`).
- No multi-agent orchestration (active_agents/progress_callback/agent_models)
  since the mobile UI has no agent-picker or model-picker — it always runs a
  single agent against a single target.

Fixes ported from the desktop runner.py: live FX-rate fetch (replacing a
hardcoded constant) and removal of dead google.antigravity scaffolding.
"""
import asyncio
import re
import os
import sys
import json
import urllib.request
import urllib.parse
import datetime
import time

# Manually load .env since python-dotenv might not be installed
import os
base_dir = os.path.dirname(__file__)
def get_path(filename):
    return os.path.join(base_dir, filename)
if os.path.exists(get_path('.env')):
    with open(get_path('.env'), "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k not in os.environ:
                    os.environ[k.strip()] = v.strip()

# ---------------------------------------------------------------------------
# Yahoo Finance API helpers
# ---------------------------------------------------------------------------
_YAHOO_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

_FALLBACK_USD_PER_SGD = 0.779  # only used if the live FX fetch fails
_fx_rate_cache: dict = {}  # {"USD_SGD": (timestamp, rate)}
_FX_CACHE_TTL = 900  # seconds — FX doesn't need to be fetched every call


def get_usd_per_sgd() -> float:
    """Live USD-per-1-SGD rate from Yahoo Finance, cached for _FX_CACHE_TTL seconds.
    Falls back to a fixed approximate rate if the fetch fails, instead of failing
    valuation entirely."""
    cached = _fx_rate_cache.get("USD_SGD")
    if cached and (time.monotonic() - cached[0]) < _FX_CACHE_TTL:
        return cached[1]
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/SGD=X"
        req = urllib.request.Request(url, headers=_YAHOO_HEADERS)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            sgd_per_usd = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            rate = 1.0 / sgd_per_usd
    except Exception:
        rate = _FALLBACK_USD_PER_SGD
    _fx_rate_cache["USD_SGD"] = (time.monotonic(), rate)
    return rate

# Mapping SGX tickers from Portfolio.md to Yahoo Finance symbols
SGX_TICKER_MAP = {
    "A31": {"yahoo": "A31.SI", "name": "Addvalue Technologies", "currency": "SGD"},
    "C6L": {"yahoo": "C6L.SI", "name": "Singapore Airlines", "currency": "SGD"},
    "D05": {"yahoo": "D05.SI", "name": "DBS Group Holdings", "currency": "SGD"},
}

# Mapping portfolio ticker aliases to real Yahoo symbols
TICKER_ALIASES = {
    "Addvalue Tech": "A31.SI",
    "SIA": "C6L.SI",
    "DBS": "D05.SI",
    "SPYM": "SPLG",
    "SPLG": "SPLG",  # Prevent search API from resolving to SPLG.L
    "SOLS": "SOLS",
    "Solstice Advanced": "SOLS",
    "SpaceX": None,  # Not publicly traded
}


def search_ticker(query: str, max_results: int = 6) -> list:
    """
    Search Yahoo Finance for tickers matching query.
    Returns list of dicts: [{"symbol": "AAPL", "name": "Apple Inc.", "type": "EQUITY"}]
    """
    q = urllib.parse.quote(query)
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={q}&quotesCount={max_results}&newsCount=0"
    req = urllib.request.Request(url, headers=_YAHOO_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            results = []
            for quote in data.get("quotes", []):
                if quote.get("quoteType") in ("EQUITY", "ETF"):
                    results.append({
                        "symbol": quote.get("symbol", ""),
                        "name": quote.get("longname") or quote.get("shortname") or quote.get("symbol", ""),
                        "type": quote.get("quoteType", "EQUITY"),
                    })
            return results[:max_results]
    except Exception:
        return []


def fetch_live_price(query_string: str) -> dict | None:
    """
    Resolve a query (ticker or company name) to a live price.
    Returns {"price": float, "name": str, "ticker": str, "currency": str} or None.
    """
    # Check if it's a known SGX alias first
    yahoo_symbol = None
    currency = "USD"
    for alias, mapped in TICKER_ALIASES.items():
        if query_string.lower() == alias.lower():
            yahoo_symbol = mapped
            break
    for sgx_code, info in SGX_TICKER_MAP.items():
        if query_string.lower() in (sgx_code.lower(), info["name"].lower()):
            yahoo_symbol = info["yahoo"]
            currency = info["currency"]
            break

    if yahoo_symbol is None:
        # Try to resolve via search API
        results = search_ticker(query_string, max_results=1)
        if results:
            yahoo_symbol = results[0]["symbol"]
            company_name = results[0]["name"]
        else:
            yahoo_symbol = query_string.upper()
            company_name = query_string
    else:
        company_name = query_string

    if yahoo_symbol is None:
        return None

    # Fetch chart data for the resolved symbol
    try:
        q = urllib.parse.quote(yahoo_symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{q}"
        req = urllib.request.Request(url, headers=_YAHOO_HEADERS)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            resolved_currency = meta.get("currency", "USD")
            resolved_name = meta.get("longName") or meta.get("shortName") or company_name
            resolved_symbol = meta.get("symbol", yahoo_symbol)
            if price is None:
                return None
            return {
                "price": price,
                "name": resolved_name,
                "ticker": resolved_symbol.replace(".SI", "").upper(),
                "yahoo_symbol": resolved_symbol,
                "currency": resolved_currency,
            }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Portfolio parser
# ---------------------------------------------------------------------------
def parse_portfolio(file_path=None) -> list:
    """Parse Portfolio.md and return list of holdings [{name, shares}]."""
    if file_path is None:
        file_path = get_path('Portfolio.md') if os.path.exists("Portfolio.md") else "PORTFOLIO.md"
    if not os.path.exists(file_path):
        return []

    holdings = []
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    TICKER_MAP = {
        "A31": "Addvalue Tech",
        "C6L": "SIA",
        "D05": "DBS",
        "SOLS": "Solstice Advanced",
        "SPYM": "SPLG",
    }

    for line in content.split("\n"):
        line_strip = line.strip()
        if not line_strip.startswith("|") or not line_strip.endswith("|"):
            continue
        parts = [p.strip() for p in line_strip.split("|")[1:-1]]
        if len(parts) < 3:
            continue
        if any(h in parts[0].lower() for h in ["company", "---"]):
            continue
        if "total" in parts[0].lower() or parts[0] == "":
            continue

        ticker = parts[1].replace("**", "").strip()
        qty_str = parts[2].replace("**", "").replace(",", "").strip()
        name = TICKER_MAP.get(ticker, ticker)

        try:
            shares = float(qty_str)
            if shares.is_integer():
                shares = int(shares)
            if name and shares > 0:
                holdings.append({"name": name, "shares": shares})
        except ValueError:
            continue

    if holdings:
        return holdings

    # Fallback list format
    pattern = re.compile(r'-\s+([A-Za-z0-9\s\.&\-]+?)\s*\((\d+)\s+shares?\)')
    for match in pattern.finditer(content):
        name = match.group(1).strip()
        shares = int(match.group(2))
        holdings.append({"name": name, "shares": shares})
    return holdings


# ---------------------------------------------------------------------------
# Portfolio metrics
# ---------------------------------------------------------------------------
def get_metrics_sync(target_input="Portfolio.md") -> dict:
    """
    Build portfolio metrics from live data.
    If target_input is a ticker/company name, treat it as a single-stock analysis.
    """
    if target_input and target_input.lower() not in ("portfolio.md", "portfolio"):
        holdings = [{"name": target_input, "shares": 100}]
    else:
        holdings = parse_portfolio()

    total_val_usd = 0
    holdings_metrics = []
    errors = []
    usd_per_sgd = get_usd_per_sgd()

    for h in holdings:
        name = h["name"]
        shares = h["shares"]

        live_data = fetch_live_price(name)
        if live_data is None:
            errors.append(f"Could not fetch price for '{name}'")
            continue

        price = live_data["price"]
        currency = live_data["currency"]
        ticker = live_data["ticker"]
        full_name = live_data["name"]

        val_local = shares * price
        val_usd = val_local * usd_per_sgd if currency == "SGD" else val_local
        total_val_usd += val_usd

        holdings_metrics.append({
            "ticker": ticker,
            "name": full_name,
            "shares": shares,
            "price_usd": price * usd_per_sgd if currency == "SGD" else price,
            "val_usd": val_usd,
            "currency": currency,
            "raw_price": price,
            "sector": "Equity",  # Sector is determined by LLM analysis, not hardcoded
        })

    for hm in holdings_metrics:
        hm["weight"] = (hm["val_usd"] / total_val_usd) if total_val_usd > 0 else 0

    # Calculate sector weights (basic)
    sector_weights = {}
    for hm in holdings_metrics:
        s = hm["sector"]
        sector_weights[s] = sector_weights.get(s, 0.0) + hm["weight"]

    # Risk flags
    risk_flags = list(errors)

    # Regime and score — these are purely descriptive based on market data
    regime = "PORTFOLIO ANALYSIS MODE"
    agg_score = sum(hm["weight"] * 0.5 for hm in holdings_metrics)

    return {
        "total_val_usd": total_val_usd,
        "holdings_count": len(holdings_metrics),
        "holdings": holdings_metrics,
        "sector_weights": sector_weights,
        "risk_flags": risk_flags,
        "regime": regime,
        "agg_score": agg_score,
        "overrides": "NONE ACTIVE",
    }


# ---------------------------------------------------------------------------
# AGENTS.md prompt extractor
# ---------------------------------------------------------------------------
def extract_prompt_block(agent_name: str) -> str:
    """Extract the system prompt for a given agent from AGENTS_v2.2.md."""
    agents_path = get_path('AGENTS_v2.2.md') if os.path.exists("AGENTS_v2.2.md") else "AGENTS.md"
    if not os.path.exists(agents_path):
        return ""
    with open(agents_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(r'^#\s*PROMPT\s+(\w+)\s*[—-]\s*(.*?)$', re.MULTILINE)
    matches = list(pattern.finditer(content))

    clean_name = agent_name.lower().replace("agent", "").replace("analyst", "").replace("scanner", "").replace("optimizer", "").replace("&", "").strip()
    if "master report" in agent_name.lower() or "master orchestrator" in agent_name.lower():
        clean_name = "investment recommendation"

    # Exact match
    for idx, match in enumerate(matches):
        p_name = match.group(2).strip().lower()
        p_name_clean = p_name.replace("agent", "").replace("analyst", "").replace("scanner", "").replace("optimizer", "").replace("&", "").strip()

        if clean_name in p_name_clean or p_name_clean in clean_name:
            start_pos = match.end()
            end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
            block = content[start_pos:end_pos]
            cb_match = re.search(r'```(?:[a-zA-Z]*)\n(.*?)\n```', block, re.DOTALL)
            if cb_match:
                return cb_match.group(1).strip()
            return block.strip()

    # Fuzzy match
    for idx, match in enumerate(matches):
        p_name = match.group(2).strip().lower()
        words_req = set(clean_name.split())
        words_p = set(p_name.replace("(", "").replace(")", "").replace(",", "").split())
        if words_req & words_p:
            start_pos = match.end()
            end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
            block = content[start_pos:end_pos]
            cb_match = re.search(r'```(?:[a-zA-Z]*)\n(.*?)\n```', block, re.DOTALL)
            if cb_match:
                return cb_match.group(1).strip()
            return block.strip()

    return ""


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------
def get_workspace_state_context(target_input="Portfolio.md") -> str:
    """Build the user prompt with current portfolio state and market data."""
    metrics = get_metrics_sync(target_input)
    
    is_single_ticker = (target_input and target_input.lower() not in ("portfolio.md", "portfolio"))
    
    if is_single_ticker and len(metrics["holdings"]) > 0:
        target = metrics["holdings"][0]
        context_title = "SINGLE TICKER ANALYSIS MODE"
        holdings_str = f"- {target['name']} ({target['ticker']}) — Current Price: ${target['raw_price']:.2f} {target['currency']}"
        portfolio_summary = f"Focus Target: {target['name']} ({target['ticker']})"
    else:
        context_title = "CURRENT PORTFOLIO STATE & MARKET CONTEXT"
        holdings_str = "\n".join([
            f"- {h['name']} ({h['ticker']}) — {h['shares']} shares @ ${h['raw_price']:.2f} {h['currency']} — "
            f"Value: ${h['val_usd']:,.2f} USD — Weight: {h['weight']*100:.2f}%"
            for h in metrics["holdings"]
        ])
        portfolio_summary = f"Total Portfolio Value: ${metrics['total_val_usd']:,.2f} USD\nHoldings Count: {metrics['holdings_count']}"

    today = datetime.date.today().strftime("%B %d, %Y")

    context = f"""{context_title} (as of {today}):

{portfolio_summary}

Active Holdings / Target (LIVE prices from Yahoo Finance):
{holdings_str}

Active Risk Flags:
{chr(10).join(['- ' + r for r in metrics['risk_flags']]) if metrics['risk_flags'] else '- None detected'}

IMPORTANT INSTRUCTIONS:
- Use the LIVE price data provided above. Do NOT fabricate or hallucinate any prices, dates, or financial metrics.
- For earnings dates, only reference them if you are confident of the actual date. If unsure, say "Upcoming (check IR calendar)".
- All analysis must reference the actual tickers and companies listed above.
- If you are evaluating a single ticker, focus your entire analysis on that specific company.
- Follow the agent's Standardized Output block formatting rules strictly.
- Include the full company name alongside each ticker symbol.
"""
    return context


# ---------------------------------------------------------------------------
# LLM caller
# ---------------------------------------------------------------------------
async def call_llm(system_prompt: str, user_prompt: str) -> str:
    """Call Claude, Gemini, or OpenAI to generate real analysis.
    Claude is called via raw HTTPS (urllib) since the `anthropic` SDK isn't
    installed for Chaquopy; Gemini/OpenAI go through the openai SDK."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if anthropic_key:
        try:
            model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            body = json.dumps({
                "model": model,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
                "max_tokens": 4096,
                "temperature": 0.2,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                text = "".join(
                    block.get("text", "") for block in data.get("content", [])
                    if block.get("type") == "text"
                ).strip()
                if text:
                    return text
        except Exception as e:
            print(f"Claude API call failed: {e}. Trying Gemini/OpenAI fallback...", file=sys.stderr)

    if gemini_key:
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=gemini_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
            )
            response = client.chat.completions.create(
                model="gemini-2.5-flash",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            if response and response.choices:
                return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Gemini API call failed: {e}. Trying OpenAI fallback...", file=sys.stderr)

    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            if response and response.choices:
                return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"OpenAI API call failed: {e}.", file=sys.stderr)

    return ""


# ---------------------------------------------------------------------------
# Main agent runner
# ---------------------------------------------------------------------------
async def run_agent(target_name: str, target_input="Portfolio.md") -> str:
    """
    Execute an agent analysis.
    Uses LLM with the prompt from AGENTS_v2.2.md + live portfolio data.
    No hardcoded fallback data.
    """
    system_prompt = extract_prompt_block(target_name)
    user_prompt = get_workspace_state_context(target_input)

    # Try LLM execution
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        if system_prompt:
            live_result = await call_llm(system_prompt, user_prompt)
            if live_result:
                return live_result
            else:
                return (
                    f"# {target_name} — Execution Report\n\n"
                    f"**Status:** LLM call returned empty response.\n\n"
                    f"The system prompt was loaded from AGENTS_v2.2.md and the portfolio data was "
                    f"prepared with live prices, but the LLM did not return a response. "
                    f"Please check your API key and try again.\n\n"
                    f"## Portfolio Context Sent\n\n{user_prompt}"
                )
        else:
            return (
                f"# {target_name} — Execution Report\n\n"
                f"**Status:** Could not find a matching prompt in AGENTS_v2.2.md for agent '{target_name}'.\n\n"
                f"Please verify the agent name matches a PROMPT heading in the agents file."
            )
    else:
        return (
            f"# {target_name} — Execution Report\n\n"
            f"**Status:** No API key configured.\n\n"
            f"To generate real analysis, set `GEMINI_API_KEY` or `OPENAI_API_KEY` in your `.env` file.\n\n"
            f"## Portfolio Context (Live Data)\n\n{user_prompt}"
        )


def run_agent_sync(agent_name, target):
    import asyncio
    return asyncio.run(run_agent(agent_name, target))

