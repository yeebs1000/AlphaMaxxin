"""
AlphaMaxxin Runner — Clean rewrite.
All data comes from live Yahoo Finance API or LLM calls.
No hardcoded prices, no hardcoded mock reports.
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

# News intelligence layer
try:
    from news_fetcher import get_news_context_for_portfolio
    _NEWS_AVAILABLE = True
except ImportError:
    _NEWS_AVAILABLE = False
    def get_news_context_for_portfolio(tickers, max_articles=20):
        return ""

# Moomoo live market data layer (subscribed feed) — optional, falls back to Yahoo Finance
try:
    from moomoo_client import (
        get_moomoo_quote, get_moomoo_industry, get_moomoo_analyst_consensus,
        MOOMOO_AVAILABLE as _MOOMOO_AVAILABLE,
    )
except ImportError:
    _MOOMOO_AVAILABLE = False
    def get_moomoo_quote(ticker):
        return None
    def get_moomoo_industry(ticker):
        return None
    def get_moomoo_analyst_consensus(ticker):
        return None

# Real technical indicator calculation (RSI/MACD/MAs/Bollinger/volume profile)
# — optional, the Technical Analysis Agent just gets no real-data block if missing.
try:
    from technical_indicators import get_technical_snapshot, format_technical_context
    _TECHNICAL_INDICATORS_AVAILABLE = True
except ImportError:
    _TECHNICAL_INDICATORS_AVAILABLE = False

# Broad-market candidate universe for the Screener agent — optional, the
# Screener just falls back to scanning from its own knowledge if missing.
try:
    from market_screener import get_market_candidates, format_market_screening_context
    _MARKET_SCREENER_AVAILABLE = True
except ImportError:
    _MARKET_SCREENER_AVAILABLE = False


# Manually load .env since python-dotenv might not be installed
if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
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

    # Prefer the subscribed Moomoo live feed when OpenD is reachable.
    if _MOOMOO_AVAILABLE:
        moomoo_symbol = yahoo_symbol.replace(".SI", "")
        moomoo_data = get_moomoo_quote(moomoo_symbol)
        if moomoo_data is not None:
            moomoo_data["name"] = company_name
            return moomoo_data

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
                
            prev_close = meta.get("previousClose") or meta.get("chartPreviousClose") or price
            change_pct = 0.0
            if prev_close:
                change_pct = ((price - prev_close) / prev_close) * 100
                
            return {
                "price": price,
                "name": resolved_name,
                "ticker": resolved_symbol.replace(".SI", "").upper(),
                "yahoo_symbol": resolved_symbol,
                "currency": resolved_currency,
                "previous_close": prev_close,
                "change_pct": change_pct,
            }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Portfolio parser
# ---------------------------------------------------------------------------
def parse_portfolio(file_path=None) -> list:
    """Parse Portfolio.md and return list of holdings [{name, shares}]."""
    if file_path is None:
        file_path = "Portfolio.md" if os.path.exists("Portfolio.md") else "PORTFOLIO.md"
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

        # Real industry classification from moomoo's plate data when available
        # (cached, so this is a no-op lookup after the first call per ticker);
        # "Equity" is a deliberate fallback, not a stand-in for real analysis —
        # sector/industry weighting still differs per holding when moomoo has data.
        industry = get_moomoo_industry(ticker) or "Equity"

        holdings_metrics.append({
            "ticker": ticker,
            "name": full_name,
            "shares": shares,
            "price_usd": price * usd_per_sgd if currency == "SGD" else price,
            "val_usd": val_usd,
            "currency": currency,
            "raw_price": price,
            "sector": industry,
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
AGENTS_FILE = "AGENTS_v3.0.md"


def extract_prompt_block(agent_name: str, file_path=None) -> str:
    """Extract the system prompt for a given agent from AGENTS_FILE."""
    agents_path = file_path if file_path is not None else AGENTS_FILE
        
    if not os.path.exists(agents_path):
        return ""
    with open(agents_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(r'^#\s*PROMPT\s+(\w+)\s*[—-]\s*(.*?)$', re.MULTILINE)
    matches = list(pattern.finditer(content))

    clean_name = agent_name.lower().replace("agent", "").replace("analyst", "").replace("scanner", "").replace("optimizer", "").replace("&", "").strip()

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
def get_workspace_state_context(target_input="Portfolio.md", active_agents=None) -> str:
    """Build the user prompt with current portfolio state, market data, and live news."""
    metrics = get_metrics_sync(target_input)
    
    is_single_ticker = (target_input and target_input.lower() not in ("portfolio.md", "portfolio"))
    
    def _analyst_suffix(ticker: str) -> str:
        """Appends moomoo analyst consensus (target price, buy/hold/sell split)
        to a holding line when available — grounds agents like the Investment
        Recommendation Agent in real coverage instead of LLM-only judgment."""
        consensus = get_moomoo_analyst_consensus(ticker)
        if not consensus or not consensus.get("analyst_count"):
            return ""
        return (
            f" — Analyst Consensus: {consensus['analyst_count']} analysts, "
            f"Buy {consensus['buy_pct']:.0f}% / Hold {consensus['hold_pct']:.0f}% / Sell {consensus['sell_pct']:.0f}%, "
            f"Avg Target ${consensus['target_avg']:.2f} (range ${consensus['target_low']:.2f}-${consensus['target_high']:.2f})"
        )

    if is_single_ticker and len(metrics["holdings"]) > 0:
        target = metrics["holdings"][0]
        context_title = "SINGLE TICKER ANALYSIS MODE"
        holdings_str = (
            f"- {target['name']} ({target['ticker']}) — Current Price: ${target['raw_price']:.2f} {target['currency']}"
            f" — Industry: {target['sector']}{_analyst_suffix(target['ticker'])}"
        )
        portfolio_summary = f"Focus Target: {target['name']} ({target['ticker']})"
        news_tickers = [target['ticker']]
    else:
        context_title = "CURRENT PORTFOLIO STATE & MARKET CONTEXT"
        holdings_str = "\n".join([
            f"- {h['name']} ({h['ticker']}) — {h['shares']} shares @ ${h['raw_price']:.2f} {h['currency']} — "
            f"Value: ${h['val_usd']:,.2f} USD — Weight: {h['weight']*100:.2f}% — Industry: {h['sector']}"
            f"{_analyst_suffix(h['ticker'])}"
            for h in metrics["holdings"]
        ])
        portfolio_summary = f"Total Portfolio Value: ${metrics['total_val_usd']:,.2f} USD\nHoldings Count: {metrics['holdings_count']}"
        news_tickers = [h['ticker'] for h in metrics['holdings']]

    today = datetime.date.today().strftime("%B %d, %Y")

    context = f"""{context_title} (as of {today}):

