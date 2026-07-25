"""Deterministic business-stage classifier + stage-appropriate health checks.

Why: a single global cash rule mis-reads whole sectors. A utility spending
capex above CFO IS the business model; a bank's CFO is deposit/loan flow, not
profit; an asset-light software name has no capex to judge. Stage first, then
the checks that mean something for that stage — and an explicit list of the
checks that are actively MISLEADING there, so the digest says "not judged"
instead of quietly scoring a name on a metric that does not apply.

Inputs are exactly what already exists: `snap` from
skills/fundamentals.compute_fundamentals() and `years` from
YFinanceProvider.statements() (annual rows, newest first). No new feed.

Classification runs on ANNUAL statements on purpose: stage is a structural
property and must not flip on one noisy quarter. The .info quarterly fields
(rev_yoy, eps_yoy) stay where they belong — in the entry gate, not here.
"""
from ..data.base import to_number

# Things free data cannot answer. Never score these — say "unknown".
NOT_COMPUTABLE = {
    "cash_runway": "no cash/ST-investments row in _STMT_ROWS (one-line fix: add "
                   "'Cash Cash Equivalents And Short Term Investments' to the "
                   "balance frame — same fetch, no new call)",
    "debt_maturity_wall": "no maturity schedule in any free frame; current_liabilities "
                          "lumps payables with current debt. Proxy only: total_debt/CFO.",
    "ffo_affo": "needs D&A and gains-on-sale; D&A is addable ('Depreciation And "
                "Amortization' in the cashflow frame), gains-on-sale is not. "
                "Use CFO-based coverage instead of a fake FFO.",
    "interest_coverage": "no interest-expense or EBIT row; op_margin is TTM from .info "
                         "and mixes periods with statement revenue.",
    "rd_intensity": "no R&D row — cannot separate asset-light reinvestment from none.",
    "segment_mix": "no segment data — conglomerate/sum-of-parts is not computable.",
    "book_value": "no total-equity row. Derivable as total_debt*100/debt_to_equity, but "
                  "debt_to_equity is a point-in-time .info value against a fiscal-year "
                  "total_debt — treat any P/B or ROE built on it as low confidence.",
}

# Industry substrings (lowercased .info industry). yfinance uses an em dash in
# some versions ("Banks—Regional") and a hyphen in others — substring matching
# sidesteps that entirely.
_FIN_INDUSTRY = ("bank", "insurance", "reinsurance", "capital markets",
                 "credit services", "mortgage")
_FIN_EXCLUDE = ("financial data",)      # SPGI/MSCI-type: asset-light, normal metrics
# NOT "infrastructure" — yfinance's industry for MSFT/ORCL is
# "Software—Infrastructure", which a bare substring match would file as a
# utility. Every entry here must be a term no software name can contain.
_INFRA_INDUSTRY = ("reit", "utilities", "telecom", "midstream", "pipeline",
                   "railroad", "airport", "waste management")
_CYCLICAL_SECTORS = {"Energy", "Basic Materials", "Industrials", "Consumer Cyclical"}
_CYCLICAL_INDUSTRY = ("semiconductor", "auto", "airline", "steel", "shipping",
                      "marine", "homebuilding", "chemicals", "aluminum",
                      "copper", "mining", "luxury goods", "travel")


def _n(row, key):
    return to_number((row or {}).get(key))


def _gross_margin(row):
    rev, cogs = _n(row, "revenue"), _n(row, "cogs")
    if not rev or cogs is None:
        return None
    return (rev - cogs) / rev


def _cagr(new, old, years_apart):
    if not new or not old or new <= 0 or old <= 0:
        return None
    return (new / old) ** (1.0 / years_apart) - 1


def div_yield(snap):
    """Fraction, not percent. yfinance flipped dividendYield to percent units
    (3.42) mid-2025 while the Finnhub path in fundamentals.py still divides by
    100 — so the same field arrives in two units depending on source. Normalize
    at every read site until the provider is fixed."""
    dy = to_number((snap.get("dividend") or {}).get("yield"))
    if dy is None:
        return None
    return dy / 100.0 if dy > 1 else dy


