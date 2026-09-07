#!/usr/bin/env python3
"""Universe fundamentals backfill — widen the research universe so industry
peer pools can exist.

Phase 1 measured the problem: 90 US names carried cached fundamentals across 48
industry labels, so no industry reached MIN_PEERS=12 and every candidate fell
back to its sector. The index constituent lists are already cached (S&P 500 +
400 = ~903 US names, HSI 85, STI 30); what is missing is a fundamentals
snapshot per name. This script fills that gap and nothing else.

It writes ONLY to the existing DiskTTLCache namespace `yf_fundamentals`, the
same place YFinanceProvider already writes. It computes nothing, ranks nothing,
and touches no report, signal, order or broker path.

Why this is throttled and interruptible
---------------------------------------
YFinanceProvider has no rate limiter — yahoo.py throttles the OHLCV path at
60/min, but the `.info` path this uses is unbounded. Several hundred
unthrottled calls is how a box earns a Yahoo soft-ban, and the 08:00 SG/HK
digest and the 30-minute scanner both depend on Yahoo working. So:

  * a token-bucket rate limit (default 20/min, deliberately below yahoo.py's 60)
  * a consecutive-failure circuit breaker — a run of failures is the signature
    of a ban, and the correct response is to stop, not to keep pushing
  * a wall-clock deadline, so a run cannot bleed into a scheduled job
  * fully resumable: every success is written to the cache immediately, so an
    interrupted run loses only the name in flight

Usage
-----
    universe_backfill.py --regions US --deadline 02:30 --rate 20
    universe_backfill.py --regions US HK SG --dry-run
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.data.base import DiskTTLCache, RateLimiter          # noqa: E402
from app.data.yfinance_provider import YFinanceProvider      # noqa: E402
from app.data.yahoo import YahooProvider                    # noqa: E402
from app.data import index_constituents as ic                # noqa: E402
from app.data import security_master as sm                   # noqa: E402

# Which cache namespace a dataset fills, and how to fetch one name.
OHLCV_INTERVAL, OHLCV_RANGE = "1d", "2y"

# namespace, fetch(provider, ticker), cache_key(ticker)
DATASETS = {
    "fundamentals": ("yf_fundamentals", lambda p, t: p.fundamentals(t),
                     lambda t: t),
    "statements": ("yf_statements", lambda p, t: p.statements(t),
                   lambda t: t),
    # OHLCV keys are composite, and the range matters: ret_252d needs 253
    # closes, a 1y range returns exactly 252, and the factor would silently
    # never score. 2y also leaves room for a longer window later.
    "ohlcv": ("yahoo_ohlcv",
              lambda p, t: p.ohlcv(t, OHLCV_INTERVAL, OHLCV_RANGE),
              lambda t: f"{t}:{OHLCV_INTERVAL}:{OHLCV_RANGE}"),
}

# Which provider serves each dataset.
OHLCV_DATASETS = {"ohlcv"}

# DiskTTLCache.get_or_fetch() does NOT cache a None result, so a name Yahoo has
# no statements for would be refetched on every resume forever. This ledger
# remembers those names so a resumed run spends its rate budget on names that
# might actually return something. Statement coverage thins fast off the US
# main boards, so this is the common case, not the edge case.
NO_DATA_LEDGER = Path("/opt/alphamaxx/data_store/backfill_state")

UNIVERSE_SOURCES = {
    "US": ("sp500 + sp400", ic.us_universe),
    "HK": ("hang seng", ic.hk_universe),
    "SG": ("straits times", ic.sg_universe),
}


def cache_entry_path(cache: DiskTTLCache, namespace: str, key: str) -> Path:
    """Mirrors DiskTTLCache's own layout: {root}/{namespace}/{sha1(key)}.json.

    Presence is checked directly rather than through cache.get(), because get()
    honours the 24h TTL and would report every entry older than a day as
    absent. For a research backfill an existing snapshot is worth keeping even
    when it is a week old — its age is recorded in the artifact — so refetching
    it would spend the rate budget on names we already have.
    """
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return Path(cache.root) / namespace / f"{digest}.json"


def load_no_data(dataset: str) -> set:
    path = NO_DATA_LEDGER / f"{dataset}_no_data.json"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return set(json.load(handle))
    except (OSError, ValueError):
        return set()


def save_no_data(dataset: str, names: set) -> None:
    NO_DATA_LEDGER.mkdir(parents=True, exist_ok=True)
    path = NO_DATA_LEDGER / f"{dataset}_no_data.json"
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(sorted(names), handle, indent=1)
    os.replace(tmp, path)


def parse_deadline(text: str | None) -> float | None:
    if not text:
        return None
    now = datetime.datetime.now()
    hour, minute = (int(part) for part in text.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return time.monotonic() + (target - now).total_seconds()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--regions", nargs="+", default=["US"],
                        choices=list(UNIVERSE_SOURCES))
    parser.add_argument("--dataset", default="fundamentals",
                        choices=list(DATASETS))
    parser.add_argument("--universe-file", default=None,
                        help="JSON list of tickers, instead of the index source")
    parser.add_argument("--rate", type=int, default=20,
                        help="fetches per minute (default 20; yahoo.py uses 60)")
    parser.add_argument("--max-names", type=int, default=2000)
    parser.add_argument("--deadline", default=None,
                        help="local HH:MM hard stop, e.g. 02:30")
    parser.add_argument("--max-consecutive-failures", type=int, default=15,
                        help="raise for statements: empty results are "
                             "normal off the US main boards")
    parser.add_argument("--refresh-older-than-days", type=float, default=None,
                        help="also refetch existing entries older than this")
    parser.add_argument("--cache-root", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cache = DiskTTLCache(Path(args.cache_root) if args.cache_root else None)
    if args.dataset in OHLCV_DATASETS:
        provider = YahooProvider(cache)
    else:
        provider = YFinanceProvider(cache)
        if not provider.available:
            print("yfinance is not installed in this venv", file=sys.stderr)
            return 2
    namespace, fetch_one, cache_key = DATASETS[args.dataset]
    known_empty = load_no_data(args.dataset)
    print(f"dataset        : {args.dataset} -> {namespace}")
    if known_empty:
        print(f"known no-data  : {len(known_empty)} (skipped)")

    # Universe lists come from the 30-day cache; at 16 days old they are fresh,
    # so this makes no network call of its own.
    todo, present, skipped_region = [], 0, 0
    now = time.time()
    if args.universe_file:
        with open(args.universe_file, "r", encoding="utf-8") as handle:
            explicit = json.load(handle)
        sources = [(None, "explicit list", lambda names=explicit: names)]
    else:
        sources = [(region, *UNIVERSE_SOURCES[region]) for region in args.regions]

    for region, label, fetch in sources:
        names = fetch() or []
        print(f"{region or 'ANY':3s} universe {label:22s} {len(names):5d} names")
        for ticker in names:
            row_region = sm.region_for_ticker(ticker)
            if region is not None and row_region != region:
                skipped_region += 1
                continue
            if region is None and row_region is None:
                skipped_region += 1
                continue
            if ticker in known_empty:
                present += 1
                continue
            path = cache_entry_path(cache, namespace, cache_key(ticker))
            if path.exists():
                if args.refresh_older_than_days is None:
                    present += 1
                    continue
                age_days = (now - path.stat().st_mtime) / 86400
                if age_days <= args.refresh_older_than_days:
                    present += 1
                    continue
            todo.append((row_region, ticker))

    todo = todo[:args.max_names]
    print(f"\nalready cached : {present}")
    print(f"region-mismatch: {skipped_region}")
    print(f"to fetch       : {len(todo)}")
    if not todo:
        print("nothing to do")
        return 0
    estimate = len(todo) / max(args.rate, 1)
    print(f"estimate       : {estimate:.1f} min at {args.rate}/min")
    if args.deadline:
        print(f"hard deadline  : {args.deadline} local")
    if args.dry_run:
        print("\n--dry-run: no fetch performed")
        return 0

    limiter = RateLimiter(args.rate, 60.0)
    deadline = parse_deadline(args.deadline)
    ok = fail = 0
    consecutive = 0
    started = time.monotonic()

    for index, (region, ticker) in enumerate(todo, start=1):
        if deadline and time.monotonic() >= deadline:
            print(f"\nDEADLINE reached — stopping cleanly at {index - 1}/{len(todo)}")
            break
        limiter.acquire()
        try:
            snapshot = fetch_one(provider, ticker)
        except Exception as exc:                       # noqa: BLE001
            snapshot, exc_note = None, f"{type(exc).__name__}: {exc}"
        else:
            exc_note = None
        if snapshot:
            ok += 1
            consecutive = 0
        else:
            # A None here is ambiguous: Yahoo genuinely has nothing, or Yahoo
            # is refusing us. Record it either way so a resume does not pay for
            # it again, and let the consecutive counter catch a real ban — a
            # long unbroken run of empties on an index universe is not normal.
            fail += 1
            consecutive += 1
            known_empty.add(ticker)
            if exc_note:
                print(f"  {ticker}: {exc_note}", file=sys.stderr)
        if consecutive >= args.max_consecutive_failures:
            # The signature of a rate-limit ban. Pushing through it would put
            # the 08:00 digest and the 30-minute scanner at risk for no gain.
            print(f"\nCIRCUIT BREAKER: {consecutive} consecutive failures — "
                  f"stopping at {index}/{len(todo)}. Yahoo is likely refusing "
                  f"this box; re-run later, the work so far is cached.",
                  file=sys.stderr)
            break
        if index % 25 == 0 or index == len(todo):
            elapsed = (time.monotonic() - started) / 60
            print(f"  {index:4d}/{len(todo)}  ok={ok} fail={fail}  "
                  f"{elapsed:.1f} min", flush=True)

    save_no_data(args.dataset, known_empty)
    elapsed = (time.monotonic() - started) / 60
    print(f"\nfetched ok : {ok}")
    print(f"no data    : {fail}")
    print(f"elapsed    : {elapsed:.1f} min")
    total = len(list((Path(cache.root) / namespace).glob("*.json")))
    print(f"cache now  : {total} names in {namespace}")
    print(f"no-data ledger: {len(known_empty)} names "
          f"({NO_DATA_LEDGER / (args.dataset + '_no_data.json')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