{portfolio_summary}

Active Holdings / Target (LIVE prices — Moomoo subscribed feed where entitled, Yahoo Finance fallback otherwise):
{holdings_str}

Active Risk Flags:
{chr(10).join(['- ' + r for r in metrics['risk_flags']]) if metrics['risk_flags'] else '- None detected'}
"""

    if active_agents:
        active_agents_list = "\n".join([f"- {a}" for a in active_agents])
        context += f"""
Active Sub-Agents Enabled for this Run:
{active_agents_list}
"""

    # ── Inject live news intelligence ──────────────────────────────────────────
    has_finnhub = bool(os.environ.get("FINNHUB_API_KEY", "").strip())
    has_av = bool(os.environ.get("ALPHAVANTAGE_API_KEY", "").strip())

    if _NEWS_AVAILABLE and (has_finnhub or has_av) and news_tickers:
        try:
            news_digest = get_news_context_for_portfolio(news_tickers, max_articles=25)
            if news_digest and len(news_digest) > 50:
                context += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LIVE NEWS INTELLIGENCE (as of {today})
Source: Finnhub / Alpha Vantage / Yahoo Finance
Sentiment: 📈 Bullish | 📉 Bearish | ➖ Neutral
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{news_digest}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        except Exception as e:
            context += f"\n[News Intelligence: fetch failed — {e}]\n"

    context += """
