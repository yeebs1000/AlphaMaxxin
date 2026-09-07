#!/usr/bin/env python3
"""Sector-relative research probe — Phase 1 measurement harness.

EXPERIMENTAL RESEARCH MEASUREMENT — not wired to reports, signals, sizing, or
orders. This script produces a coverage/ranking artifact so the owner can judge
whether sector-relative analysis is worth integrating. It is not a report, not
a recommendation, and nothing reads its output automatically.

It is a thin adapter around two pure modules:

    app.data.security_master   identity + two-level taxonomy
    app.skills.sector_relative peer percentiles (no I/O of any kind)

What it is allowed to touch:
  * an explicit JSON fixture (`--input`)                    — zero provider calls
  * the on-disk DiskTTLCache written by earlier free-feed
    fetches, read directly (`--cache-scan`)                 — zero network
  * `data_store/price_panel.json` for bars                  — zero network
  * bounded read-only IBKR ContractDetails (`--ibkr-taxonomy`)

What it must never touch: any LLM, any account/position API, any order API, any
broker market-data or scanner subscription. There is no code path here that can
reach them.

Examples
--------
    # fixture mode, provably offline
    sector_relative_probe.py --input fixture.json --region US \\
        --sector Technology --out /tmp/probe.json

    # cached free-provider data already on this box
    sector_relative_probe.py --cache-scan --region US --sector Technology \\
        --out data_store/sector_research/us-technology.json
"""
import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.data import security_master as sm            # noqa: E402
from app.skills import sector_relative as sr          # noqa: E402
from app.skills import sector_shortlist as ssl        # noqa: E402
from app.skills.fundamentals import (compute_fundamentals,  # noqa: E402
                                     f_score)

BANNER = ("EXPERIMENTAL RESEARCH MEASUREMENT — not wired to reports, "
          "signals, sizing, or orders")

DEFAULT_ARTIFACT_DIR = REPO_ROOT / "data_store" / "sector_research"
DEFAULT_PRICE_PANEL = REPO_ROOT / "data_store" / "price_panel.json"

# Namespace written by YFinanceProvider.fundamentals(). Read directly rather
# than through DiskTTLCache.get() so an EXPIRED entry is still usable for a
# research measurement — with its age reported, which get() cannot do because
# it returns None past the TTL.
FUNDAMENTALS_NAMESPACE = "yf_fundamentals"
STATEMENTS_NAMESPACE = "yf_statements"
OHLCV_NAMESPACE = "yahoo_ohlcv"
OHLCV_KEY_SUFFIX = ":1d:2y"   # what universe_backfill --dataset ohlcv writes


