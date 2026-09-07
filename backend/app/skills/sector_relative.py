"""Sector-relative peer ranking — the deterministic analysis kernel.

Phase 1 of the sector research prototype (`~/infra/SECTOR-ANALYSIS-WORK-BRIEF.md`
§3.5, §5.2). Every number here is computed in Python from explicitly supplied
inputs. No LLM may create, rescore, reorder or filter what this module returns.

**This module is deliberately inert.** It performs no network, filesystem,
broker, environment or wall-clock access, and imports nothing that does — the
only import is `math`. `as_of` is a parameter, not a clock read, which is what
makes a run reproducible and a trailing-only window honest. `tests/
test_sector_relative.py` enforces this by scanning the source.

The output is an EXPERIMENTAL RESEARCH MEASUREMENT. It is not a signal, not a
recommendation, not a position size, and is not wired to any report or order
path.

Method (`METHODOLOGY_VERSION`):
  * midrank percentiles on a 0-100 scale, not z-scores. With 12-30 peers a
    percentile is robust to the fat tails and single outliers that make a
    z-score unstable, and it is hand-checkable in a fixture.
  * percentile = (midrank - 0.5) / n * 100, so a set of distinct values is
    symmetric about 50 and neither endpoint is pinned to 0 or 100.
  * ties take the average rank; ticker sort is the final stable tie-break.
  * a factor's peer denominator is counted per factor, because eligibility
    differs field by field — a name can have a P/E and no EV/EBITDA.
  * invalid values are excluded, never imputed to a neutral 50. Imputing would
    reward missing data, which is exactly backwards for the thin non-US
    coverage this universe has.
"""
import math

SCHEMA_VERSION = "sector_relative-1"
METHODOLOGY_VERSION = "midrank-percentile-1"

# Minimum eligible names before a peer distribution means anything. 12 is the
# brief's figure: below it a percentile is mostly an artifact of which names
# happened to have data.
MIN_PEERS = 12

TRADING_DAYS_PER_YEAR = 252

DISCLAIMER = ("EXPERIMENTAL RESEARCH MEASUREMENT — not wired to reports, "
              "signals, sizing, or orders")


# ---------------------------------------------------------------------------
# null-v1 factor profile
# ---------------------------------------------------------------------------
# Every factor declares: id | family | source | direction | weight | version.
# The profile is plain data so it serializes into the artifact verbatim — the
# reader of a result can always see the formula that produced it.
#
# null-v1 is equal-weight on purpose. It is a NULL profile: a deliberately
# uninteresting baseline that exists to test the machinery, not a thesis about
# what makes a company attractive. No sector-specific profile is enabled,
# because the measures that would justify one (EV/EBITDAX, reserve life, CET1,
# NIM, same-store sales, GMROI, book-to-bill) are not fields in the current
# free-feed fundamentals contract. They are future feed requirements. Never ask
# a model to supply them from memory.
NULL_V1_PROFILE = {
    "id": "null-v1",
    "version": "null-v1",
    "description": "Equal-weight baseline over factor families supported by "
                   "the current free-feed fundamentals contract.",
    "min_families": 3,
    "family_weights": {"value": 1.0, "growth": 1.0, "quality": 1.0, "price": 1.0},
    "factors": (
        # Value — lower is better, and only positive values qualify. A negative
        # or zero P/E is not cheap, it is a different situation entirely; the
        # brief calls this out explicitly.
        {"id": "fwd_pe", "family": "value", "source": "fundamentals:valuation.fwd_pe",
         "direction": "lower_is_better", "weight": 1.0, "require_positive": True,
         "version": "null-v1"},
        {"id": "ev_ebitda", "family": "value", "source": "fundamentals:valuation.ev_ebitda",
         "direction": "lower_is_better", "weight": 1.0, "require_positive": True,
         "version": "null-v1"},
        {"id": "ps", "family": "value", "source": "fundamentals:valuation.ps",
         "direction": "lower_is_better", "weight": 1.0, "require_positive": True,
         "version": "null-v1"},
        # Growth — higher is better. Negative growth is a real observation, so
        # no positivity requirement here.
        {"id": "rev_yoy", "family": "growth", "source": "fundamentals:growth.rev_yoy",
         "direction": "higher_is_better", "weight": 1.0, "version": "null-v1"},
        {"id": "eps_yoy", "family": "growth", "source": "fundamentals:growth.eps_yoy",
         "direction": "higher_is_better", "weight": 1.0, "version": "null-v1"},
        # Quality — margins and Piotroski completion ratio when supplied.
        {"id": "op_margin", "family": "quality", "source": "fundamentals:margins.operating",
         "direction": "higher_is_better", "weight": 1.0, "version": "null-v1"},
        {"id": "net_margin", "family": "quality", "source": "fundamentals:margins.net",
         "direction": "higher_is_better", "weight": 1.0, "version": "null-v1"},
        {"id": "f_score_ratio", "family": "quality", "source": "derived:f_score_ratio",
         "direction": "higher_is_better", "weight": 1.0, "version": "null-v1"},
        # Price behaviour — computed from the supplied bars, trailing-only.
        # Direction is stated, never inferred from the field name: realized
        # volatility is scored lower-is-better as an explicit choice, not
        # because "vol sounds bad".
        {"id": "ret_252d", "family": "price", "source": "price:total_return",
         "window": 252, "direction": "higher_is_better", "weight": 1.0,
         "version": "null-v1"},
        {"id": "ret_63d", "family": "price", "source": "price:total_return",
         "window": 63, "direction": "higher_is_better", "weight": 1.0,
         "version": "null-v1"},
        {"id": "realized_vol_63d", "family": "price", "source": "price:realized_vol",
         "window": 63, "direction": "lower_is_better", "weight": 1.0,
         "version": "null-v1"},
    ),
}