IMPORTANT INSTRUCTIONS:
- Use the LIVE price data provided above. Do NOT fabricate or hallucinate any prices, dates, or financial metrics.
- Use the LIVE NEWS INTELLIGENCE block above to ground your analysis in today's actual headlines and events.
- For earnings dates, only reference them if you are confident of the actual date. If unsure, say "Upcoming (check IR calendar)".
- All analysis must reference the actual tickers and companies listed above.
- If you are evaluating a single ticker, focus your entire analysis on that specific company.
- Follow the agent's Standardized Output block formatting rules strictly.
- Include the full company name alongside each ticker symbol.
"""
    return context


# Caps how many tickers get a real technical snapshot computed per run — this
# is a non-LLM network fetch (Yahoo/moomoo), but still sequential, so a huge
# portfolio doesn't add a long, uncapped delay before the Technical Analysis
# Agent's LLM call even starts.
_MAX_TECHNICAL_TICKERS = 12


def get_technical_context_block(target_input="Portfolio.md") -> str:
    """Real computed RSI/MACD/Moving-Average/Bollinger/volume-profile data for
    the active ticker(s), for injection into the Technical Analysis Agent's
    prompt only — other agents don't need this and it would just add tokens
    to every sub-agent call for no benefit."""
    if not _TECHNICAL_INDICATORS_AVAILABLE:
        return ""
    metrics = get_metrics_sync(target_input)
    tickers = [h["ticker"] for h in metrics["holdings"][:_MAX_TECHNICAL_TICKERS]]
    blocks = []
    for ticker in tickers:
        try:
            snap = get_technical_snapshot(ticker)
        except Exception:
            snap = None
        if snap:
            blocks.append(format_technical_context(snap))
    return "\n".join(blocks)


def get_market_screening_context_block() -> str:
    """Real-data broad-market candidate universe (US non-mega-cap, SGX, HKEX)
    for injection into the Screener agent's prompt only — every other agent
    stays focused on the user's own holdings."""
    if not _MARKET_SCREENER_AVAILABLE:
        return ""
    try:
        candidates = get_market_candidates()
    except Exception:
        return ""
    return format_market_screening_context(candidates)


# ---------------------------------------------------------------------------
# LLM caller
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "gemini-3.5-flash"  # cheap default tier when no agent_models mapping is supplied


async def call_llm(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Call Claude, Gemini, or OpenAI depending on which model was selected for this agent/layer."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if "claude" in model.lower():
        if not anthropic_key:
            return "\n> [Claude unavailable] No ANTHROPIC_API_KEY set in .env.\n"
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=anthropic_key)
        # One retry on transient overload/rate-limit errors (Anthropic 429/529) rather
        # than silently dropping the sub-agent's contribution — a Master Orchestrator
        # run fans out ~30 of these concurrently (see _SUBAGENT_CONCURRENCY below),
        # which is exactly the kind of burst that triggers transient provider errors.
        for attempt in range(2):
            try:
                response = await client.messages.create(
                    model=model,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    max_tokens=8192,
                    temperature=0.2,
                )
                if response and response.content:
                    return "".join(block.text for block in response.content if block.type == "text").strip()
                return ""
            except Exception as e:
                status = getattr(e, "status_code", None)
                if attempt == 0 and status in (429, 529):
                    await asyncio.sleep(2.0)
                    continue
                print(f"Claude API call failed: {e}.", file=sys.stderr)
                return ""
        return ""

    if gemini_key:
        import google.genai as genai
        from google.genai import types
        client = genai.Client(api_key=gemini_key)
        # google-genai's Client is synchronous — a blocking call here would
        # freeze the whole asyncio event loop for the duration of the network
        # round-trip, making every "concurrent" sub-agent run strictly one at
        # a time despite asyncio.gather. asyncio.to_thread() runs it in a
        # worker thread instead, so the loop stays free to run other agents'
        # coroutines while this one waits on the network.
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
            ),
        )
        if response and response.text:
            return response.text.strip()

    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            # Same blocking-client issue as Gemini above — offload to a thread.
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=model if "gpt" in model else "gpt-4o-mini",
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


