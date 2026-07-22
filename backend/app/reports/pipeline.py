"""The report pipeline: resolve target → run deterministic skills → run the
preset's enabled analyst lenses in parallel → synthesis → persist.

Everything numeric happens in the skills stage; the LLM stage only receives
the compact JSON the skills produced. Disabled lenses cost nothing and are
reported as such."""
import asyncio
import datetime

import numpy as np

from .. import equity_history
from .. import portfolio as pf
from .. import watchlists as wl
from ..data.live_quote import live_quote, live_ohlcv
from ..llm import analysts as an
from ..skills import (
    technicals, fundamentals as fund_skill, macro as macro_skill, risk as risk_skill,
    news as news_skill, catalysts as cat_skill, screener as screener_skill,
    signals as signals_skill, performance as perf_skill,
    portfolio_construction as pc_skill, options_math, politician_trades as pol_skill,
    order_book as ob_skill, ml_alpha as ml_skill, market_review as mr_skill,
    strategies as strat_skill, insiders as ins_skill, supply_chain as sc_skill,
    dividends as div_skill, alt_data as alt_skill,
    digital_footprint as dfp_skill,
)
from . import ledger, store
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


# Broad-scan region bias: overweight US/SG/HK, keep JP/KR a deliberate
# minority. A region-focused preset (Dragon Watch/Sakura/Kimchi) ignores the
# weights and takes a full slate of its single region.
# ponytail: fixed weights + buckets — tune here if the regional mix drifts.
_SCAN_REGION_WEIGHTS = {"US": 6, "SG": 5, "HK": 5, "JP": 2, "KR": 2}
_SCAN_SINGLE_REGION = 6


def _scan_candidates(registry, preset: dict,
                     settings: dict | None = None) -> tuple[list[dict], dict]:
    """Market-scan presets that screen exist to surface NEW setups, not to
    re-analyze the user's book — so their analysis universe IS the top screened
    candidates, not the resolved target. Broad (multi-region) scans apply the
    region weights so US/SG/HK dominate; single-region presets take a full
    slate. Returns (candidate_holdings, screen). Empty holdings (screener
    returned nothing) means the caller keeps the original target as a fallback.

    Broad scans honor the user's scan_markets toggles (dashboard-settable);
    region-scoped presets (Dragon Watch…) are explicit choices and ignore them."""
    regions = preset.get("regions")
    if not regions:
        toggles = (settings or {}).get("scan_markets") or {}
        regions = [r for r in _SCAN_REGION_WEIGHTS
                   if toggles.get(r, True)] or list(_SCAN_REGION_WEIGHTS)
    single = len(regions) == 1
    screen, holdings = {}, []
    for region in regions:
        cap = _SCAN_SINGLE_REGION if single else _SCAN_REGION_WEIGHTS.get(region, 3)
        part = screener_skill.screen(registry.yahoo, regions=[region], max_per_market=cap)
        screen[region] = part.get(region, [])
        holdings += [{"company": s["ticker"], "ticker": s["ticker"], "quantity": 0.0,
                      "cost_price": 0.0, "currency": "USD"} for s in screen[region]]
    return holdings, screen


def _fetch_per_ticker(registry, holdings: list[dict], emit) -> dict:
    """Quotes, OHLCV, and FX for the target tickers — the fetch pass every
    skill reads from."""
    data = {"quotes": {}, "daily": {}, "weekly": {}, "symbols": {}, "fx": {"USD": 1.0}}
    for h in holdings:
        ticker = h["ticker"]
        symbol, _ = registry.yahoo.resolve_symbol(ticker)
        if symbol:
            data["symbols"][ticker] = symbol
        quote = live_quote(ticker, registry.yahoo)
        if quote:
            data["quotes"][ticker] = quote
        data["daily"][ticker] = live_ohlcv(ticker, registry.yahoo, "1d", "1y")
        data["weekly"][ticker] = live_ohlcv(ticker, registry.yahoo, "1wk", "2y")
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


