#!/usr/bin/env python3
"""Prospective ranking snapshot — the input to a forward evaluation.

EXPERIMENTAL RESEARCH MEASUREMENT — not wired to reports, signals, sizing, or
orders.

Each run freezes one day's ranking so that, weeks later, it can be scored
against what actually happened. This is the only honest route to "does the
score predict anything": the box has no point-in-time fundamentals and no
point-in-time sector membership, so a historical backtest would grade today's
labels on today's survivors.

A snapshot records the score AND the price at `as_of`. Recording the price
matters more than it looks: re-deriving it later from a refreshed cache would
silently use a split-adjusted series that no longer matches what was seen on
the day, which is a quiet lookahead bug.

Snapshots are append-only. An existing file for a date is never overwritten
without --force, because a rewritten snapshot is a rewritten experiment.
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.skills import forward_eval as fe                    # noqa: E402

BANNER = ("EXPERIMENTAL RESEARCH MEASUREMENT — not wired to reports, "
          "signals, sizing, or orders")
SNAPSHOT_DIR = REPO_ROOT / "data_store" / "sector_research" / "snapshots"


def peer_pool_id(entry: dict, region: str) -> str:
    """Stable identifier for the pool a name was actually ranked inside.

    Evaluation must compare like with like: an IC computed across every name
    in a region would mostly measure sector drift, not the peer-relative
    judgement the score is making.
    """
    level = entry.get("peer_level_used")
    if level == "industry":
        key = entry.get("industry")
    elif level == "industry_group":
        key = entry.get("industry_group")
    elif level == "sector":
        key = entry.get("sector")
    else:
        key = "none"
    return f"{region}|{level}|{key}"


def price_at(bars: dict, as_of: str):
    """Last close on or before as_of."""
    if not isinstance(bars, dict):
        return None
    dated = sorted(d for d in bars if isinstance(d, str) and d <= as_of)
    return bars[dated[-1]] if dated else None


def build_snapshot(artifacts, bars_by_ticker: dict, *, as_of: str) -> dict:
    entries, skipped = [], {"no_score": 0, "no_price": 0}
    for artifact in artifacts:
        analysis = artifact["analysis"]
        region = analysis["scope"]["region"]
        for row in analysis["candidates"]:
            if row.get("experimental_score") is None:
                skipped["no_score"] += 1
                continue
            price = price_at(bars_by_ticker.get(row["ticker"]), as_of)
            if price is None:
                skipped["no_price"] += 1
                continue
            entries.append({
                "ticker": row["ticker"],
                "region": region,
                "sector": row.get("sector"),
                "industry": row.get("industry"),
                "industry_group": row.get("industry_group"),
                "peer_level_used": row.get("peer_level_used"),
                "peer_pool": peer_pool_id(row, region),
                "peer_count": row.get("peer_count"),
                "experimental_score": row["experimental_score"],
                "family_scores": row.get("family_scores"),
                "price_at_as_of": price,
            })
    entries.sort(key=lambda e: (e["region"], e["peer_pool"], -e["experimental_score"],
                                e["ticker"]))
    pools = {}
    for entry in entries:
        pools[entry["peer_pool"]] = pools.get(entry["peer_pool"], 0) + 1
    return {
        "banner": BANNER,
        "schema_version": "ranking_snapshot-1",
        "as_of": as_of,
        "taken_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "protocol_version": fe.PROTOCOL["protocol_version"],
        "protocol_hash": fe.protocol_hash(),
        "methodology_version": (artifacts[0]["analysis"]["methodology_version"]
                                if artifacts else None),
        "profile_id": (artifacts[0]["analysis"]["profile"]["id"]
                       if artifacts else None),
        "entries": entries,
        "n_entries": len(entries),
        "n_pools": len(pools),
        "pools_at_or_above_minimum": sum(
            1 for n in pools.values() if n >= fe.PROTOCOL["min_names_per_pool"]),
        "skipped": skipped,
        "limitations": [
            "current classifications, NOT point-in-time",
            "no claim of predictive power until the pre-registered minimum of "
            f"{fe.PROTOCOL['min_snapshots_before_reporting']} snapshots exists",
            "prices recorded as seen on as_of; do not re-derive them later",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=BANNER)
    parser.add_argument("--artifacts", nargs="+", required=True,
                        help="sweep artifact JSON files to snapshot")
    parser.add_argument("--bars", required=True,
                        help="JSON {ticker: {date: close}}")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    artifacts = []
    for pattern in args.artifacts:
        for path in sorted(Path().glob(pattern)) or [Path(pattern)]:
            with open(path, "r", encoding="utf-8") as handle:
                artifacts.append(json.load(handle))
    with open(args.bars, "r", encoding="utf-8") as handle:
        bars = json.load(handle)

    snapshot = build_snapshot(artifacts, bars, as_of=args.as_of)
    out = Path(args.out) if args.out else SNAPSHOT_DIR / f"{args.as_of}.json"
    if out.exists() and not args.force:
        print(f"{out} exists — a rewritten snapshot is a rewritten experiment; "
              f"pass --force only if you mean it", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=1, allow_nan=False)
        handle.write("\n")
    os.replace(tmp, out)

    print(BANNER)
    print(f"snapshot      {out}")
    print(f"as_of         {args.as_of}")
    print(f"protocol      {snapshot['protocol_version']} "
          f"{snapshot['protocol_hash'][:12]}")
    print(f"entries       {snapshot['n_entries']} across {snapshot['n_pools']} pools "
          f"({snapshot['pools_at_or_above_minimum']} at or above the minimum)")
    print(f"skipped       {snapshot['skipped']}")
    existing = sorted(SNAPSHOT_DIR.glob("*.json")) if SNAPSHOT_DIR.exists() else []
    need = fe.PROTOCOL["min_snapshots_before_reporting"]
    print(f"snapshots     {len(existing)} of {need} before any result may be read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
