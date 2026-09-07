#!/usr/bin/env python3
"""Weekly prospective snapshot — one command for the timer to call.

EXPERIMENTAL RESEARCH MEASUREMENT — not wired to reports, signals, sizing, or
orders. This writes a dated ranking snapshot and nothing else. It never places
an order, never reaches a broker, never calls a model.

Steps, in order:
  1. optionally refresh the free-provider caches (--refresh)
  2. sweep every sector in each region from cache            (no network)
  3. export the bar series the sweep actually used           (no network)
  4. write the append-only snapshot                          (no network)

Only step 1 touches the network, and it is the expensive one — see --refresh.
Everything after it is deterministic and reproducible from what is on disk.
"""
import argparse
import datetime
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.skills import forward_eval as fe                    # noqa: E402

CACHE_ROOT = Path("/var/lib/alphamaxx/.cache/alphamaxxin")
STATE_DIR = REPO_ROOT / "data_store" / "backfill_state"
ARTIFACT_DIR = REPO_ROOT / "data_store" / "sector_research"
UNIVERSE_FILE = STATE_DIR / "all_universe.json"
REGIONS = ("US", "HK", "SG")

BANNER = ("EXPERIMENTAL RESEARCH MEASUREMENT — not wired to reports, "
          "signals, sizing, or orders")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def last_trading_date(today: datetime.date) -> str:
    """The last completed session before `today`.

    A weekly job runs before any market opens, so the newest complete bar is
    the previous trading day. Weekends walk back to Friday. This is
    deliberately calendar-only: exchange holidays are handled downstream by
    taking the last bar at or before as_of, so a holiday costs a day of data
    rather than producing a wrong as_of.
    """
    day = today - datetime.timedelta(days=1)
    while day.weekday() >= 5:            # 5 = Sat, 6 = Sun
        day -= datetime.timedelta(days=1)
    return day.isoformat()


def deadline_passed(deadline: str | None) -> bool:
    """True once today's HH:MM is behind us.

    Needed because universe_backfill rolls a past deadline to TOMORROW — right
    for a single overnight run, wrong across two phases: if OHLCV eats the
    budget, fundamentals would see a 24-hours-away deadline and run unbounded.
    """
    if not deadline:
        return False
    hour, minute = (int(part) for part in deadline.split(":"))
    now = datetime.datetime.now()
    return now >= now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def refresh_caches(rate_fundamentals: int, rate_ohlcv: int, deadline: str | None):
    """Re-fetch the free provider data the score depends on.

    Both are needed weekly: bars obviously, but valuation multiples move with
    price too, so a week-old fwd_pe is a week-old score. Each phase is a
    separate resumable process — if one is cut short the snapshot still runs on
    whatever is cached and records how stale it is. OHLCV goes first because
    price is the input the snapshot cannot do without: it is the thing being
    predicted, and a snapshot with no price at as_of is not evaluable at all.
    """
    backfill = REPO_ROOT / "scripts" / "universe_backfill.py"
    for dataset, rate in (("ohlcv", rate_ohlcv), ("fundamentals", rate_fundamentals)):
        if deadline_passed(deadline):
            print(f"\n--- skipping {dataset}: refresh deadline {deadline} "
                  f"already passed ---", flush=True)
            continue
        command = [sys.executable, "-u", str(backfill),
                   "--universe-file", str(UNIVERSE_FILE),
                   "--dataset", dataset,
                   "--cache-root", str(CACHE_ROOT),
                   "--rate", str(rate),
                   "--max-names", "4000",
                   "--refresh-older-than-days", "5"]
        if deadline:
            command += ["--deadline", deadline]
        print(f"\n--- refreshing {dataset} ---", flush=True)
        subprocess.run(command, check=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=BANNER)
    parser.add_argument("--as-of", default=None,
                        help="default: last completed trading session")
    parser.add_argument("--refresh", action="store_true",
                        help="re-fetch provider caches first (the slow part)")
    parser.add_argument("--rate-fundamentals", type=int, default=20)
    parser.add_argument("--rate-ohlcv", type=int, default=30)
    parser.add_argument("--refresh-deadline", default=None,
                        help="local HH:MM hard stop for the refresh phase")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    as_of = args.as_of or last_trading_date(datetime.date.today())
    print(BANNER)
    print(f"as_of {as_of}")

    if args.refresh:
        refresh_caches(args.rate_fundamentals, args.rate_ohlcv,
                       args.refresh_deadline)

    probe = _load("probe", REPO_ROOT / "scripts" / "sector_relative_probe.py")
    snapshotter = _load("snapshotter", REPO_ROOT / "scripts" / "snapshot_ranking.py")

    fundamentals, bars, taxonomy, provenance = probe.load_from_cache(
        CACHE_ROOT, REPO_ROOT / "data_store" / "price_panel.json", as_of=as_of)
    print(f"cache: {provenance['fundamentals_names']} fundamentals, "
          f"{provenance['bars_total_names']} bar series, "
          f"{provenance.get('names_with_f_score', 0)} with F-score, "
          f"median age {provenance['fundamentals_age_days_median']}d")

    artifacts = []
    for region in REGIONS:
        counts = probe.sectors_present(fundamentals, region)
        for sector, count in counts.items():
            if count < probe.sr.MIN_PEERS:
                continue
            artifact = probe.run_probe(
                fundamentals=fundamentals, bars=bars, taxonomy_override=taxonomy,
                region=region, sector=sector, as_of=as_of, provenance=provenance)
            slug = sector.lower().replace(" ", "-").replace("/", "-")
            probe.write_artifact(
                artifact, ARTIFACT_DIR / f"{region.lower()}-{slug}-{as_of}.json",
                force=True)
            artifacts.append(artifact)
    print(f"swept {len(artifacts)} sector artifacts across {len(REGIONS)} regions")

    snapshot = snapshotter.build_snapshot(artifacts, bars, as_of=as_of)
    out = snapshotter.SNAPSHOT_DIR / f"{as_of}.json"
    if out.exists() and not args.force:
        print(f"{out} exists — a rewritten snapshot is a rewritten experiment",
              file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=1, allow_nan=False)
        handle.write("\n")
    tmp.replace(out)

    existing = sorted(snapshotter.SNAPSHOT_DIR.glob("*.json"))
    need = fe.PROTOCOL["min_snapshots_before_reporting"]
    print(f"snapshot   {out}")
    print(f"entries    {snapshot['n_entries']} across {snapshot['n_pools']} pools "
          f"({snapshot['pools_at_or_above_minimum']} at or above the minimum)")
    print(f"protocol   {snapshot['protocol_version']} "
          f"{snapshot['protocol_hash'][:12]}")
    print(f"progress   {len(existing)} of {need} snapshots before any result "
          f"may be read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
