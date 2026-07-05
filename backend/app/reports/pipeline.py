"""The report pipeline: resolve target → run deterministic skills → run the
preset's enabled analyst lenses in parallel → synthesis → persist.

Everything numeric happens in the skills stage; the LLM stage only receives
the compact JSON the skills produced. Disabled lenses cost nothing and are
reported as such."""
import asyncio
import datetime

from .. import portfolio as pf
from .. import watchlists as wl
from ..llm import analysts as an
from ..skills import (
    technicals, fundamentals as fund_skill, macro as macro_skill, risk as risk_skill,
    news as news_skill, catalysts as cat_skill, screener as screener_skill,
    signals as signals_skill, performance as perf_skill,
    portfolio_construction as pc_skill, options_math, politician_trades as pol_skill,
)
from . import store
from .presets import get_preset


def resolve_target(target: dict) -> tuple[list[dict], str]:
    """→ (holdings, label). Ticker/watchlist targets become synthetic
    holdings (qty 0) so every downstream skill takes the same shape."""
    kind = target.get("kind", "portfolio")
    if kind == "portfolio":
        return pf.parse_portfolio(), "Portfolio"
    if kind == "tickers":
        tickers = target.get("tickers", [])
        holdings = [{"company": t, "ticker": t, "quantity": 0.0,
                     "cost_price": 0.0, "currency": "USD"} for t in tickers]
        return holdings, ", ".join(tickers)
    if kind == "watchlist":
        found = wl.get_watchlist(target.get("watchlist_id", ""))
        if not found:
            raise ValueError("watchlist not found")
        holdings = [{"company": t, "ticker": t, "quantity": 0.0,
                     "cost_price": 0.0, "currency": "USD"}
                    for t in found["tickers"]]
        return holdings, f"Watchlist: {found['name']}"
    raise ValueError(f"unknown target kind '{kind}'")


def _fetch_per_ticker(registry, holdings: list[dict], emit) -> dict:
    """Quotes, OHLCV, and FX for the target tickers — the fetch pass every
    skill reads from."""
    data = {"quotes": {}, "daily": {}, "weekly": {}, "symbols": {}, "fx": {"USD": 1.0}}
    for h in holdings:
        ticker = h["ticker"]
        symbol, _ = registry.yahoo.resolve_symbol(ticker)
        if not symbol:
            continue
        data["symbols"][ticker] = symbol
        quote = registry.yahoo.quote(symbol)
        if quote:
            data["quotes"][ticker] = quote
        data["daily"][ticker] = registry.yahoo.ohlcv(symbol, "1d", "1y")
        data["weekly"][ticker] = registry.yahoo.ohlcv(symbol, "1wk", "2y")
    for ccy in {h.get("currency", "USD") for h in holdings} | \
               {q.get("currency", "USD") for q in data["quotes"].values()}:
        if ccy != "USD":
            rate = registry.yahoo.fx_rate(ccy)
            if rate:
                data["fx"][ccy] = rate
    return data


def _returns_from_daily(daily: dict) -> dict:
    out = {}
    for ticker, bars in daily.items():
        closes = (bars or {}).get("closes", [])
        if len(closes) > 20:
            out[ticker] = [(closes[i] - closes[i - 1]) / closes[i - 1]
                           for i in range(1, len(closes)) if closes[i - 1]]
    return out


