"""Portfolio health check — gathers live broker data and runs the PM-grade
assessment in skills/portfolio_health.py.

    py -m app.health_check            # uses Portfolio.md as-is
    py -m app.health_check --sync     # pull live broker positions first

Deliberately separate from the report pipeline: this spends no LLM tokens,
answers a different question ("is the book well built?"), and can therefore be
run as often as wanted. Broker sync is opt-in because it reaches out to the
local moomoo/IBKR/Tiger gateways.
"""
import datetime
import sys

from .skills import portfolio_health


def _daily_returns(bars):
    closes = (bars or {}).get("closes") or []
    return [closes[i] / closes[i - 1] - 1
            for i in range(1, len(closes)) if closes[i - 1]]


def gather(sync_brokers: bool = False) -> dict:
    """Build the positions list the health report needs, from live data.

    Every per-name lookup degrades to None rather than failing the run: a
    thin feed should cost us one field, not the whole assessment.
    """
    from . import equity_history
    from . import portfolio as pf
    from .data.live_quote import live_quote
    from .data.registry import get_default_registry
    from .skills import portfolio_context as pctx
    from .skills.business_stage import SLEEVE, classify
    from .skills.fundamentals import compute_fundamentals, f_score
    from .skills.performance import portfolio_summary

    if sync_brokers:
        try:
            result = pf.sync_from_brokers()
            print(f"[health] broker sync: "
                  f"{'ok' if result.get('success') else result.get('error')}")
        except Exception as e:  # noqa: BLE001 — stale file beats no run
            print(f"[health] broker sync failed, using Portfolio.md: {e}",
                  file=sys.stderr)

    reg = get_default_registry()
    holdings = pf.parse_portfolio()
    if not holdings:
        return {"positions": [], "equity_metrics": None}

    quotes = {h["ticker"]: live_quote(h["ticker"], reg.yahoo) or {} for h in holdings}
    summary = portfolio_summary(holdings, quotes)

    positions, returns, benchmarks, bench_cache = [], {}, {}, {}
    for row in summary.get("holdings", []):
        t = row["ticker"]
        # Portfolio.md holds LOCAL tickers; Yahoo needs the suffixed symbol.
        symbol, _ = reg.yahoo.resolve_symbol(t)
        symbol = symbol or t
        raw = reg.yfinance.fundamentals(symbol) if reg.yfinance.available else None
        snap = compute_fundamentals(t, raw)
        years = reg.yfinance.statements(symbol) if reg.yfinance.available else None
        stage = classify(snap, years) if snap else None
        fund = None
        if snap:
            # fundamental_conviction lives in the personal scanner layer, which
            # is not part of the public repo. Without it the quality dimension
            # simply drops out of the composite — the rest still scores.
            try:
                from .scanner import fundamental_conviction
                fund = fundamental_conviction(snap, f_score(years), years=years)
            except ImportError:
                fund = None
        returns[t] = _daily_returns(reg.yahoo.ohlcv(symbol, "1d", "2y"))
        sym = pctx.benchmark_for_ticker(t)
        if sym and sym not in bench_cache:
            bench_cache[sym] = _daily_returns(reg.yahoo.ohlcv(sym, "1d", "2y"))
        if sym:
            benchmarks[t] = bench_cache[sym]
        positions.append({
            "ticker": t,
            "company": row.get("company"),
            "weight": row.get("weight"),
            "value_usd": row.get("value_usd"),
            "sector": (snap or {}).get("sector"),
            "stage": (stage or {}).get("stage"),
            "sleeve": SLEEVE.get((stage or {}).get("stage"), {}).get("sleeve"),
            "fund_score": (fund or {}).get("score"),
            "fund_verdict": (fund or {}).get("verdict"),
            "beta": pctx.beta(returns[t], benchmarks.get(t))
                    if benchmarks.get(t) else None,
        })

    # Cash and money-market/short-bond funds sit OUTSIDE position_list_query,
    # so a securities-only view misses real ballast. The owner sweeps idle cash
    # into a money-market fund, so this balance moves; adding it as one line
    # keeps sector weights and the defensive floor honest.
    cash_line = _cash_position(summary.get("total_value_usd"))
    if cash_line:
        positions.append(cash_line)
        # Re-weight: the book just got bigger by the cash leg.
        total = (summary.get("total_value_usd") or 0) + cash_line["value_usd"]
        if total:
            for p in positions:
                p["weight"] = (p["value_usd"] or 0) / total

    # Portfolio beta = weighted mean of LOCAL-market betas (see
    # portfolio_context: a single US benchmark mis-measures HK/SG names).
    known = {p["ticker"]: p["beta"] for p in positions if p.get("beta") is not None}
    covered = sum(p["weight"] or 0 for p in positions if p["ticker"] in known)
    pbeta = (round(sum((p["weight"] or 0) * known[p["ticker"]]
                       for p in positions if p["ticker"] in known) / covered, 2)
             if covered > 0 else None)

    # Pairwise correlations for the cluster check.
    corr = {}
    tickers = [p["ticker"] for p in positions]
    for i, a in enumerate(tickers):
        for b in tickers[i + 1:]:
            c = pctx.correlation(returns.get(a), returns.get(b))
            if c is not None:
                corr[(a, b)] = c

    eq = equity_history.metrics()
    return {"positions": positions, "equity_metrics": eq,
            "portfolio_beta": pbeta, "beta_coverage": round(covered, 2),
            "corr": corr, "summary": summary,
            "benchmark_return_pct": _benchmark_return(reg, eq),
            "mwr": money_weighted(summary.get("total_value_usd"))}