def metrics(snap: dict | None, years: list | None) -> dict:
    """Every derived number the classifier and the checks share. All None-safe."""
    snap = snap or {}
    ys = years or []
    y0, y1, y2 = (ys[0] if ys else {}), (ys[1] if len(ys) > 1 else {}), \
                 (ys[2] if len(ys) > 2 else {})
    rev0, rev1, rev2 = _n(y0, "revenue"), _n(y1, "revenue"), _n(y2, "revenue")
    ni0, ni1 = _n(y0, "net_income"), _n(y1, "net_income")
    cfo0, cfo1 = _n(y0, "cfo"), _n(y1, "cfo")
    capex0 = abs(_n(y0, "capex")) if _n(y0, "capex") is not None else None
    sh0, sh1 = _n(y0, "shares"), _n(y1, "shares")
    gm0, gm1 = _gross_margin(y0), _gross_margin(y1)
    ta0, td0 = _n(y0, "total_assets"), _n(y0, "total_debt")
    mc = to_number(snap.get("market_cap"))
    ni_hist = [_n(y, "net_income") for y in ys[:5]]
    ni_hist = [v for v in ni_hist if v is not None]
    return {
        "years_available": len(ys),
        "sector": snap.get("sector"),
        "industry": (snap.get("industry") or "").lower(),
        "market_cap": mc,
        "revenue": rev0,
        "net_income": ni0,
        "cfo": cfo0,
        "capex": capex0,
        "gross_margin": gm0,
        "gm_delta": None if gm0 is None or gm1 is None else gm0 - gm1,
        "rev_growth_1y": None if not rev1 or rev0 is None else rev0 / rev1 - 1,
        "rev_cagr_3y": _cagr(rev0, rev2, 2),          # 2 gaps across 3 rows
        "capex_to_cfo": None if capex0 is None or not cfo0 or cfo0 <= 0
                        else capex0 / cfo0,
        "capex_to_rev": None if capex0 is None or not rev0 else capex0 / rev0,
        "cfo_yield": None if cfo0 is None or not mc else cfo0 / mc,
        "fcf_yield": None if cfo0 is None or capex0 is None or not mc
                     else (cfo0 - capex0) / mc,
        "burn_shrinking": None if cfo0 is None or cfo1 is None else cfo0 > cfo1,
        "dilution_1y": None if not sh1 or sh0 is None else sh0 / sh1 - 1,
        "roa": None if ni0 is None or not ta0 else ni0 / ta0,
        "debt_to_assets": None if td0 is None or not ta0 else td0 / ta0,
        "debt_to_cfo": None if td0 is None or not cfo0 or cfo0 <= 0 else td0 / cfo0,
        "accrual_gap": None if ni0 is None or cfo0 is None else cfo0 - ni0,
        "ni_improving": None if ni0 is None or ni1 is None else ni0 > ni1,
        # Normalized (mid-cycle) earnings — the only honest way to value a
        # cyclical: trailing P/E is LOWEST at the peak, which is when the
        # position is most dangerous (Graham's normalized-earnings point).
        "norm_pe": None if not ni_hist or not mc or sum(ni_hist) <= 0
                   else mc / (sum(ni_hist) / len(ni_hist)),
        "dividend_yield": div_yield(snap),
        # Distribution coverage out of operating cash — works for REITs and
        # utilities where payout_ratio (earnings-based) is meaningless.
        "payout_of_cfo": None,   # filled below, needs both
    }


def _fill_payout(m):
    dy, mc, cfo = m["dividend_yield"], m["market_cap"], m["cfo"]
    if dy and mc and cfo and cfo > 0:
        m["payout_of_cfo"] = (dy * mc) / cfo
    return m


# ---------------------------------------------------------------- classifier