# Caps how many sub-agent LLM calls run at once during a Master Orchestrator
# fan-out. Without this, selecting all 32 agents fires ~30 concurrent requests
# at the same provider, which is exactly the burst pattern that triggers real
# 429/529 rate-limit errors — previously silently dropped (empty sub-report)
# and then papered over by the orchestrator inventing a plausible-sounding
# excuse for the gap. Fixing the burst is the real fix; the prompt-level rule
# (see AGENTS_v3.0.md) is to never fabricate a cause for missing data either way.
#
# None of the 32 sub-agents depend on another sub-agent's output (each only
# receives Portfolio.md/news context — see get_workspace_state_context) — the
# fan-out below is already maximally parallel in that sense. The real lever
# left is the cap itself: one global semaphore throttles every provider to
# the same limit, even though Gemini (the default per-agent tier) tolerates
# far more concurrent traffic than Claude before rate-limiting. Splitting the
# cap per-provider lets the Gemini-tier majority of agents run with much less
# queuing, while keeping Claude-tier agents (usually just the synthesis call)
# at the conservative limit that avoids 429/529s.
_PROVIDER_CONCURRENCY = {"claude": 4, "gemini": 12, "openai": 8}
_DEFAULT_CONCURRENCY = 6
_provider_semaphores: dict[str, asyncio.Semaphore] = {
    provider: asyncio.Semaphore(limit) for provider, limit in _PROVIDER_CONCURRENCY.items()
}


def _semaphore_for_model(model: str) -> asyncio.Semaphore:
    model_lower = (model or "").lower()
    for provider, semaphore in _provider_semaphores.items():
        if provider in model_lower:
            return semaphore
    return _provider_semaphores.setdefault(
        "_default", asyncio.Semaphore(_DEFAULT_CONCURRENCY)
    )