def money_weighted(current_value: float | None, pull_broker: bool = True,
                   days: int = 40) -> dict | None:
    """Money-weighted return over the equity-history window.

    Only EXTERNAL capital counts. Verified on the live account: a stock
    purchase funded from existing cash moves the cost basis exactly like a
    deposit does, so the snapshot proxy read a routine buy as $3.5k of new
    money and produced a -31.7% MWR that was pure artifact. Broker-classified
    flows are therefore strongly preferred, and when they show NO external
    flows in the window the honest answer is that MWR equals TWR.
    """
    from . import equity_history
    from .data.registry import get_default_registry
    from .skills import money_weighted as mwmod
    if not current_value:
        return None
    rows = equity_history._load()
    if len(rows) < 2:
        return None
    w0 = datetime.date.fromisoformat(rows[0]["date"])
    w1 = datetime.date.fromisoformat(rows[-1]["date"])
    opening = float(rows[0].get("value_usd") or 0)

    # The measured portfolio is the SECURITIES BOOK: value_usd counts holdings
    # and carries no cash leg. So cash deployed from account cash into stock is
    # a CONTRIBUTION to the thing being measured, even though it is not new
    # capital to the account. Omitting it makes a cash->stock conversion read
    # as pure gain (it produced a 617,292% MWR before this was corrected).
    # Cost-basis deltas capture exactly those contributions.
    contributions = mwmod.flows_from_snapshots(rows)[1:]     # drop opening
    note = None

    # Broker data cannot replace those flows, but it answers a different and
    # useful question: was any of the growth NEW money?
    external = None
    if pull_broker:
        try:
            from .brokers.moomoo_client import external_flows, get_moomoo_cash_flow
            flows = external_flows(get_moomoo_cash_flow(days=days))
            if flows is not None:
                fx = get_default_registry().yahoo
                external = []
                for r in flows:
                    try:
                        d = datetime.date.fromisoformat(r["date"])
                    except (ValueError, KeyError):
                        continue
                    if not (w0 <= d <= w1):
                        continue
                    amt = float(r.get("amount") or 0)
                    ccy = (r.get("currency") or "USD").upper()
                    if ccy != "USD":     # this account funds in SGD
                        rate = fx.fx_rate(ccy)
                        if not rate:
                            continue
                        amt *= rate
                    external.append((d, amt))
        except Exception:  # noqa: BLE001 — gateway down is normal
            external = None

    if external is not None:
        note = (f"broker-verified: {len(external)} external deposit(s) in this "
                "window" + ("" if external else
                            " — the book grew by deploying existing account "
                            "cash, not new money"))

    out = mwmod.money_weighted_return([(w0, opening)] + contributions,
                                      current_value, as_of=w1)
    if out:
        out["source"] = ("securities-book flows (cost-basis deltas); "
                         + ("broker-verified external capital"
                            if external is not None else
                            "broker cash flow unavailable"))
        out["window"] = f"{w0.isoformat()} to {w1.isoformat()}"
        out["external_flows_in_window"] = (len(external)
                                           if external is not None else None)
        if note:
            out["note"] = note
    return out


def _cash_position(book_value: float | None) -> dict | None:
    """Broker cash + money-market/bond fund balances as a single ballast line.

    Beta 0 and no fundamentals by construction — scoring a money-market fund
    on revenue growth would be nonsense, so those fields stay None and drop
    out of the relevant dimensions rather than dragging them down.
    """
    try:
        from .brokers.moomoo_client import get_moomoo_account_assets
        assets = get_moomoo_account_assets()
    except Exception:  # noqa: BLE001 — gateway down is normal
        return None
    if not assets:
        return None
    amount = (assets.get("cash") or 0) + (assets.get("fund_assets") or 0)
    if amount <= 0:
        return None
    return {
        "ticker": "CASH", "company": "Cash & money-market funds",
        "weight": None,                      # set by the caller after re-weighting
        "value_usd": amount,
        "sector": portfolio_health.CASH_SECTOR,
        "stage": "cash", "sleeve": "ballast",
        "fund_score": None, "fund_verdict": None, "beta": 0.0,
    }