def run_skills(registry, preset: dict, holdings: list[dict], emit) -> dict:
    """Execute the preset's deterministic skills. Returns the skills-section
    dict that both the analysts and the report JSON consume."""
    wanted = set(preset["skills"])
    tickers = [h["ticker"] for h in holdings]
    out: dict = {}

    emit("fetch", "Fetching market data", 10)
    fetched = _fetch_per_ticker(registry, holdings, emit)

    if "technicals" in wanted:
        emit("skills", "Computing technicals", 20)
        out["technicals"] = {}
        for t in tickers:
            snap = technicals.compute_snapshot(t, fetched["daily"].get(t),
                                               fetched["weekly"].get(t))
            if snap:
                out["technicals"][t] = snap

    if "fundamentals" in wanted:
        emit("skills", "Computing fundamentals", 28)
        out["fundamentals"] = {}
        for t in tickers:
            symbol = fetched["symbols"].get(t, t)
            yf_raw = registry.yfinance.fundamentals(symbol) if registry.yfinance.available else None
            fh = registry.finnhub.metrics(t) if (yf_raw is None and registry.finnhub.available) else None
            snap = fund_skill.compute_fundamentals(t, yf_raw, fh)
            if snap:
                out["fundamentals"][t] = snap

    if "macro" in wanted:
        emit("skills", "Computing macro snapshot", 34)
        out["macro"] = macro_skill.compute_macro(registry.fred, registry.yahoo,
                                                 regions=preset.get("regions"))

    if "news" in wanted:
        emit("skills", "Fetching and digesting news", 42)
        articles = news_skill.fetch_and_merge(registry, tickers)
        out["news"] = news_skill.digest(articles)

    if "catalysts" in wanted:
        emit("skills", "Building catalyst calendar", 48)
        out["catalysts"] = cat_skill.build_calendar(registry.finnhub, tickers)

    if "screener" in wanted and preset.get("market_scan"):
        emit("skills", "Screening the market", 52)
        out["screen"] = screener_skill.screen(registry.yahoo,
                                              regions=preset.get("regions"))

    if "performance" in wanted:
        out["summary"] = perf_skill.portfolio_summary(
            holdings, fetched["quotes"], fx_rates=fetched["fx"],
            benchmark_quote=registry.yahoo.quote("^GSPC"))

    if "risk" in wanted:
        emit("skills", "Computing risk metrics", 58)
        values_usd = {}
        for h in holdings:
            quote = fetched["quotes"].get(h["ticker"])
            if quote and h.get("quantity"):
                ccy = quote.get("currency", "USD")
                values_usd[h["ticker"]] = (h["quantity"] * quote["price"]
                                           * fetched["fx"].get(ccy, 1.0))
        bench = registry.yahoo.ohlcv("^GSPC", "1d", "1y")
        out["risk"] = risk_skill.compute_risk(
            holdings, values_usd,
            returns=_returns_from_daily(fetched["daily"]),
            benchmark_returns=_returns_from_daily({"^GSPC": bench}).get("^GSPC"),
            sectors={t: s.get("sector") for t, s in out.get("fundamentals", {}).items()
                     if s.get("sector")})

    if "signals" in wanted:
        emit("skills", "Aggregating composite signals", 64)
        out["composites"] = {}
        for t in tickers:
            out["composites"][t] = signals_skill.aggregate(
                t, out.get("technicals", {}).get(t),
                out.get("fundamentals", {}).get(t),
                out.get("news", {}).get("sentiment_by_ticker"),
                out.get("risk"))

    if "portfolio_construction" in wanted and out.get("summary"):
        out["sizing"] = pc_skill.suggest_sizing(out["summary"],
                                                out.get("composites", {}),
                                                out.get("technicals"))

    if "options_math" in wanted and registry.yfinance.available:
        emit("skills", "Summarizing option chains", 68)
        out["options"] = {}
        for t in tickers:
            chain = registry.yfinance.option_chain(fetched["symbols"].get(t, t))
            summary = options_math.chain_summary(chain) if chain else None
            if summary:
                out["options"][t] = summary

    if "politician_trades" in wanted:
        emit("skills", "Checking congressional disclosures", 70)
        provider = pol_skill.PoliticianTradesProvider(registry.yahoo._cache) \
            if hasattr(registry.yahoo, "_cache") else None
        transactions = provider.all_transactions() if provider else \
            {"senate": [], "house": [], "feed_ok": False}
        out["politician_trades"] = pol_skill.recent_trades(transactions, tickers)

    return out