def classify(snap: dict | None, years: list | None) -> dict:
    """-> {"stage", "reason", "metrics"}. Mutually exclusive by construction:
    first branch that matches wins, and the order encodes what dominates what.

    Order rationale:
      1. financial / regulated_infra are STRUCTURAL (the accounting itself
         differs) — they must be settled before any cash-flow test runs.
      2. distress before early_stage: both burn cash, only one is investable,
         so the melting-ice-cube test gets first look at cash-burners.
      3. cyclical (sector) before the profitable buckets: a cyclical at peak
         earnings looks exactly like a mature cash generator, and mis-labelling
         it there is how you buy the top of the cycle on a 7x P/E.
    """
    m = _fill_payout(metrics(snap, years))
    sector, ind = m["sector"], m["industry"]

    if not snap or (m["years_available"] < 2 and m["net_income"] is None):
        return {"stage": "unknown", "reason": "insufficient statements", "metrics": m}

    if (sector == "Financial Services" or any(k in ind for k in _FIN_INDUSTRY)) \
            and not any(k in ind for k in _FIN_EXCLUDE):
        return {"stage": "financial", "reason": f"sector/industry: {ind or sector}",
                "metrics": m}

    if sector in ("Utilities", "Real Estate") or any(k in ind for k in _INFRA_INDUSTRY):
        return {"stage": "regulated_infra", "reason": f"sector/industry: {ind or sector}",
                "metrics": m}

    d = distress_markers(m)
    if d["count"] >= 3:
        return {"stage": "distress", "reason": "; ".join(d["hits"]), "metrics": m}

    pre_profit = (m["net_income"] is not None and m["net_income"] <= 0) or \
                 (m["cfo"] is not None and m["cfo"] <= 0)
    growing_fast = ((m["rev_cagr_3y"] or 0) >= 0.20 or (m["rev_growth_1y"] or 0) >= 0.20)
    small = (m["revenue"] is None or m["revenue"] < 2e9)
    # Pre-commercial = a SMALL revenue base the market prices on future sales.
    # Revenue SCALE is the necessary condition, not the multiple: Intel at
    # 8.8x sales on $53B of revenue is a high-multiple incumbent (so is MSFT
    # at ~10x), while X-Energy at 44x sales on $94M is genuinely development-
    # stage. Offered as an ALTERNATIVE to fast growth, since a pre-commercial
    # company can have modest early revenue growing slowly. A dying business
    # fails it — the market does not pay 8x sales for one, and the distress
    # branch above catches it first.
    pre_commercial = (
        m["revenue"] == 0
        or (m["revenue"] is not None and m["revenue"] < 2e9
            and (m["market_cap"] or 0) / (m["revenue"] or 1) > 8)
    )
    if pre_profit and (growing_fast or pre_commercial) and (small or pre_commercial):
        return {"stage": "early_stage",
                "reason": "unprofitable but scaling (growth intact, margin not collapsing)",
                "metrics": m}

    # A named cyclical INDUSTRY is decisive. A cyclical SECTOR is only a prior:
    # "Consumer Cyclical" and "Industrials" also contain structural compounders
    # (Amazon is filed under internet retail with a 50% gross margin, +12%
    # revenue and $139B of operating cash flow — sizing that as a tactical
    # cycle trade is simply wrong). Require the sector prior to be corroborated
    # by actual cycle evidence: thin/again-falling margins or lumpy revenue.
    cyclical_industry = any(k in ind for k in _CYCLICAL_INDUSTRY)
    gm, gm_d = m.get("gross_margin"), m.get("gm_delta")
    cycle_evidence = ((gm is not None and gm < 0.35)
                      or (gm_d is not None and gm_d <= -0.03)
                      or (m.get("rev_growth_1y") is not None
                          and m["rev_growth_1y"] < 0.05))
    if cyclical_industry or (sector in _CYCLICAL_SECTORS and cycle_evidence):
        why = ind or sector
        return {"stage": "cyclical",
                "reason": f"sector/industry: {why}" if cyclical_industry
                          else f"{why} + cycle evidence (margin/revenue)",
                "metrics": m}

    reinvesting = ((m["capex_to_cfo"] or 0) >= 0.40
                   or (m["rev_cagr_3y"] or 0) >= 0.10
                   or (m["rev_growth_1y"] or 0) >= 0.10)
    if reinvesting:
        return {"stage": "compounder",
                "reason": f"profitable, reinvesting (capex/CFO {m['capex_to_cfo']}, "
                          f"3y rev CAGR {m['rev_cagr_3y']})", "metrics": m}

    return {"stage": "mature_cash",
            "reason": "profitable, low reinvestment, low growth", "metrics": m}