def _benchmark_return(reg, equity_metrics) -> float | None:
    """S&P 500 return over the SAME window the book's TWR covers. Without it
    "performance" is a raw number: +8% in a market that made 12% is a losing
    book, and only the excess figure says so."""
    if not equity_metrics:
        return None
    try:
        import datetime
        start = datetime.date.fromisoformat(equity_metrics["first_date"])
        end = datetime.date.fromisoformat(equity_metrics["last_date"])
        bars = reg.yahoo.ohlcv("^GSPC", "1d", "1y") or {}
        closes, stamps = bars.get("closes") or [], bars.get("timestamps") or []
        pairs = []
        for ts, c in zip(stamps, closes):
            # Yahoo emits EPOCH INTEGERS, not ISO strings — fromisoformat on
            # "1784899800" fails silently and drops every bar.
            try:
                d = (datetime.datetime.fromtimestamp(
                        ts, datetime.timezone.utc).date()
                     if isinstance(ts, (int, float))
                     else datetime.date.fromisoformat(str(ts)[:10]))
            except (ValueError, OSError, OverflowError):
                continue
            if start <= d <= end:
                pairs.append(c)
        if len(pairs) < 2 or not pairs[0]:
            return None
        return round((pairs[-1] / pairs[0] - 1) * 100, 2)
    except Exception:  # noqa: BLE001 — a missing benchmark costs one field
        return None


def run(sync_brokers: bool = False) -> dict:
    data = gather(sync_brokers=sync_brokers)
    rep = portfolio_health.health_report(
        data["positions"], equity_metrics=data.get("equity_metrics"),
        portfolio_beta=data.get("portfolio_beta"), corr=data.get("corr"),
        benchmark_return_pct=data.get("benchmark_return_pct"))
    rep["performance"]["mwr"] = data.get("mwr")
    return rep


def format_report(rep: dict) -> str:
    """Plain-text PM briefing."""
    if not rep.get("score"):
        return "Portfolio health: no positions to assess."
    out = [f"PORTFOLIO HEALTH — {rep['score']}/100  (grade {rep['grade']})", ""]
    for name, d in rep["dimensions"].items():
        s = d.get("score")
        out.append(f"  {name.replace('_', ' ').title():22} "
                   f"{(str(s) + '/100') if s is not None else 'n/a':>9}  "
                   f"{d.get('detail', '')}")
    perf = rep.get("performance") or {}
    if perf.get("twr_pct") is not None:
        line = f"  {'Performance':22} {perf['twr_pct']:>8.2f}%  TWR"
        if perf.get("excess_pct") is not None:
            line += f" ({perf['excess_pct']:+.2f}% vs benchmark)"
        if perf.get("sharpe_ann") is not None:
            line += f", Sharpe {perf['sharpe_ann']}"
        out.append(line)
    mwr = perf.get("mwr")
    if mwr:
        out.append(f"  {'Money-weighted':22} {mwr['mwr_annual_pct']:>8.2f}%  "
                   f"annualised on {mwr['n_flows']} flow(s) over "
                   f"{mwr['days']}d, net invested "
                   f"${mwr['net_invested']:,.0f}")
        if mwr.get("simple_gain_pct") is not None:
            out.append(f"  {'':22} {mwr['simple_gain_pct']:>8.2f}%  "
                       f"simple gain on contributed capital")
        out.append(f"  {'':22} {'':>8}   window {mwr.get('window', '?')}, "
                   f"{mwr.get('external_flows_in_window', 0)} external flow(s)")
        out.append(f"  {'':22} {'':>8}   source: {mwr['source']}")
        if mwr.get("note"):
            out.append(f"  {'':22} {'':>8}   {mwr['note']}")
        # The GAP is the signal: TWR measures the strategy, MWR measures what
        # the owner earned given when money arrived.
        if perf.get("twr_pct") is not None:
            gap = mwr["mwr_annual_pct"] - perf["twr_pct"]
            if abs(gap) > 1.0:
                worse = "below" if gap < 0 else "above"
                out.append(f"  {'':22} {'':>8}   MWR is {abs(gap):.1f}pp {worse} "
                           f"TWR — money "
                           f"{'arrived at bad moments' if gap < 0 else 'arrived well'}")
    out += ["", "RECOMMENDATIONS"]
    if not rep["recommendations"]:
        out.append("  None — the book is within every structural limit.")
    for r in rep["recommendations"]:
        tgt = r.get("target")
        tgt = ", ".join(tgt) if isinstance(tgt, list) else (tgt or "")
        head = f"  [{r['priority'].upper()}] {r['action']}"
        out.append(f"{head} {tgt}".rstrip())
        out.append(f"      {r['why']}")
    out += ["", f"  ({rep['note']})"]
    return "\n".join(out)


if __name__ == "__main__":
    import os
    from .config import load_env
    load_env()
    rep = run(sync_brokers="--sync" in sys.argv)
    text = format_report(rep)
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))
    sys.stdout.flush()
    os._exit(0)      # moomoo's non-daemon threads would otherwise hang exit