def default_cache_root() -> Path:
    override = os.environ.get("ALPHAMAXXIN_CACHE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "alphamaxxin"


# ---------------------------------------------------------------------------
# input loading — each returns (fundamentals, bars, taxonomy, provenance)
# ---------------------------------------------------------------------------
def load_from_fixture(path) -> tuple:
    """Explicit JSON input. Performs zero provider calls of any kind, which is
    what makes the offline test meaningful."""
    with open(path, "r", encoding="utf-8") as handle:
        blob = json.load(handle)
    provenance = {
        "mode": "fixture",
        "path": str(path),
        "provider_calls": 0,
        "note": "explicit fixture input; no provider was contacted",
    }
    return (blob.get("fundamentals") or {}, blob.get("bars") or {},
            blob.get("taxonomy") or {}, provenance)


def load_from_cache(cache_root, price_panel_path, *, as_of: str) -> tuple:
    """Read what earlier free-feed fetches already wrote to disk.

    No network, no broker: this walks cache files that exist. Staleness is
    reported per name rather than hidden, because these fundamentals were
    fetched on whatever day they were fetched, not as of `as_of`.
    """
    cache_root = Path(cache_root)
    namespace_dir = cache_root / FUNDAMENTALS_NAMESPACE
    fundamentals, ages, skipped = {}, {}, 0
    now = time.time()
    for entry_path in sorted(namespace_dir.glob("*.json")):
        try:
            with open(entry_path, "r", encoding="utf-8") as handle:
                entry = json.load(handle)
        except (OSError, ValueError):
            skipped += 1
            continue
        ticker, payload = entry.get("key"), entry.get("payload")
        if not ticker or not isinstance(payload, dict):
            skipped += 1
            continue
        snapshot = compute_fundamentals(ticker, payload)
        if snapshot:
            fundamentals[ticker] = snapshot
            ages[ticker] = round((now - float(entry.get("fetched_at", 0))) / 86400, 2)

    # Piotroski inputs live in their own cache namespace and their own
    # function, so the snapshot has no f_score until they are joined here.
    # Without this the quality family runs on two margins and the statements
    # backfill is a directory nothing reads.
    statements_dir = cache_root / STATEMENTS_NAMESPACE
    with_f_score = 0
    for entry_path in sorted(statements_dir.glob("*.json")):
        try:
            with open(entry_path, "r", encoding="utf-8") as handle:
                entry = json.load(handle)
        except (OSError, ValueError):
            continue
        ticker, years = entry.get("key"), entry.get("payload")
        if ticker not in fundamentals or not isinstance(years, list):
            continue
        block = f_score(years)
        if block:
            fundamentals[ticker] = {**fundamentals[ticker], "f_score": block}
            with_f_score += 1

    bars, panel_mtime = {}, None
    panel_path = Path(price_panel_path)
    if panel_path.exists():
        with open(panel_path, "r", encoding="utf-8") as handle:
            bars = json.load(handle)
        panel_mtime = datetime.datetime.fromtimestamp(
            panel_path.stat().st_mtime, datetime.timezone.utc).isoformat()
    panel_names = len(bars)

    # The OHLCV cache is the real bar source: price_panel.json covers 97 names
    # against a universe of 2,270. Cache entries win where both exist — they
    # are fresher and were fetched for this purpose.
    ohlcv_dir = cache_root / OHLCV_NAMESPACE
    ohlcv_names, ohlcv_skipped = 0, 0
    for entry_path in sorted(ohlcv_dir.glob("*.json")):
        try:
            with open(entry_path, "r", encoding="utf-8") as handle:
                entry = json.load(handle)
        except (OSError, ValueError):
            ohlcv_skipped += 1
            continue
        key, payload = entry.get("key") or "", entry.get("payload")
        if not key.endswith(OHLCV_KEY_SUFFIX) or not isinstance(payload, dict):
            continue
        ticker = key[: -len(OHLCV_KEY_SUFFIX)]
        series = _bars_from_ohlcv(payload)
        if series:
            bars[ticker] = series
            ohlcv_names += 1

    provenance = {
        "mode": "cache-scan",
        "provider_calls": 0,
        "network_calls": 0,
        "fundamentals_cache": str(namespace_dir),
        "fundamentals_names": len(fundamentals),
        "fundamentals_unreadable": skipped,
        "fundamentals_age_days_median": _median_age(ages),
        "fundamentals_age_days_max": max(ages.values()) if ages else None,
        "statements_cache": str(statements_dir),
        "names_with_f_score": with_f_score,
        "price_panel": str(panel_path) if panel_path.exists() else None,
        "price_panel_mtime_utc": panel_mtime,
        "price_panel_names": panel_names,
        "ohlcv_cache": str(ohlcv_dir),
        "ohlcv_names": ohlcv_names,
        "ohlcv_unreadable": ohlcv_skipped,
        "bars_total_names": len(bars),
        "limitations": [
            "cached fundamentals carry their own fetch date, NOT as_of — see "
            "fundamentals_age_days_max",
            "Yahoo sector/industry labels are CURRENT, not point-in-time",
            "price_panel covers today's surviving names only (survivorship bias)",
        ],
    }
    return fundamentals, bars, {}, provenance


def _bars_from_ohlcv(payload: dict) -> dict:
    """Column-oriented cache payload -> {"YYYY-MM-DD": close}.

    Nulls are dropped rather than carried: yfinance emits None for holidays and
    halts, and a null close in a return calculation is worse than a missing bar.
    """
    timestamps = payload.get("timestamps") or []
    closes = payload.get("closes") or []
    series = {}
    for stamp, close in zip(timestamps, closes):
        if stamp is None or close is None:
            continue
        try:
            date = datetime.datetime.fromtimestamp(
                float(stamp), datetime.timezone.utc).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        series[date] = close
    return series


def _median_age(ages: dict):
    if not ages:
        return None
    ordered = sorted(ages.values())
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else round(
        (ordered[mid - 1] + ordered[mid]) / 2, 2)


def enrich_with_ibkr_taxonomy(fundamentals: dict, *, region: str,
                              max_requests: int) -> tuple:
    """Bounded, read-only ContractDetails for a sample of names.

    Imported lazily so that a run without --ibkr-taxonomy cannot reach the
    broker module at all. Contract metadata only — the adapter connects
    read-only with every startup account/order fetch disabled.
    """
    from app.brokers.ibkr_client import fetch_contract_taxonomy   # noqa: PLC0415
    from app.data.index_constituents import _IBKR_REGION          # noqa: PLC0415

    region_info = _IBKR_REGION.get(region)
    if not region_info:
        return {}, {"requested": 0, "error": f"no IBKR spec for region {region}"}
    exchange, currency, to_local = region_info
    specs = [{"key": t, "symbol": to_local(t), "exchange": exchange,
              "currency": currency}
             for t in sorted(fundamentals)[:max_requests]]
    started = time.time()
    rows = fetch_contract_taxonomy(specs, max_requests=max_requests)
    elapsed = round(time.time() - started, 2)
    if rows is None:
        return {}, {"requested": len(specs), "resolved": 0, "elapsed_s": elapsed,
                    "error": "ib_async unavailable or gateway unreachable"}
    resolved = {k: v for k, v in rows.items() if v}
    return resolved, {"requested": len(specs), "resolved": len(resolved),
                      "unresolved": len(specs) - len(resolved),
                      "elapsed_s": elapsed}


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------
def build_security_master(fundamentals: dict, ibkr_rows: dict, *, region: str,
                          include_reits: bool, include_catalist: bool,
                          prefer: str) -> tuple:
    raw_rows, off_region = [], {}
    for ticker in sorted(fundamentals):
        snapshot = fundamentals[ticker] or {}
        ibkr = ibkr_rows.get(ticker) or {}
        # Region comes from the ticker, never from the requested scope. Pooling
        # HK/JP names into a US distribution compares raw multiples across
        # currencies and disclosure regimes, which the brief forbids.
        row_region = sm.region_for_ticker(ticker)
        if row_region != region:
            off_region[ticker] = row_region or "out_of_scope"
            continue
        raw_rows.append({
            "region": row_region,
            "ticker": ticker,
            "source_symbol": ticker,
            "universe_source": "alphamaxxin_cache",
            "con_id": ibkr.get("con_id"),
            "local_symbol": ibkr.get("local_symbol"),
            "primary_exchange": ibkr.get("primary_exchange"),
            "currency": ibkr.get("currency") or snapshot.get("currency"),
            "long_name": ibkr.get("long_name") or snapshot.get("name"),
            "stock_type": ibkr.get("stock_type"),
            "ibkr_industry": ibkr.get("ibkr_industry"),
            "ibkr_category": ibkr.get("ibkr_category"),
            "yahoo_sector": snapshot.get("sector"),
            "yahoo_industry": snapshot.get("industry"),
        })
    rows = [sm.build_row(r, prefer=prefer, include_reits=include_reits,
                         include_catalist=include_catalist) for r in raw_rows]
    unique, duplicates = sm.dedupe_rows(rows)
    return unique, duplicates, off_region


def run_probe(*, fundamentals, bars, taxonomy_override, region, sector, as_of,
              provenance, ibkr_rows=None, ibkr_stats=None, prefer="ibkr",
              include_reits=False, include_catalist=False,
              profile=None) -> dict:
    started = time.time()
    rows, duplicates, off_region = build_security_master(
        fundamentals, ibkr_rows or {}, region=region, include_reits=include_reits,
        include_catalist=include_catalist, prefer=prefer)
    audit = sm.coverage_audit(rows, duplicates=duplicates,
                              elapsed_s=round(time.time() - started, 3))
    by_other_region = {}
    for other in off_region.values():
        by_other_region[other] = by_other_region.get(other, 0) + 1
    audit["off_region_dropped"] = len(off_region)
    audit["off_region_by_region"] = by_other_region

    taxonomy_by_ticker = dict(taxonomy_override or {})
    included = set()
    for row in rows:
        if not row["included"]:
            continue
        included.add(row["ticker"])
        taxonomy_by_ticker.setdefault(row["ticker"], row)

    scoped_fundamentals = {t: fundamentals[t] for t in fundamentals if t in included}
    analysis = sr.analyze_sector_relative(
        scoped_fundamentals, bars, region=region, sector=sector, as_of=as_of,
        profile=profile or sr.NULL_V1_PROFILE,
        taxonomy_by_ticker=taxonomy_by_ticker,
        industry_groups=sm.INDUSTRY_GROUPS)

    return {
        "banner": BANNER,
        "artifact_schema": "sector_probe-1",
        "generated_note": "reproducible from the recorded inputs and as_of",
        "as_of": as_of,
        "scope": {"region": region, "sector": sector},
        "input_provenance": provenance,
        "ibkr_taxonomy": ibkr_stats or {"requested": 0,
                                        "note": "not requested this run"},
        "security_master": {
            "schema_version": sm.SCHEMA_VERSION,
            "taxonomy_version": sm.TAXONOMY_VERSION,
            "prefer": prefer,
            "coverage_audit": audit,
        },
        "analysis": analysis,
        # The canonical membership and order, computed in Python. Production
        # integration is blocked (brief §3.7) until the rendered list comes
        # from here rather than from model prose — so it ships with the
        # artifact from the start, before any lens exists to be tempted by it.
        "shortlist": ssl.build_shortlist(analysis, limit=10),
        "limitations": [
            "current classifications, NOT point-in-time — a 2016 bar carries a "
            "2026 label if one is ever joined to it",
            "no point-in-time fundamentals exist on this box; nothing here "
            "supports a fundamental backtest",
            "cached universe reflects surviving names only (survivorship bias)",
            "null-v1 is a baseline profile, not a thesis; no sector profile is "
            "enabled",
            "this artifact measures coverage and contract behaviour, not edge",
        ],
    }


def write_artifact(artifact: dict, path, *, force: bool) -> Path:
    """Atomic write that refuses to clobber. An overwritten measurement cannot
    be compared with the one it replaced."""
    path = Path(path)
    if path.exists() and not force:
        raise FileExistsError(
            f"{path} exists — pass --force to overwrite it deliberately")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(artifact, handle, indent=1, allow_nan=False, sort_keys=False)
        handle.write("\n")
    os.replace(tmp, path)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="explicit JSON fixture; zero provider calls")
    source.add_argument("--cache-scan", action="store_true",
                        help="read free-provider data already cached on disk")
    parser.add_argument("--region", required=True, choices=list(sm.REGIONS))
    parser.add_argument("--sector", default=None,
                        help="required unless --sweep")
    parser.add_argument("--as-of", required=True,
                        help="YYYY-MM-DD; bars after this date are ignored")
    parser.add_argument("--out", help="artifact path")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing artifact")
    parser.add_argument("--ibkr-taxonomy", action="store_true",
                        help="bounded read-only ContractDetails enrichment")
    parser.add_argument("--max-taxonomy", type=int, default=50,
                        help="cap on ContractDetails requests (default 50)")
    parser.add_argument("--prefer", choices=("ibkr", "yahoo"), default="ibkr")
    parser.add_argument("--include-reits", action="store_true")
    parser.add_argument("--include-catalist", action="store_true")
    parser.add_argument("--cache-root", default=None)
    parser.add_argument("--price-panel", default=str(DEFAULT_PRICE_PANEL))
    parser.add_argument("--print-summary", action="store_true")
    parser.add_argument("--sweep", action="store_true",
                        help="run every sector in the region that clears the "
                             "peer minimum, one artifact each plus an index")
    return parser