def distress_markers(m: dict) -> dict:
    """The melting-ice-cube discriminator. Each marker is a fact about the
    business, not about the price. 3+ = distress (veto). Fewer = a cash-burner
    that may simply be early. Deliberately needs BOTH a demand signal (revenue,
    margin) and a financing signal (dilution, leverage) to fire — a company
    growing 40% with a fat gross margin cannot reach 3 no matter how much it
    burns, and a shrinking one with collapsing margin and 20% dilution reaches
    it without any price input at all."""
    hits = []
    # Development-stage carve-out: a pre-commercial business (revenue still
    # growing, and priced by the market on future rather than current sales)
    # legitimately sells its first units below cost — first-of-a-kind reactors,
    # a drug in launch. Gross-margin markers are DEMAND signals for an
    # operating business; applying them here labels "hasn't started working
    # yet" as "worked once and is dying", which is the opposite trade.
    # Revenue must still be GROWING to qualify — a shrinking pre-commercial
    # company gets no exemption.
    rev, mcap = m.get("revenue"), m.get("market_cap")
    pre_commercial = (
        (m["rev_growth_1y"] is None or m["rev_growth_1y"] >= 0)
        and rev is not None and mcap is not None and rev > 0
        and mcap / rev > 8
    )
    if m["rev_growth_1y"] is not None and m["rev_growth_1y"] < -0.05:
        hits.append(f"revenue -{abs(m['rev_growth_1y']):.0%} YoY")
    if not pre_commercial:
        if m["gm_delta"] is not None and m["gm_delta"] <= -0.03:
            hits.append(f"gross margin -{abs(m['gm_delta'])*100:.0f}bp YoY")
        if m["gross_margin"] is not None and m["gross_margin"] < 0.05:
            hits.append("gross margin <5% — selling near/below cost")
    if m["cfo"] is not None and m["cfo"] < 0 and m["burn_shrinking"] is False:
        hits.append("cash burn deepening")
    if m["dilution_1y"] is not None and m["dilution_1y"] > 0.15:
        hits.append(f"share count +{m['dilution_1y']:.0%} — financing under duress")
    if (m["debt_to_assets"] or 0) > 0.60 or (m["debt_to_cfo"] or 0) > 8:
        hits.append("balance-sheet stress (debt/assets >60% or debt/CFO >8y)")
    return {"count": len(hits), "hits": hits}


# ------------------------------------------------- stage-appropriate checks
#
# NOT_APPLICABLE is the deliverable half nobody writes down: the checks that
# must be SKIPPED, not merely failed, in each bucket. A skipped check drops out
# of the denominator (the existing `known` pattern in fundamental_conviction);
# a failed one silently penalizes a healthy company for its own accounting.
NOT_APPLICABLE = {
    "financial": {
        "current_ratio": "banks/insurers have no meaningful working-capital cycle",
        "debt_to_equity": "10-20x leverage IS the business — the >200% veto kills "
                          "every bank, including DBS",
        "cfo_yield": "CFO is dominated by deposit/loan and reserve flows; a growing "
                     "bank can print negative CFO in a good year",
        "fcf_yield": "same, plus capex is immaterial",
        "capex_to_cfo": "immaterial capex base",
        "piotroski.liquidity_up": "current ratio input is meaningless",
        "piotroski.turnover_up": "asset turnover for a bank is a leverage artifact",
    },
    "regulated_infra": {
        "fcf_yield": "structurally negative by design — rate base/asset growth is "
                     "funded externally against contracted or regulated returns",
        "capex_to_cfo": "above 1.0 is the model, not a red flag",
        "current_ratio": "these run negative working capital deliberately",
        "pe_ttm (REIT only)": "depreciation on appreciating property makes GAAP EPS "
                              "meaningless — and FFO/AFFO is NOT computable here "
                              "(see NOT_COMPUTABLE); use payout_of_cfo instead",
        "debt_to_equity": "regulated capital structures sit at 100-250% by design",
    },
    "early_stage": {
        "pe_ttm": "no E",
        "peg": "no E",
        "cfo_yield": "negative by definition",
        "fcf_yield": "negative by definition",
        "piotroski": "6 of 9 criteria need profits or a stable asset base",
        "eps_yoy": "noise on a small negative base",
    },
    "cyclical": {
        "pe_ttm": "INVERTED at the cycle — lowest P/E is peak earnings, i.e. the most "
                  "dangerous entry. Use norm_pe (mid-cycle earnings) instead",
        "rev_growth_1y": "cycle position, not business quality",
        "gm_delta": "moves with the commodity, not with competitiveness",
    },
    "compounder": {
        "fcf_yield": "capex is the thesis (MSFT/AMZN data centers) — judging FCF here "
                     "vetoes exactly the names worth owning; use cfo_yield",
        "dividend_yield": "capital returned instead of reinvested is a demerit here",
    },
    "mature_cash": {
        "rev_growth_1y > 5%": "KHC/HON will never clear it; the return comes from FCF "
                              "yield + buyback + dividend, not from growth",
        "peg": "meaningless at ~0 growth",
    },
    "distress": {},
    "unknown": {},
}