# Fields deliberately NOT ranked, with the reason, so a later reader does not
# "fix" their absence: raw FCF and market cap are currency-denominated and this
# universe spans USD/HKD/SGD; analyst targets, recommendation labels and news
# sentiment are opinions, not fundamentals; portfolio risk is not a property of
# the company.
EXCLUDED_BY_DESIGN = ("balance.fcf", "market_cap", "analyst.target_mean",
                      "analyst.rec", "news_sentiment", "portfolio_risk")


# ---------------------------------------------------------------------------
# small pure numerics (deliberately not imported from data.base — that module
# reads os.environ, which would break this module's inertness guarantee)
# ---------------------------------------------------------------------------
def _num(value):
    """Finite float or None. Bools are not numbers here; NaN/Inf are missing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _mean(values):
    return sum(values) / len(values) if values else None


def _stdev(values):
    """Sample standard deviation; None below two observations."""
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    var = sum((v - avg) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _round(value, digits=4):
    return None if value is None else round(value, digits)


def midrank_percentiles(pairs) -> dict:
    """{ticker: percentile} for (ticker, value) pairs, ascending in value.

    Ties share the average of the ranks they span, so two identical values can
    never be separated by an accident of input order. The final sort key is the
    ticker, which makes the result invariant to how the caller ordered its
    input — the property test #8 checks.
    """
    ordered = sorted(pairs, key=lambda item: (item[1], item[0]))
    n = len(ordered)
    out, index = {}, 0
    while index < n:
        stop = index
        while stop + 1 < n and ordered[stop + 1][1] == ordered[index][1]:
            stop += 1
        midrank = (index + stop) / 2 + 1          # 1-based average rank
        percentile = (midrank - 0.5) / n * 100
        for position in range(index, stop + 1):
            out[ordered[position][0]] = percentile
        index = stop + 1
    return out


# ---------------------------------------------------------------------------
# value extraction
# ---------------------------------------------------------------------------
def _dig(snapshot, dotted):
    node = snapshot
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _trailing_closes(bars, as_of):
    """Ascending closes dated on or before `as_of`.

    Accepts either the cached price-panel shape ({date: close}) or a list of
    {date, close} rows. Trailing-only is enforced here rather than trusted from
    the caller: a factor that can see past `as_of` is not a factor, it is a
    lookahead bug.
    """
    rows = []
    if isinstance(bars, dict):
        rows = list(bars.items())
    elif isinstance(bars, (list, tuple)):
        for bar in bars:
            if isinstance(bar, dict):
                rows.append((bar.get("date"), bar.get("close")))
            elif isinstance(bar, (list, tuple)) and len(bar) >= 2:
                rows.append((bar[0], bar[1]))
    closes = []
    for date, close in rows:
        if not isinstance(date, str) or date > as_of:
            continue
        value = _num(close)
        if value is not None and value > 0:
            closes.append((date, value))
    closes.sort()
    return [value for _, value in closes]


def _total_return(closes, window):
    if window is None or len(closes) < window + 1:
        return None
    start = closes[-(window + 1)]
    return (closes[-1] / start) - 1 if start > 0 else None


def _realized_vol(closes, window):
    """Annualized standard deviation of daily log returns over the window."""
    if window is None or len(closes) < window + 1:
        return None
    tail = closes[-(window + 1):]
    log_returns = []
    for prev, curr in zip(tail, tail[1:]):
        if prev <= 0 or curr <= 0:
            return None
        log_returns.append(math.log(curr / prev))
    deviation = _stdev(log_returns)
    return None if deviation is None else deviation * math.sqrt(TRADING_DAYS_PER_YEAR)


def _f_score_ratio(snapshot):
    """Piotroski completion ratio. Requires at least 5 of 9 criteria known —
    a 2-of-2 score is 100% and utterly uninformative next to a 7-of-9."""
    block = snapshot.get("f_score") if isinstance(snapshot, dict) else None
    if not isinstance(block, dict):
        return None
    score, known = _num(block.get("score")), _num(block.get("known"))
    if score is None or known is None or known < 5:
        return None
    return score / known


def factor_value(factor, snapshot, closes):
    """(value, invalid_reason). value None means the factor cannot be scored
    for this name; the reason is recorded rather than swallowed."""
    source = factor.get("source", "")
    if source.startswith("fundamentals:"):
        raw = _dig(snapshot, source.split(":", 1)[1])
        value = _num(raw)
        if value is None:
            return None, "missing"
    elif source == "derived:f_score_ratio":
        value = _f_score_ratio(snapshot)
        if value is None:
            return None, "missing"
    elif source == "price:total_return":
        value = _total_return(closes, factor.get("window"))
        if value is None:
            return None, "insufficient_history"
    elif source == "price:realized_vol":
        value = _realized_vol(closes, factor.get("window"))
        if value is None:
            return None, "insufficient_history"
    else:
        return None, "unknown_source"
    if factor.get("require_positive") and value <= 0:
        # Explicitly NOT "cheap". A non-positive multiple is a different state,
        # and ranking it as the cheapest name in the pool would be a lie.
        return None, "non_positive"
    return value, None


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------
def analyze_sector_relative(fundamentals_by_ticker: dict,
                            daily_bars_by_ticker: dict,
                            *, region: str, sector: str, as_of: str,
                            profile: dict,
                            taxonomy_by_ticker: dict | None = None,
                            industry_groups: dict | None = None) -> dict:
    """Peer-relative factor percentiles for one (region, sector) scope.

    Inputs are read, never mutated. Output is JSON-serializable with finite
    numbers only.
    """
    fundamentals_by_ticker = fundamentals_by_ticker or {}
    daily_bars_by_ticker = daily_bars_by_ticker or {}
    taxonomy_by_ticker = taxonomy_by_ticker or {}
    # industry label -> coarser group. Supplied by the caller rather than
    # imported, so this module keeps its no-dependency guarantee.
    industry_groups = industry_groups or {}
    factors = list(profile.get("factors") or ())
    family_weights = dict(profile.get("family_weights") or {})
    min_families = int(profile.get("min_families", 3))
    warnings = []

    # -- 1. scope the candidate set ----------------------------------------
    candidates, excluded = {}, {}
    for ticker in sorted(fundamentals_by_ticker):
        snapshot = fundamentals_by_ticker[ticker] or {}
        taxonomy = taxonomy_by_ticker.get(ticker) or {}
        row_sector = taxonomy.get("sector") or snapshot.get("sector")
        row_industry = taxonomy.get("industry") or snapshot.get("industry")
        if row_sector != sector:
            excluded[ticker] = ["sector_mismatch"]
            continue
        candidates[ticker] = {
            "ticker": ticker,
            "sector": row_sector,
            "industry": row_industry,
            "industry_group": (taxonomy.get("industry_group")
                               or industry_groups.get(row_industry)),
            "snapshot": snapshot,
            "closes": _trailing_closes(daily_bars_by_ticker.get(ticker), as_of),
            "taxonomy_source": taxonomy.get("sector_source") or (
                "fundamentals_snapshot" if snapshot.get("sector") else None),
            "taxonomy_status": taxonomy.get("sector_status"),
            "taxonomy_conflict": bool(taxonomy.get("taxonomy_conflict")),
        }

    eligible = sorted(candidates)
    sector_pool = list(eligible)

    # -- 2. choose a peer level per industry group -------------------------
    # Level is decided once per industry so a candidate has one coherent peer
    # denominator story, then MIN_PEERS is applied AGAIN per factor inside the
    # chosen pool (step 4) because field coverage differs from name coverage.
    by_industry, by_group = {}, {}
    for ticker in eligible:
        by_industry.setdefault(candidates[ticker]["industry"], []).append(ticker)
        group = candidates[ticker]["industry_group"]
        if group:
            by_group.setdefault(group, []).append(ticker)

    pool_for, level_for = {}, {}
    insufficient_groups = []
    for industry, members in sorted(by_industry.items(), key=lambda kv: (kv[0] or "",)):
        group = candidates[members[0]]["industry_group"]
        group_pool = by_group.get(group) or []
        # Three tiers, narrowest first. The middle one exists because the
        # census measured what its absence costs: US Consumer Cyclical spread
        # 119 names over 22 industries with none reaching 12, so every name
        # fell to a sector pool mixing restaurants, car makers and casinos.
        if industry and len(members) >= MIN_PEERS:
            level, pool = "industry", members
        elif group and len(group_pool) >= MIN_PEERS:
            level, pool = "industry_group", group_pool
        elif len(sector_pool) >= MIN_PEERS:
            level, pool = "sector", sector_pool
        else:
            level, pool = "insufficient_peers", []
            insufficient_groups.append({
                "industry": industry, "members": len(members),
                "industry_group": group, "group_pool": len(group_pool),
                "sector_pool": len(sector_pool), "minimum": MIN_PEERS})
        for ticker in members:
            level_for[ticker] = level
            pool_for[ticker] = pool

    # -- 3. raw factor values ----------------------------------------------
    raw_values, invalid_reasons = {}, {}
    for factor in factors:
        fid = factor["id"]
        raw_values[fid], invalid_reasons[fid] = {}, {}
        for ticker in eligible:
            value, reason = factor_value(
                factor, candidates[ticker]["snapshot"], candidates[ticker]["closes"])
            if value is None:
                invalid_reasons[fid][ticker] = reason
            else:
                raw_values[fid][ticker] = value

    # -- 4. percentiles within each distinct pool --------------------------
    percentiles, denominators = {}, {}
    for factor in factors:
        fid, direction = factor["id"], factor.get("direction")
        percentiles[fid], denominators[fid] = {}, {}
        seen_pools = {}
        for ticker in eligible:
            pool = pool_for.get(ticker) or []
            key = (level_for.get(ticker), tuple(pool))
            if key not in seen_pools:
                pairs = [(t, raw_values[fid][t]) for t in pool if t in raw_values[fid]]
                if len(pairs) >= MIN_PEERS:
                    seen_pools[key] = (midrank_percentiles(pairs), len(pairs))
                else:
                    seen_pools[key] = (None, len(pairs))
            ranked, denominator = seen_pools[key]
            denominators[fid][ticker] = denominator
            if ranked is None or ticker not in ranked:
                continue
            value = ranked[ticker]
            if direction == "lower_is_better":
                value = 100 - value
            elif direction != "higher_is_better":
                warnings.append(f"factor {fid} has no explicit direction — skipped")
                continue
            percentiles[fid][ticker] = value

    # -- 5. family scores, composite, rank ---------------------------------
    rows = []
    for ticker in eligible:
        by_family, coverage = {}, {}
        for factor in factors:
            fid, family = factor["id"], factor["family"]
            if ticker in percentiles[fid]:
                by_family.setdefault(family, []).append(percentiles[fid][ticker])
                coverage[fid] = "scored"
            elif ticker in invalid_reasons[fid]:
                # This name's own reason outranks the pool's. They point at
                # different repairs: a per-name reason says fix the feed, an
                # insufficient denominator says widen the peer pool.
                coverage[fid] = invalid_reasons[fid][ticker]
            elif denominators[fid].get(ticker, 0) < MIN_PEERS:
                coverage[fid] = "insufficient_factor_peers"
            else:
                coverage[fid] = "missing"
        family_scores = {f: _round(_mean(v)) for f, v in sorted(by_family.items())}

        composite, composite_note = None, None
        if level_for.get(ticker) == "insufficient_peers":
            composite_note = "insufficient_peers"
        elif len(family_scores) < min_families:
            # Renormalizing over one or two families would quietly turn a
            # coverage failure into a confident-looking score.
            composite_note = (f"only {len(family_scores)} of {min_families} "
                              "required families present")
        else:
            weights = {f: _num(family_weights.get(f)) or 0.0 for f in family_scores}
            total = sum(weights.values())
            if total > 0:
                composite = _round(sum(family_scores[f] * weights[f]
                                       for f in family_scores) / total, 4)
            else:
                composite_note = "profile family weights sum to zero"

        rows.append({
            "ticker": ticker,
            "sector": candidates[ticker]["sector"],
            "industry": candidates[ticker]["industry"],
            "industry_group": candidates[ticker]["industry_group"],
            "eligible": True,
            "peer_level_requested": "industry",
            "peer_level_used": level_for.get(ticker),
            "peer_count": len(pool_for.get(ticker) or []),
            "factor_percentiles": {f: _round(percentiles[f][ticker])
                                   for f in percentiles if ticker in percentiles[f]},
            "factor_denominators": {f: denominators[f].get(ticker, 0)
                                    for f in denominators},
            "factor_coverage": coverage,
            "family_scores": family_scores,
            "experimental_score": composite,
            "experimental_rank": None,
            "exclusions": [],
            "warnings": [composite_note] if composite_note else [],
            "taxonomy_conflict": candidates[ticker]["taxonomy_conflict"],
        })

    scored = [r for r in rows if r["experimental_score"] is not None]
    scored.sort(key=lambda r: (-r["experimental_score"], r["ticker"]))
    for position, row in enumerate(scored, start=1):
        row["experimental_rank"] = position
    rows.sort(key=lambda r: (r["experimental_rank"] is None,
                             r["experimental_rank"] or 0, r["ticker"]))

    # -- 6. sector context — observed, labelled, and NOT in the score ------
    context_returns = [raw_values.get("ret_252d", {}).get(t) for t in eligible]
    context_returns = [v for v in context_returns if v is not None]
    context_vol = [raw_values.get("realized_vol_63d", {}).get(t) for t in eligible]
    context_vol = [v for v in context_vol if v is not None]
    sector_context = {
        "note": "price-derived observations only; excluded from every score",
        "included_in_score": False,
        "names_with_252d_return": len(context_returns),
        "median_return_252d": _round(_median(context_returns)),
        "breadth_positive_252d": _round(
            sum(1 for v in context_returns if v > 0) / len(context_returns)
            if context_returns else None),
        "median_realized_vol_63d": _round(_median(context_vol)),
    }

    # -- 7. coverage -------------------------------------------------------
    missing_by_factor = {
        factor["id"]: {
            reason: sum(1 for r in invalid_reasons[factor["id"]].values() if r == reason)
            for reason in sorted(set(invalid_reasons[factor["id"]].values()))
        } for factor in factors
    }
    level_counts = {}
    for ticker in eligible:
        level = level_for.get(ticker)
        level_counts[level] = level_counts.get(level, 0) + 1

    if not eligible:
        warnings.append(f"no candidates matched region={region} sector={sector}")
    if len(sector_pool) < MIN_PEERS:
        warnings.append(
            f"sector pool has {len(sector_pool)} names, below MIN_PEERS={MIN_PEERS} "
            "— no fallback level is available")

    return {
        "schema_version": SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "disclaimer": DISCLAIMER,
        "as_of": as_of,
        "scope": {"region": region, "sector": sector},
        "profile": {"id": profile.get("id"), "version": profile.get("version"),
                    "min_families": min_families,
                    "family_weights": family_weights,
                    "factors": [dict(f) for f in factors]},
        "peer_policy": {
            "minimum": MIN_PEERS,
            "requested_level": "industry",
            "fallback_levels": ["industry_group", "sector"],
            "level_counts": level_counts,
            "level_used_by_ticker": {t: level_for.get(t) for t in eligible},
        },
        "taxonomy": {
            "version": next(
                (v for v in ((taxonomy_by_ticker.get(t) or {}).get("taxonomy_version")
                             for t in eligible) if v), None),
            "source_by_ticker": {t: candidates[t]["taxonomy_source"] for t in eligible},
            "status_by_ticker": {t: candidates[t]["taxonomy_status"] for t in eligible},
            "conflicts": sorted(t for t in eligible if candidates[t]["taxonomy_conflict"]),
            "note": "current labels; NOT point-in-time classifications",
        },
        "sector_context": sector_context,
        "candidates": rows,
        "coverage": {
            "input_names": len(fundamentals_by_ticker),
            "in_scope_names": len(eligible),
            "excluded_names": len(excluded),
            "exclusions": excluded,
            "scored_names": len(scored),
            "peer_level_counts": level_counts,
            "insufficient_peer_groups": insufficient_groups,
            "missing_by_factor": missing_by_factor,
            "industries_present": sorted(i for i in by_industry if i),
            "industry_groups_present": sorted(by_group),
            "names_without_industry_group": sum(
                1 for t in eligible if not candidates[t]["industry_group"]),
            "names_without_industry": len(by_industry.get(None, [])),
        },
        "warnings": warnings,
    }