def sectors_present(fundamentals: dict, region: str) -> dict:
    """Sector -> in-region name count, so a sweep can skip sectors that cannot
    reach the peer minimum instead of writing empty artifacts."""
    counts = {}
    for ticker, snapshot in (fundamentals or {}).items():
        if sm.region_for_ticker(ticker) != region:
            continue
        sector = (snapshot or {}).get("sector")
        if sector:
            counts[sector] = counts.get(sector, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.input:
        fundamentals, bars, taxonomy, provenance = load_from_fixture(args.input)
    else:
        fundamentals, bars, taxonomy, provenance = load_from_cache(
            args.cache_root or default_cache_root(), args.price_panel,
            as_of=args.as_of)

    ibkr_rows, ibkr_stats = {}, None
    if args.ibkr_taxonomy:
        ibkr_rows, ibkr_stats = enrich_with_ibkr_taxonomy(
            fundamentals, region=args.region, max_requests=args.max_taxonomy)

    if args.sweep:
        return run_sweep(args, fundamentals, bars, taxonomy, ibkr_rows, ibkr_stats)
    if not args.sector:
        print("--sector is required unless --sweep is given", file=sys.stderr)
        return 2

    artifact = run_probe(
        fundamentals=fundamentals, bars=bars, taxonomy_override=taxonomy,
        region=args.region, sector=args.sector, as_of=args.as_of,
        provenance=provenance, ibkr_rows=ibkr_rows, ibkr_stats=ibkr_stats,
        prefer=args.prefer, include_reits=args.include_reits,
        include_catalist=args.include_catalist)

    out = Path(args.out) if args.out else (
        DEFAULT_ARTIFACT_DIR /
        f"{args.region.lower()}-{args.sector.lower().replace(' ', '-')}-{args.as_of}.json")
    written = write_artifact(artifact, out, force=args.force)

    analysis = artifact["analysis"]
    audit = artifact["security_master"]["coverage_audit"]
    print(BANNER)
    print(f"artifact          {written}")
    print(f"scope             {args.region} / {args.sector}  as_of={args.as_of}")
    print(f"universe rows     {audit['rows_in']} "
          f"(included {audit['rows_included']}, "
          f"off-region dropped {audit['off_region_dropped']})")
    print(f"sector fill rate  {audit['sector_fill_rate']}  "
          f"industry {audit['industry_fill_rate']}")
    print(f"in scope          {analysis['coverage']['in_scope_names']}")
    print(f"scored            {analysis['coverage']['scored_names']}")
    print(f"peer levels       {analysis['coverage']['peer_level_counts']}")
    for warning in analysis["warnings"]:
        print(f"  warning: {warning}")
    if args.print_summary:
        for row in analysis["candidates"][:10]:
            print(f"  {row['experimental_rank'] or '-':>3} {row['ticker']:<12} "
                  f"score={row['experimental_score']} "
                  f"level={row['peer_level_used']} n={row['peer_count']}")
    return 0


def run_sweep(args, fundamentals, bars, taxonomy, ibkr_rows, ibkr_stats) -> int:
    """One artifact per sector, plus an index summarising peer-level coverage.

    The index is the point: it shows, sector by sector, how many names reached
    an INDUSTRY-level peer pool versus how many fell back to sector. That ratio
    is what decides whether the industry tier is worth keeping.
    """
    counts = sectors_present(fundamentals, args.region)
    out_dir = Path(args.out) if args.out else DEFAULT_ARTIFACT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    index, skipped = [], []
    for sector, count in counts.items():
        if count < sr.MIN_PEERS:
            skipped.append({"sector": sector, "names": count,
                            "reason": f"below MIN_PEERS={sr.MIN_PEERS}"})
            continue
        artifact = run_probe(
            fundamentals=fundamentals, bars=bars, taxonomy_override=taxonomy,
            region=args.region, sector=sector, as_of=args.as_of,
            provenance=provenance_for_sweep(args), ibkr_rows=ibkr_rows,
            ibkr_stats=ibkr_stats, prefer=args.prefer,
            include_reits=args.include_reits,
            include_catalist=args.include_catalist)
        slug = sector.lower().replace(" ", "-").replace("/", "-")
        path = out_dir / f"{args.region.lower()}-{slug}-{args.as_of}.json"
        write_artifact(artifact, path, force=True)
        coverage = artifact["analysis"]["coverage"]
        levels = coverage["peer_level_counts"]
        index.append({
            "sector": sector,
            "in_scope": coverage["in_scope_names"],
            "scored": coverage["scored_names"],
            "industry_level": levels.get("industry", 0),
            "sector_level": levels.get("sector", 0),
            "insufficient": levels.get("insufficient_peers", 0),
            "industries_present": len(coverage["industries_present"]),
            "artifact": str(path),
        })

    summary = {
        "banner": BANNER,
        "artifact_schema": "sector_sweep_index-1",
        "region": args.region, "as_of": args.as_of,
        "min_peers": sr.MIN_PEERS,
        "sectors_run": index, "sectors_skipped": skipped,
        "totals": {
            "in_scope": sum(row["in_scope"] for row in index),
            "industry_level": sum(row["industry_level"] for row in index),
            "sector_level": sum(row["sector_level"] for row in index),
        },
    }
    write_artifact(summary, out_dir / f"index-{args.region.lower()}-{args.as_of}.json",
                   force=True)

    print(BANNER)
    print(f"sweep {args.region}  as_of={args.as_of}  MIN_PEERS={sr.MIN_PEERS}\n")
    print(f"{'sector':26s} {'names':>6s} {'scored':>7s} {'industry':>9s} "
          f"{'sector':>7s} {'inds':>5s}")
    for row in index:
        print(f"{row['sector'][:26]:26s} {row['in_scope']:6d} {row['scored']:7d} "
              f"{row['industry_level']:9d} {row['sector_level']:7d} "
              f"{row['industries_present']:5d}")
    totals = summary["totals"]
    share = (totals["industry_level"] / totals["in_scope"]
             if totals["in_scope"] else 0)
    print(f"\ntotal in scope {totals['in_scope']} · industry-level "
          f"{totals['industry_level']} ({share:.0%}) · sector-level "
          f"{totals['sector_level']}")
    for row in skipped:
        print(f"  skipped {row['sector']}: {row['names']} names, {row['reason']}")
    return 0


def provenance_for_sweep(args) -> dict:
    return {"mode": "cache-scan (sweep)", "provider_calls": 0,
            "network_calls": 0, "region": args.region}


if __name__ == "__main__":
    raise SystemExit(main())