def health_checks(stage: str, m: dict) -> dict:
    """-> {check: True/False/None}. None = unknown or not applicable; caller
    drops Nones from the denominator (same pattern as fundamental_conviction)."""
    def ge(v, t):
        return None if v is None else v >= t

    def le(v, t):
        return None if v is None else v <= t

    if stage == "mature_cash":
        return {
            "fcf_yield_ok": ge(m["fcf_yield"], 0.05),
            "cash_conversion": None if m["accrual_gap"] is None else m["accrual_gap"] > 0,
            "not_shrinking": None if m["rev_growth_1y"] is None
                             else m["rev_growth_1y"] > -0.03,
            "margin_stable": None if m["gm_delta"] is None else m["gm_delta"] > -0.02,
            "buyback_or_div": None if m["dilution_1y"] is None and not m["dividend_yield"]
                              else bool((m["dilution_1y"] or 0) <= 0.005
                                        or (m["dividend_yield"] or 0) > 0.01),
            "leverage_ok": le(m["debt_to_cfo"], 4.0),
            "returns_ok": ge(m["roa"], 0.05),
        }
    if stage == "compounder":
        return {
            "cfo_yield_ok": ge(m["cfo_yield"], 0.03),
            "growing": ge(m["rev_cagr_3y"], 0.08),
            "margin_holding": None if m["gm_delta"] is None else m["gm_delta"] > -0.02,
            "cash_conversion": None if m["accrual_gap"] is None else m["accrual_gap"] > 0,
            "reinvestment_paying_off": m["ni_improving"],
            "no_dilution": le(m["dilution_1y"], 0.02),
            "leverage_ok": le(m["debt_to_cfo"], 4.0),
        }
    if stage == "regulated_infra":
        return {
            "cfo_positive": None if m["cfo"] is None else m["cfo"] > 0,
            "distribution_covered": le(m["payout_of_cfo"], 0.80),
            "leverage_ok": le(m["debt_to_cfo"], 8.0),   # 8y is normal here, not stress
            "rate_base_growing": ge(m["rev_growth_1y"], 0.0),
            "no_equity_raid": le(m["dilution_1y"], 0.05),  # REITs/utils issue equity
            "yield_real": ge(m["dividend_yield"], 0.02),
        }
    if stage == "financial":
        return {
            "roa_ok": ge(m["roa"], 0.008),          # 0.8% ROA — the bank standard
            "profitable": None if m["net_income"] is None else m["net_income"] > 0,
            "revenue_growing": ge(m["rev_growth_1y"], 0.0),
            "no_dilution": le(m["dilution_1y"], 0.02),
            "payout_covered": le(m["payout_of_cfo"], 0.90) if m["payout_of_cfo"]
                              else None,
            "earnings_improving": m["ni_improving"],
        }
    if stage == "cyclical":
        return {
            "not_peak_priced": le(m["norm_pe"], 18.0),   # vs mid-cycle, not trailing
            "profitable_through_cycle": None if not m["norm_pe"] else True,
            "balance_sheet_survives_trough": le(m["debt_to_assets"], 0.40),
            "no_dilution": le(m["dilution_1y"], 0.03),
            "cash_generative": None if m["cfo"] is None else m["cfo"] > 0,
        }
    if stage == "early_stage":
        return {
            "growth_intact": ge(m["rev_growth_1y"], 0.20),
            "gross_margin_viable": ge(m["gross_margin"], 0.30),
            "margin_improving": None if m["gm_delta"] is None else m["gm_delta"] > -0.01,
            "burn_shrinking": m["burn_shrinking"],
            "dilution_tolerable": le(m["dilution_1y"], 0.10),
            "runway_ok": None,   # NOT_COMPUTABLE["cash_runway"] — never fake it
        }
    return {}