# ---------------------------------------------------------------------------
# Main agent runner
# ---------------------------------------------------------------------------
async def run_agent(
    target_name: str,
    target_input="Portfolio.md",
    active_agents=None,
    progress_callback=None,
    agent_models=None
) -> str:
    """
    Execute an agent analysis.
    Uses LLM with the prompt from AGENTS_v3.0.md + live portfolio data.
    active_agents: if provided AND target_name is Master Orchestrator, ONLY those agents run.
    progress_callback: optional callable(agent_name, status) for live GUI feedback.
    """
    # Determine which model to run for this agent/layer — resolved up-front so both
    # the Master Orchestrator branch and the single-agent branch below have it set.
    current_model = DEFAULT_MODEL
    if agent_models and target_name in agent_models:
        current_model = agent_models[target_name]

    if target_name == "Master Orchestrator" and active_agents:
        total = len(active_agents)

        async def run_one(agent, idx):
            if progress_callback:
                progress_callback(agent, f"Starting ({idx+1}/{total})...")
            agent_model = (agent_models or {}).get(agent, DEFAULT_MODEL)
            async with _semaphore_for_model(agent_model):
                result = await run_agent(agent, target_input, agent_models=agent_models)  # sub-agent has NO active_agents
                if not result:
                    # Empty result = the call failed even after call_llm's own retry.
                    # One more attempt, after a short stagger, before accepting the gap.
                    await asyncio.sleep(1.5)
                    result = await run_agent(agent, target_input, agent_models=agent_models)
            if progress_callback:
                progress_callback(agent, f"Done ({idx+1}/{total})")
            return result

        # Run sub-agents concurrently — only the selected ones
        tasks = [run_one(agent, i) for i, agent in enumerate(active_agents)]
        reports = await asyncio.gather(*tasks)

        # Format sub-reports with clear headers
        sub_reports = []
        for agent, report in zip(active_agents, reports):
            sub_reports.append(f"=== REPORT FROM SUB-AGENT: {agent} ===\n{report}\n")
        sub_reports_text = "\n".join(sub_reports)

        system_prompt = extract_prompt_block(target_name)
        workspace_context = get_workspace_state_context(target_input, active_agents=active_agents)
        user_prompt = f"{workspace_context}\n\n{sub_reports_text}"

        if progress_callback:
            progress_callback("Master Orchestrator", "Synthesizing all sub-agent reports...")
    else:
        system_prompt = extract_prompt_block(target_name)
        # Build prompt
        prompt = get_workspace_state_context(target_input)
        if target_name == "Technical Analysis Agent":
            technical_block = get_technical_context_block(target_input)
            if technical_block:
                prompt += f"\n\n{technical_block}"
        elif target_name == "High-Conviction Stock & Options Screener":
            market_block = get_market_screening_context_block()
            if market_block:
                prompt += f"\n\n{market_block}"
        prompt += f"\n\nYOUR TASK:\nExecute your designated role as '{target_name}'. Target: {target_input}."

    # Now execute the LLM if we have a prompt
    if system_prompt:
        has_key_for_model = (
            ("claude" in current_model.lower() and os.environ.get("ANTHROPIC_API_KEY"))
            or ("claude" not in current_model.lower() and (os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")))
        )
        if has_key_for_model:
            try:
                # `user_prompt` is used in the final print statement, so define it here if not defined
                user_prompt = prompt if 'prompt' in locals() else user_prompt 
                return await call_llm(system_prompt, user_prompt, model=current_model)
            except Exception as e:
                return (
                    f"# {target_name} — Execution Report\n\n"
                    f"**Status:** Error executing {target_name} LLM analysis: {e}\n\n"
                    f"Please check your API key and try again."
                )
        else:
            user_prompt = prompt if 'prompt' in locals() else user_prompt
            return (
                f"# {target_name} — Execution Report\n\n"
                f"**Status:** No API key configured for model '{current_model}'.\n\n"
                f"To generate real analysis, set `ANTHROPIC_API_KEY` (for Claude models), or `GEMINI_API_KEY` / `OPENAI_API_KEY` in your `.env` file.\n\n"
                f"## Portfolio Context (Live Data)\n\n{user_prompt}"
            )
    else:
        return (
            f"# {target_name} — Execution Report\n\n"
            f"**Status:** Could not find a matching prompt in AGENTS_v3.0.md for agent '{target_name}'.\n\n"
            f"Please verify the agent name matches a PROMPT heading in the agents file."
        )


# ---------------------------------------------------------------------------
# Full portfolio parser (for GUI editor)
# ---------------------------------------------------------------------------
def parse_portfolio_full(file_path=None) -> list:
    """
    Parse Portfolio.md and return complete holding data including cost prices.
    Returns list of dicts: [{company, ticker, quantity, cost_price, currency, section}]
    """
    if file_path is None:
        file_path = "Portfolio.md" if os.path.exists("Portfolio.md") else "PORTFOLIO.md"
    if not os.path.exists(file_path):
        return []

    holdings = []
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    current_section = "USD"  # Default
    for line in content.split("\n"):
        line_strip = line.strip()

        # Detect section headers
        if "Singapore" in line_strip and "SGD" in line_strip:
            current_section = "SGD"
        elif "US" in line_strip and ("USD" in line_strip or "ETF" in line_strip):
            current_section = "USD"

        if not line_strip.startswith("|") or not line_strip.endswith("|"):
            continue
        parts = [p.strip() for p in line_strip.split("|")[1:-1]]
        if len(parts) < 6:
            continue
        # Skip header rows and separator rows
        if any(h in parts[0].lower() for h in ["company", "---", ":"]):
            continue
        if "total" in parts[0].lower() or parts[0] == "":
            continue

        company = parts[0].replace("**", "").replace("*", "").strip()
        ticker = parts[1].replace("**", "").strip()
        qty_str = parts[2].replace("**", "").replace(",", "").strip()
        # parts[3] = current price (skip, we fetch live)
        cost_str = parts[4].replace("**", "").replace(",", "").strip()

        try:
            quantity = float(qty_str)
            cost_price = float(cost_str) if cost_str else 0.0
            holdings.append({
                "company": company,
                "ticker": ticker,
                "quantity": quantity,
                "cost_price": cost_price,
                "currency": current_section,
            })
        except ValueError:
            continue

    return holdings


# ---------------------------------------------------------------------------
# Free, zero-LLM position guidance heuristic
# ---------------------------------------------------------------------------
def get_position_guidance(file_path=None) -> list:
    """
    Mechanical, zero-LLM-cost per-holding signal for an at-a-glance dashboard
    view. Combines unrealized P&L vs. cost basis (from Portfolio.md), real
    RSI/trend (technical_indicators.get_technical_snapshot), and moomoo
    analyst consensus into a simple score -> Increase/Hold/Trim label.

    This is a rule-based heuristic, not personalized financial advice — for a
    qualitative, reasoned recommendation use the Investment Recommendation
    Agent (e.g. the "Portfolio Medic" preset) on demand instead.

    Returns a list of dicts:
    [{ticker, company, price, cost_price, pnl_pct, rsi14, trend,
      analyst_consensus, score, signal, reasons}, ...]
    """
    holdings = parse_portfolio_full(file_path)
    out = []
    for h in holdings:
        ticker = h["ticker"]
        cost_price = h.get("cost_price") or 0.0

        live = fetch_live_price(ticker) or fetch_live_price(h["company"])
        if live is None:
            continue
        price = live["price"]
        pnl_pct = ((price - cost_price) / cost_price * 100) if cost_price else None

        rsi14 = None
        trend = "Unknown"
        if _TECHNICAL_INDICATORS_AVAILABLE:
            try:
                snap = get_technical_snapshot(ticker)
            except Exception:
                snap = None
            if snap:
                rsi14 = snap.get("rsi14")
                last_close, sma50, sma200 = snap.get("last_close"), snap.get("sma50"), snap.get("sma200")
                if last_close is not None and sma50 is not None and sma200 is not None:
                    if last_close > sma50 > sma200:
                        trend = "Uptrend"
                    elif last_close < sma50 < sma200:
                        trend = "Downtrend"
                    else:
                        trend = "Mixed"

        consensus = get_moomoo_analyst_consensus(ticker)

        score = 0
        reasons = []
        if rsi14 is not None:
            if rsi14 < 30:
                score += 1
                reasons.append(f"RSI {rsi14:.0f} (oversold)")
            elif rsi14 > 70:
                score -= 1
                reasons.append(f"RSI {rsi14:.0f} (overbought)")
        if trend == "Uptrend":
            score += 1
            reasons.append("Price above 50/200-day SMA (uptrend)")
        elif trend == "Downtrend":
            score -= 1
            reasons.append("Price below 50/200-day SMA (downtrend)")
        if consensus and consensus.get("analyst_count"):
            if consensus.get("buy_pct", 0) >= 60:
                score += 1
                reasons.append(f"{consensus['buy_pct']:.0f}% analyst Buy consensus")
            elif consensus.get("sell_pct", 0) >= 40:
                score -= 1
                reasons.append(f"{consensus['sell_pct']:.0f}% analyst Sell consensus")
        if pnl_pct is not None:
            if pnl_pct <= -15:
                reasons.append(f"Underwater {pnl_pct:.1f}% vs. cost basis")
            elif pnl_pct >= 30:
                reasons.append(f"Up {pnl_pct:.1f}% vs. cost basis (extended gain)")

        if score >= 2:
            signal = "Increase / Accumulate"
        elif score == 1:
            signal = "Hold (Mildly Bullish)"
        elif score == 0:
            signal = "Hold"
        elif score == -1:
            signal = "Hold (Mildly Bearish) / Watch"
        else:
            signal = "Trim / Reduce"

        out.append({
            "ticker": ticker,
            "company": h["company"],
            "price": price,
            "cost_price": cost_price,
            "pnl_pct": pnl_pct,
            "rsi14": rsi14,
            "trend": trend,
            "analyst_consensus": consensus,
            "score": score,
            "signal": signal,
            "reasons": reasons,
        })
    return out


# Section heading per currency — extend this when a new currency shows up in
# holdings (e.g. a new market via moomoo) rather than hardcoding SGD/USD only.
_CURRENCY_SECTION_TITLES = {
    "SGD": "🇸🇬 Singapore Equities (SGD)",
    "USD": "🇺🇸 US Equities & ETFs (USD)",
    "HKD": "🇭🇰 Hong Kong Equities (HKD)",
}


def save_portfolio(holdings: list, file_path=None):
    """
    Write holdings list back to Portfolio.md in the standard markdown table format.
    holdings: list of dicts with keys: company, ticker, quantity, cost_price, currency
    Groups holdings into one section per currency present, instead of assuming
    only SGD/USD — any currency moomoo positions carry gets its own section.
    """
    if file_path is None:
        file_path = "Portfolio.md"

    currencies_in_order = []
    for h in holdings:
        ccy = h.get("currency", "USD")
        if ccy not in currencies_in_order:
            currencies_in_order.append(ccy)

    today = datetime.date.today().strftime("%B %d, %Y")

    lines = [
        "# Investment Portfolio",
        "",
        f"> **Last Updated:** {today}",
        "",
        "---",
        "",
    ]

    for ccy in currencies_in_order:
        section_holdings = [h for h in holdings if h.get("currency", "USD") == ccy]
        if not section_holdings:
            continue
        title = _CURRENCY_SECTION_TITLES.get(ccy, f"{ccy} Equities")
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| Company | Ticker | Quantity | Current Price | Cost Price | Market Value | Total P/L |")
        lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: |")
        total_val = 0.0
        total_pl = 0.0
        for h in section_holdings:
            qty = h["quantity"]
            cost = h["cost_price"]
            live = fetch_live_price(h["ticker"])
            cur_price = live["price"] if live else cost  # fallback to cost if live fetch fails
            market_val = qty * cur_price
            pl = (cur_price - cost) * qty
            total_val += market_val
            total_pl += pl
            pl_str = f"+{pl:,.2f}" if pl >= 0 else f"{pl:,.2f}"
            qty_str = f"{qty:,.1f}" if qty != int(qty) else f"{int(qty):,}"
            lines.append(f"| **{h['company']}** | {h['ticker']} | {qty_str} | {cur_price:.3f} | {cost:.3f} | {market_val:,.2f} | {pl_str} |")
        pl_total_str = f"+{total_pl:,.2f}" if total_pl >= 0 else f"{total_pl:,.2f}"
        lines.append(f"| **Total ({ccy})** | | | | | **{total_val:,.2f}** | **{pl_total_str}** |")
        lines.append("")
        lines.append("---")
        lines.append("")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Moomoo portfolio sync — auto-generates Portfolio.md from live account
# positions instead of hand-editing it. Brokers moomoo can't see (e.g. IBKR)
# are layered in from external_holdings.json, a small user-maintained data
# file (quantity/cost per ticker) rather than a hardcoded note in the .md.
# ---------------------------------------------------------------------------
_MARKET_CCY = {"US": "USD", "SG": "SGD", "HK": "HKD", "SH": "CNY", "SZ": "CNY", "MY": "MYR", "JP": "JPY"}
EXTERNAL_HOLDINGS_FILE = "external_holdings.json"


def load_external_holdings(file_path=None) -> dict:
    """
    Loads supplementary holdings moomoo doesn't have visibility into (other
    brokers, e.g. IBKR). Returns {} if the file doesn't exist — it's optional.
    Shape: {"TICKER": {"quantity": N, "cost_price": P, "currency": "USD", "company": "...", "broker": "..."}}
    """
    file_path = file_path or EXTERNAL_HOLDINGS_FILE
    if not os.path.exists(file_path):
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def sync_portfolio_from_moomoo(external_path=None, file_path=None) -> dict:
    """
    Rebuilds Portfolio.md from live moomoo positions, merged with
    external_holdings.json for brokers moomoo doesn't cover. Same ticker in
    both sources gets combined (summed quantity, weighted-average cost) so a
    split holding (e.g. 1 share at moomoo + 9 at IBKR) doesn't need a manual note.
    Returns {"success": bool, "holdings": [...], "error": str|None}.
    """
    from moomoo_client import get_moomoo_positions, MOOMOO_AVAILABLE
    if not MOOMOO_AVAILABLE:
        return {"success": False, "holdings": [], "error": "moomoo-api not installed"}

    positions = get_moomoo_positions()
    if positions is None:
        return {"success": False, "holdings": [], "error": "Could not reach moomoo OpenD — is it running and logged in?"}

    merged = {}  # ticker -> holding dict
    for p in positions:
        code = p["code"]  # e.g. "US.VST", "HK.01810"
        market, _, ticker = code.partition(".")
        merged[ticker] = {
            "company": p["name"] or ticker,
            "ticker": ticker,
            "quantity": p["qty"],
            "cost_price": p["average_cost"],
            "currency": _MARKET_CCY.get(market, "USD"),
        }

    for ticker, ext in load_external_holdings(external_path).items():
        ext_qty = float(ext["quantity"])
        ext_cost = float(ext.get("cost_price", 0))
        if ticker in merged:
            existing = merged[ticker]
            total_qty = existing["quantity"] + ext_qty
            existing["cost_price"] = (
                (existing["quantity"] * existing["cost_price"] + ext_qty * ext_cost) / total_qty
                if total_qty else 0.0
            )
            existing["quantity"] = total_qty
        else:
            merged[ticker] = {
                "company": ext.get("company", ticker),
                "ticker": ticker,
                "quantity": ext_qty,
                "cost_price": ext_cost,
                "currency": ext.get("currency", "USD"),
            }

    holdings = list(merged.values())
    save_portfolio(holdings, file_path=file_path)
    return {"success": True, "holdings": holdings, "error": None}
