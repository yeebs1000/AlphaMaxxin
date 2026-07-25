"""Portfolio context for a candidate — the "risk diversified fund" layer.

WHY. The digest emitted single names with no portfolio view: it would happily
hand over five semiconductor names in one morning, all correlated to the AI
theme that already dominates the book, and never mention that portfolio beta
was drifting up. "Maximise alpha, minimise beta" is not representable by a
per-name screen; it needs book-level context at the moment of the decision.

WHAT. Given a candidate and the current book, answer the three questions that
actually change a sizing decision:
  • beta      — what does this do to portfolio beta? (the "minimise beta" half)
  • crowding  — what would this take its sector to?
  • overlap   — what does it correlate with that is already owned?

Beta is computed on WEEKLY returns. Daily beta against a US benchmark is
biased low for HK/SG/JP names purely because those markets close before the US
opens (non-synchronous trading); weekly compounding absorbs the offset. This
matters here — the book is deliberately multi-region.

All pure functions over return series: no fetching, no LLM, offline-testable.
"""
import numpy as np

BETA_MIN_WEEKS = 40          # ~10 months; below this beta is noise
CORR_MIN_BARS = 60
CROWDING_WARN = 0.35         # a sector above this share of the book


def weekly(daily: list) -> list:
    """5-bar non-overlapping compounding. Removes the non-synchronous-trading
    bias that makes Asian names read as artificially low-beta against SPX."""
    series = [r for r in (daily or []) if r is not None]
    out, n = [], len(series) - len(series) % 5
    for i in range(0, n, 5):
        p = 1.0
        for r in series[i:i + 5]:
            p *= 1 + r
        out.append(p - 1)
    return out


def beta(stock_daily: list, bench_daily: list,
         min_weeks: int = BETA_MIN_WEEKS) -> float | None:
    """Weekly beta vs the benchmark, or None when the sample is too short to
    mean anything (returning a number off 8 weeks would be false precision)."""
    r, b = weekly(stock_daily), weekly(bench_daily)
    n = min(len(r), len(b))
    if n < min_weeks:
        return None
    r, b = np.asarray(r[-n:], dtype=float), np.asarray(b[-n:], dtype=float)
    var_b = float(np.var(b, ddof=1))
    if var_b <= 0:
        return None
    return round(float(np.cov(r, b)[0, 1] / var_b), 2)


def correlation(a_daily: list, b_daily: list,
                min_bars: int = CORR_MIN_BARS) -> float | None:
    a = [x for x in (a_daily or []) if x is not None]
    b = [x for x in (b_daily or []) if x is not None]
    n = min(len(a), len(b))
    if n < min_bars:
        return None
    a, b = np.asarray(a[-n:], dtype=float), np.asarray(b[-n:], dtype=float)
    if np.std(a) == 0 or np.std(b) == 0:
        return None
    return round(float(np.corrcoef(a, b)[0, 1]), 2)


def benchmark_for_ticker(ticker: str) -> str | None:
    """The ticker's OWN market index. Measuring an HK name against the S&P
    produces nonsense — Xiaomi reads beta -0.28 against SPX, which is not a
    risk number, it is a different-market artifact. Each name's beta must be
    against the index it actually trades with."""
    try:
        from ..market_calendar import market_of_ticker
        from .macro import INDEX_SYMBOLS, REGION_KEYS
        region = market_of_ticker(ticker)
        idx = ((REGION_KEYS.get(region) or {}).get("indices") or [None])[0]
        return INDEX_SYMBOLS.get(idx) if idx else None
    except Exception:  # noqa: BLE001 — context is best-effort
        return None


def candidate_context(ticker: str, weights: dict, sectors: dict,
                      returns: dict, bench_daily: list | None = None,
                      add_weight: float = 0.05,
                      candidate_sector: str | None = None,
                      benchmarks: dict | None = None) -> dict:
    """`benchmarks` maps ticker -> its own benchmark's daily returns. When
    given, each name's beta is measured against its own market (correct for a
    multi-region book) and the book beta is a weighted average of those LOCAL
    betas — i.e. "how much market risk am I taking in each market", not a
    single-index global beta, which a single US benchmark cannot deliver.
    `bench_daily` is the fallback for names with no mapped benchmark."""
    """What adding `ticker` at `add_weight` would do to the book.

    weights: {ticker: weight} of the CURRENT book (need not sum to 1).
    sectors: {ticker: sector}. returns: {ticker: [daily returns]}.
    Every field degrades to None when its inputs are missing — a missing
    number is reported as unknown, never as zero.
    """
    out = {"ticker": ticker, "add_weight": add_weight}
    cand_ret = returns.get(ticker)
    benchmarks = benchmarks or {}

    def bench_for(t):
        """That name's own market index, falling back to the shared one."""
        return benchmarks.get(t) or bench_daily

    # --- beta: the candidate's own, the book's, and the book's after adding.
    cb = bench_for(ticker)
    out["beta"] = beta(cand_ret, cb) if (cand_ret and cb) else None
    out["beta_basis"] = "local market" if benchmarks.get(ticker) else "shared benchmark"
    book_betas = {t: beta(returns.get(t), bench_for(t)) for t in weights
                  if returns.get(t) and bench_for(t)}
    known = {t: b for t, b in book_betas.items() if b is not None}
    covered = sum(weights[t] for t in known)
    if covered > 0:
        book_beta = sum(weights[t] * known[t] for t in known) / covered
        out["book_beta"] = round(book_beta, 2)
        out["beta_coverage"] = round(covered / (sum(weights.values()) or 1), 2)
        if out["beta"] is not None:
            # Weighted blend after adding the candidate at add_weight.
            after = (book_beta * covered + out["beta"] * add_weight) / (covered + add_weight)
            out["book_beta_after"] = round(after, 2)
    else:
        out["book_beta"] = out["beta_coverage"] = out["book_beta_after"] = None

    # --- crowding: what this takes its sector to.
    sec = candidate_sector or sectors.get(ticker)
    out["sector"] = sec
    if sec:
        total = sum(weights.values()) or 1.0
        cur = sum(w for t, w in weights.items() if sectors.get(t) == sec)
        after = (cur + add_weight) / (total + add_weight)
        out["sector_weight"] = round(cur / total, 3)
        out["sector_weight_after"] = round(after, 3)
        out["crowded"] = after > CROWDING_WARN

    # --- overlap: the most-correlated things already owned.
    overlaps = []
    if cand_ret:
        for t in weights:
            if t == ticker:
                continue
            c = correlation(cand_ret, returns.get(t))
            if c is not None and c >= 0.60:
                overlaps.append({"ticker": t, "corr": c})
    out["overlaps"] = sorted(overlaps, key=lambda o: -o["corr"])[:3]
    return out


def context_line(ctx: dict) -> str | None:
    """One compact human line for the digest, or None if nothing is known."""
    bits = []
    if ctx.get("beta") is not None:
        b = f"beta {ctx['beta']}"
        if ctx.get("book_beta") is not None and ctx.get("book_beta_after") is not None:
            b += f" (book {ctx['book_beta']}→{ctx['book_beta_after']})"
        bits.append(b)
    if ctx.get("sector_weight_after") is not None:
        s = f"{ctx.get('sector') or 'sector'} {ctx['sector_weight']:.0%}→{ctx['sector_weight_after']:.0%}"
        if ctx.get("crowded"):
            s += " ⚠"
        bits.append(s)
    if ctx.get("overlaps"):
        top = ctx["overlaps"][0]
        bits.append(f"corr {top['corr']} w/ {top['ticker']}")
    return " · ".join(bits) if bits else None