# --------------------------------------------------------------- eligibility
#
# Straight answer to "what is even investable for a long-term value book".
# max_position_pct is a CAP, not a target; sleeve_cap_pct bounds the whole
# bucket. Beta enters here, which is where the stated objective (max alpha,
# min beta) actually becomes a number instead of a slide.
SLEEVE = {
    "mature_cash":     {"eligible": True,  "sleeve": "core",        "max_position_pct": 8.0,  "sleeve_cap_pct": 60.0},
    "compounder":      {"eligible": True,  "sleeve": "core",        "max_position_pct": 8.0,  "sleeve_cap_pct": 60.0},
    "regulated_infra": {"eligible": True,  "sleeve": "ballast",     "max_position_pct": 6.0,  "sleeve_cap_pct": 30.0},
    "financial":       {"eligible": True,  "sleeve": "ballast",     "max_position_pct": 6.0,  "sleeve_cap_pct": 25.0},
    "cyclical":        {"eligible": True,  "sleeve": "tactical",    "max_position_pct": 4.0,  "sleeve_cap_pct": 20.0},
    "early_stage":     {"eligible": True,  "sleeve": "speculative", "max_position_pct": 2.0,  "sleeve_cap_pct": 12.0},
    "distress":        {"eligible": False, "sleeve": "veto",        "max_position_pct": 0.0,  "sleeve_cap_pct": 0.0},
    "unknown":         {"eligible": False, "sleeve": "watch",       "max_position_pct": 0.0,  "sleeve_cap_pct": 0.0},
}


def size_cap(stage: str, beta: float | None) -> float:
    """Stage cap scaled by beta — the missing link between the risk skill (which
    already computes beta) and the sizing tier (which ignores it). Beta 2.0
    halves the cap; beta 0.5 is allowed 1.5x. Keeps portfolio beta down without
    banning high-beta names outright."""
    cap = SLEEVE.get(stage, SLEEVE["unknown"])["max_position_pct"]
    if not cap or beta is None or beta <= 0:
        return cap
    return round(cap * min(1.5, 1.0 / max(beta, 0.5)), 2)