def run_skills(registry, preset: dict, holdings: list[dict], emit,
               prescreened: dict | None = None) -> dict:
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
            trends = registry.finnhub.recommendation_trends(t) if registry.finnhub.available else None
            snap = fund_skill.compute_fundamentals(t, yf_raw, fh, rec_trends=trends)
            if snap:
                # Piotroski F-score from annual statements (30d-cached) — the
                # YoY-improvement dimension the point-in-time ratios miss.
                if registry.yfinance.available:
                    snap["f_score"] = fund_skill.f_score(
                        registry.yfinance.statements(symbol))
                out["fundamentals"][t] = snap

    if "macro" in wanted:
        emit("skills", "Computing macro snapshot", 34)
        out["macro"] = macro_skill.compute_macro(registry.fred, registry.yahoo,
                                                 regions=preset.get("regions"))

    if "market_review" in wanted:
        emit("skills", "Reviewing the market", 36)
        out["market_review"] = mr_skill.compute_market_review(
            registry.yahoo, regions=preset.get("regions"))

    if "supply_chain" in wanted:
        emit("skills", "Reading supply-chain flow", 38)
        out["supply_chain"] = sc_skill.compute_chains(registry.yahoo)

    if "news" in wanted:
        emit("skills", "Fetching and digesting news", 42)
        articles = news_skill.fetch_and_merge(registry, tickers)
        out["news"] = news_skill.digest(articles)

    if "catalysts" in wanted:
        emit("skills", "Building catalyst calendar", 48)
        out["catalysts"] = cat_skill.build_calendar(registry.finnhub, tickers)

    if "screener" in wanted and preset.get("market_scan"):
        emit("skills", "Screening the market", 52)
        # Reuse the screen already computed to pick the scan targets (below) —
        # recompute only if we weren't handed one (e.g. run_skills called direct).
        out["screen"] = prescreened if prescreened is not None else \
            screener_skill.screen(registry.yahoo, regions=preset.get("regions"))

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
        adv_usd = {t: s["avg_volume_20d"] * s["last_close"]
                   for t, s in out.get("technicals", {}).items()
                   if s.get("avg_volume_20d") and s.get("last_close")}
        out["risk"] = risk_skill.compute_risk(
            holdings, values_usd,
            returns=_returns_from_daily(fetched["daily"]),
            benchmark_returns=_returns_from_daily({"^GSPC": bench}).get("^GSPC"),
            sectors={t: s.get("sector") for t, s in out.get("fundamentals", {}).items()
                     if s.get("sector")},
            adv_usd=adv_usd)

    if "strategies" in wanted and out.get("technicals"):
        emit("skills", "Running strategy panel", 62)
        out["strategy_panel"] = strat_skill.panel(
            tickers, out.get("technicals", {}), out.get("fundamentals", {}),
            out.get("composites", {}))

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
        weights = (out.get("risk") or {}).get("weights") or {}
        if weights:
            out["min_variance_tilt"] = pc_skill.min_variance_tilt(
                weights, _returns_from_daily(fetched["daily"]))

    if "dividends" in wanted:
        emit("skills", "Reading dividend income", 66)
        out["dividends"] = div_skill.income_view(
            holdings, fetched["symbols"], fetched["quotes"], registry.yfinance)

    if out.get("technicals"):
        sizing_by_ticker = {s["ticker"]: s for s in out.get("sizing", [])}
        out["recommendation_blocks"] = {}
        for t in tickers:
            block = signals_skill.recommendation_block(
                t, out["technicals"].get(t), out.get("fundamentals", {}).get(t),
                sizing_by_ticker.get(t, {}).get("atr_stop"),
                out.get("composites", {}).get(t))
            if block:
                out["recommendation_blocks"][t] = block

    if "options_math" in wanted and registry.yfinance.available:
        emit("skills", "Summarizing option chains", 68)
        out["options"] = {}
        returns_by_ticker = _returns_from_daily(fetched["daily"])
        for t in tickers:
            chain = registry.yfinance.option_chain(fetched["symbols"].get(t, t))
            rets = returns_by_ticker.get(t)
            hv_ann = (float(np.std(rets[-20:], ddof=1)) * float(np.sqrt(252))
                      if rets and len(rets) >= 21 else None)
            summary = options_math.chain_summary(chain, realized_vol_ann=hv_ann) \
                if chain else None
            if summary:
                out["options"][t] = summary

    if "order_book" in wanted:
        emit("skills", "Reading Level 2 depth", 69)
        out["order_book"] = ob_skill.fetch_depth_summaries(tickers)

    if "ml_alpha" in wanted:
        emit("skills", "Scoring ML alpha model", 69)
        # Live macro snapshot for the model's macro features — cheap even when
        # "macro" isn't otherwise in this preset's skills, since FRED responses
        # are already TTL-cached.
        macro_snapshot = macro_skill.compute_macro(registry.fred, registry.yahoo)
        out["ml_alpha"] = ml_skill.predict_targets(tickers, fetched["daily"],
                                                   macro=macro_snapshot)

    if "alt_data" in wanted:
        emit("skills", "Reading attention proxies", 71)
        out["alt_data"] = alt_skill.collect(tickers)

    if "digital_footprint" in wanted:
        emit("skills", "Scanning developer footprint", 71)
        out["digital_footprint"] = dfp_skill.collect(tickers)

    if "insiders" in wanted:
        emit("skills", "Digesting insider filings", 70)
        out["insiders"] = ins_skill.fetch_insiders(registry.finnhub, tickers)

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
                "market_review": skills.get("market_review"),
                "supply_chain": skills.get("supply_chain"),
                "news": skills.get("news"),
                "portfolio_fx_exposure": fx_exposure}
    if role == "fundamentals":
        return {**common, "fundamentals": skills.get("fundamentals"),
                "dividends": skills.get("dividends"),
                "screen": skills.get("screen")}
    if role == "technicals_options":
        return {**common, "technicals": skills.get("technicals"),
                "composites": skills.get("composites"),
                "recommendation_blocks": skills.get("recommendation_blocks"),
                "strategy_panel": skills.get("strategy_panel"),
                "options": skills.get("options"), "screen": skills.get("screen")}
    if role == "news_catalysts":
        return {**common, "news": skills.get("news"),
                "catalysts": skills.get("catalysts"),
                "insiders": skills.get("insiders"),
                "politician_trades": skills.get("politician_trades")}
    if role == "risk":
        return {**common, "risk": skills.get("risk"),
                "sizing": skills.get("sizing"),
                "min_variance_tilt": skills.get("min_variance_tilt"),
                "equity_history": skills.get("equity_history"),
                "recommendation_blocks": skills.get("recommendation_blocks"),
                "composites": skills.get("composites")}
    if role == "order_book":
        return {**common, "order_book": skills.get("order_book"),
                "technicals": skills.get("technicals"),
                "sizing": skills.get("sizing")}
    if role == "ml_alpha":
        return {**common, "ml_alpha": skills.get("ml_alpha"),
                "technicals": skills.get("technicals")}
    if role == "alternative_data":
        return {**common, "alt_data": skills.get("alt_data"),
                "technicals": skills.get("technicals")}
    if role == "digital_footprint":
        return {**common, "footprint": skills.get("digital_footprint")}
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

    # Market-scan presets that screen analyze the screened candidates, not the
    # user's portfolio — that's what makes Opportunist surface new setups
    # instead of re-reading your holdings. Falls back to the resolved target if
    # the screen came back empty.
    prescreened = None
    if preset.get("market_scan") and "screener" in preset["skills"]:
        emit("fetch", "Screening the market for candidates", 6)
        scan_holdings, prescreened = await asyncio.to_thread(
            _scan_candidates, registry, preset, settings)
        if scan_holdings:
            holdings = scan_holdings
            target_label = f"Market scan — {preset['name']}"

    if not holdings:
        raise ValueError("no target tickers — portfolio empty or no tickers given")

    run_config = {"preset": preset["name"], "target_label": target_label,
                  "regions": preset.get("regions"),
                  "market_scan": preset.get("market_scan", False)}

    # The skills stage is synchronous network-heavy code — run it off the
    # event loop, or the API server can't even flush the run-started response
    # (a cold-cache full-team run blocks the loop for minutes).
    skills = await asyncio.to_thread(run_skills, registry, preset, holdings,
                                     emit, prescreened=prescreened)

    # Real-book runs leave a daily equity snapshot behind — the digest makes
    # this a weekday series, enabling book-level TWR/drawdown/Sharpe.
    if config.get("target", {}).get("kind", "portfolio") == "portfolio" \
            and skills.get("summary"):
        equity_history.record(skills["summary"])
        skills["equity_history"] = equity_history.metrics()

    feed_status = registry.feed_status()
    lens_status = an.lens_status(feed_status)
    enabled = {l["id"] for l in lens_status if l["enabled"]}
    roles = [r for r in preset["analysts"] if r in enabled]
    # Data-driven lenses are skipped when no target ticker produced data
    # (unentitled market, too little history, nothing in the curated map) —
    # never bill an analyst whose entire input would be "no data".
    _lens_data = {"order_book": skills.get("order_book"),
                  "ml_alpha": skills.get("ml_alpha"),
                  "alternative_data": (skills.get("alt_data") or {}).get("by_ticker"),
                  "digital_footprint": (skills.get("digital_footprint") or {}).get("by_ticker")}
    for data_lens, data in _lens_data.items():
        if data_lens in roles and not data:
            roles.remove(data_lens)
    # Annotate lens transparency so the synthesis can't conflate "not part of
    # this preset" with "feed down" (it hallucinated exactly that once).
    for lens in lens_status:
        lens["in_preset"] = lens["id"] in preset["analysts"]
        lens["ran"] = lens["id"] in roles
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
        "recommendation_blocks": skills.get("recommendation_blocks"),
        "summary": skills.get("summary") or {"tickers": [h["ticker"] for h in holdings]},
        "regional_signals": (skills.get("macro") or {}).get("regional_signals"),
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
    report_id = store.save_report(report, reports_dir=reports_dir)
    ledger.record(report)  # failure-soft; report is already saved
    return report_id