def _fallback_markdown(results: list[dict], synthesis: dict, run_config: dict) -> str:
    """Built when the synthesis call fails, so a run never produces a blank
    report — surfaces exactly what happened instead of a silent empty page."""
    lines = [f"# {run_config['preset']} — {run_config['target_label']}", "",
             "> **Note:** the final synthesis step failed, so this is a "
             "fallback view assembled from whichever analyst lenses "
             f"succeeded. Reason: {synthesis.get('error') or 'unknown'}.", ""]
    any_ok = False
    for r in results:
        lines.append(f"## {r['name']}")
        if r["ok"]:
            any_ok = True
            lines.append(r["narrative_md"])
        else:
            lines.append(f"*Unavailable this run — {r.get('error') or 'no response'}.*")
        lines.append("")
    if not any_ok:
        lines.append("No analyst lens produced usable output this run — check "
                      "that an LLM API key is set in `.env` and the terminal "
                      "log for the specific error.")
    return "\n".join(lines)


def _analyst_payload(role: str, skills: dict, run_config: dict) -> dict:
    common = {"run_config": run_config}
    if role == "macro":
        fx_exposure = (skills.get("risk") or {}).get("currency_exposure")
        return {**common, "macro": skills.get("macro"),
                "portfolio_fx_exposure": fx_exposure}
    if role == "fundamentals":
        return {**common, "fundamentals": skills.get("fundamentals"),
                "screen": skills.get("screen")}
    if role == "technicals_options":
        return {**common, "technicals": skills.get("technicals"),
                "composites": skills.get("composites"),
                "options": skills.get("options"), "screen": skills.get("screen")}
    if role == "news_catalysts":
        return {**common, "news": skills.get("news"),
                "catalysts": skills.get("catalysts"),
                "politician_trades": skills.get("politician_trades")}
    if role == "risk":
        return {**common, "risk": skills.get("risk"),
                "sizing": skills.get("sizing"),
                "composites": skills.get("composites")}
    raise KeyError(role)


async def run_report(registry, config: dict, emit, cache=None, meter=None,
                     run_id: str = "", reports_dir: str | None = None,
                     settings: dict | None = None,
                     transport=None) -> str:
    """Full pipeline. Returns the persisted report id."""
    from ..settings import load_settings
    settings = settings or load_settings()
    preset = get_preset(config.get("preset", "Lite"))
    holdings, target_label = resolve_target(config.get("target", {"kind": "portfolio"}))
    if not holdings:
        raise ValueError("no target tickers — portfolio empty or no tickers given")

    run_config = {"preset": preset["name"], "target_label": target_label,
                  "regions": preset.get("regions"),
                  "market_scan": preset.get("market_scan", False)}

    skills = run_skills(registry, preset, holdings, emit)

    feed_status = registry.feed_status()
    lens_status = an.lens_status(feed_status)
    enabled = {l["id"] for l in lens_status if l["enabled"]}
    roles = [r for r in preset["analysts"] if r in enabled]
    models = {**settings["models"], **config.get("model_overrides", {})}

    emit("analysts", f"Running {len(roles)} analyst lenses", 72)
    kwargs = dict(cache=cache, meter=meter, run_id=run_id)
    if transport:
        kwargs["transport"] = transport
    results = await asyncio.gather(*[
        an.run_analyst(role, _analyst_payload(role, skills, run_config),
                       models.get(role, "gemini-3.5-flash"), **kwargs)
        for role in roles])

    emit("synthesis", "Writing the report", 88)
    synthesis_payload = {
        "analysts": results,
        "composites": skills.get("composites"),
        "summary": skills.get("summary") or {"tickers": [h["ticker"] for h in holdings]},
        "lens_status": lens_status,
        "run_config": run_config,
    }
    synthesis = await an.run_synthesis(
        synthesis_payload, models.get("synthesis", "claude-sonnet-4-6"), **kwargs)
    if not synthesis["ok"]:
        synthesis = {**synthesis,
                    "markdown": _fallback_markdown(results, synthesis, run_config)}

    emit("persist", "Saving report", 96)
    report = {
        "preset": preset["name"],
        "target_label": target_label,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "run_config": run_config,
        "sections": {"skills": skills,
                     "analysts": {r["role"]: r for r in results},
                     "synthesis": synthesis},
        "lens_status": lens_status,
        "costs": meter.run_total(run_id) if meter else {},
        "versions": {"schema": 1},
    }
    return store.save_report(report, reports_dir=reports_dir)