if __name__ == "__main__":  # offline self-check — no network, fixtures only
    def mk(sector, industry, mc, rows, **info):
        return ({"sector": sector, "industry": industry, "market_cap": mc,
                 "valuation": {}, "growth": {}, "margins": {}, "balance": {},
                 "dividend": {"yield": info.get("dy")}, "analyst": {}}, rows)

    # compounder funding capex out of operations (MSFT-shaped)
    snap, yrs = mk("Technology", "Software—Infrastructure", 3_500e9, [
        {"revenue": 281e9, "cogs": 88e9, "net_income": 101e9, "cfo": 136e9,
         "capex": -64e9, "shares": 7440e6, "total_assets": 619e9, "total_debt": 60e9},
        {"revenue": 245e9, "cogs": 74e9, "net_income": 88e9, "cfo": 118e9,
         "capex": -44e9, "shares": 7470e6, "total_assets": 512e9, "total_debt": 67e9},
        {"revenue": 211e9, "cogs": 65e9, "net_income": 72e9, "cfo": 87e9,
         "capex": -28e9, "shares": 7500e6, "total_assets": 411e9, "total_debt": 79e9}])
    r = classify(snap, yrs)
    assert r["stage"] == "compounder", r
    assert "fcf_yield" in NOT_APPLICABLE["compounder"]
    assert health_checks("compounder", r["metrics"])["cfo_yield_ok"] is True

    # bank (DBS-shaped): must NOT be judged on CFO/leverage/current ratio
    snap, yrs = mk("Financial Services", "Banks—Regional", 100e9, [
        {"revenue": 22e9, "net_income": 8.5e9, "cfo": -3e9, "capex": -0.2e9,
         "shares": 2840e6, "total_assets": 550e9, "total_debt": 60e9},
        {"revenue": 20e9, "net_income": 8.0e9, "cfo": 12e9, "capex": -0.2e9,
         "shares": 2850e6, "total_assets": 520e9, "total_debt": 55e9}], dy=5.8)
    r = classify(snap, yrs)
    assert r["stage"] == "financial", r
    hc = health_checks("financial", r["metrics"])
    assert hc["roa_ok"] is True and "cfo_yield" not in hc      # skipped, not failed
    assert abs(r["metrics"]["dividend_yield"] - 0.058) < 1e-9  # percent-unit guard

    # pre-profit growth (Tempus-shaped): burns cash, still investable, capped
    snap, yrs = mk("Healthcare", "Health Information Services", 9e9, [
        {"revenue": 1.1e9, "cogs": 0.62e9, "net_income": -0.7e9, "cfo": -0.18e9,
         "capex": -0.03e9, "shares": 170e6, "total_assets": 1.6e9, "total_debt": 0.4e9},
        {"revenue": 0.69e9, "cogs": 0.42e9, "net_income": -0.9e9, "cfo": -0.3e9,
         "capex": -0.04e9, "shares": 162e6, "total_assets": 1.4e9, "total_debt": 0.4e9}])
    r = classify(snap, yrs)
    assert r["stage"] == "early_stage", r
    assert health_checks("early_stage", r["metrics"])["runway_ok"] is None
    assert SLEEVE["early_stage"]["max_position_pct"] == 2.0

    # melting ice cube: shrinking, margin collapsing, diluting, levered
    snap, yrs = mk("Technology", "Software—Application", 0.4e9, [
        {"revenue": 0.30e9, "cogs": 0.26e9, "net_income": -0.25e9, "cfo": -0.12e9,
         "capex": -0.01e9, "shares": 300e6, "total_assets": 0.5e9, "total_debt": 0.35e9},
        {"revenue": 0.42e9, "cogs": 0.29e9, "net_income": -0.10e9, "cfo": -0.05e9,
         "capex": -0.01e9, "shares": 200e6, "total_assets": 0.7e9, "total_debt": 0.30e9}])
    r = classify(snap, yrs)
    assert r["stage"] == "distress", r
    assert SLEEVE["distress"]["eligible"] is False

    # utility: capex > CFO is the model, must not land in distress
    snap, yrs = mk("Utilities", "Utilities—Regulated Electric", 60e9, [
        {"revenue": 20e9, "cogs": 12e9, "net_income": 2.2e9, "cfo": 6.0e9,
         "capex": -8.5e9, "shares": 700e6, "total_assets": 90e9, "total_debt": 40e9},
        {"revenue": 19e9, "cogs": 11.5e9, "net_income": 2.0e9, "cfo": 5.6e9,
         "capex": -7.9e9, "shares": 690e6, "total_assets": 84e9, "total_debt": 37e9}],
        dy=0.035)
    r = classify(snap, yrs)
    assert r["stage"] == "regulated_infra", r
    hc = health_checks("regulated_infra", r["metrics"])
    assert hc["cfo_positive"] is True and hc["distribution_covered"] is True

    # cyclical at peak: 6x trailing P/E, 20x mid-cycle — must fail, not pass
    snap, yrs = mk("Basic Materials", "Steel", 12e9, [
        {"revenue": 30e9, "cogs": 25e9, "net_income": 2.0e9, "cfo": 2.4e9,
         "capex": -1.0e9, "shares": 250e6, "total_assets": 25e9, "total_debt": 6e9},
        {"revenue": 28e9, "cogs": 26.5e9, "net_income": 0.2e9, "cfo": 0.6e9,
         "capex": -1.0e9, "shares": 252e6, "total_assets": 24e9, "total_debt": 6e9},
        {"revenue": 26e9, "cogs": 25.6e9, "net_income": -0.4e9, "cfo": 0.1e9,
         "capex": -1.0e9, "shares": 255e6, "total_assets": 24e9, "total_debt": 6e9}])
    r = classify(snap, yrs)
    assert r["stage"] == "cyclical", r
    assert health_checks("cyclical", r["metrics"])["not_peak_priced"] is False

    assert size_cap("compounder", 2.0) == 4.0 and size_cap("distress", 0.5) == 0.0
    print("business_stage self-check OK")
