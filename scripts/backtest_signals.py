"""Backtest the deterministic signal stack over the training universe.

    python scripts/backtest_signals.py

⚠️  Downloads ~10y daily bars via yfinance (data API only — no LLM calls).
Reuses train_ml_alpha's downloader/universe so the backtest sees exactly the
names the screener/trainer cover. Results → data_store/backtest_results.json
(gitignored) + a printed summary table.
"""
import datetime
import json
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from app.skills import backtest  # noqa: E402
from train_ml_alpha import UNIVERSE, _download  # noqa: E402

OUT = _REPO_ROOT / "data_store" / "backtest_results.json"


def main() -> None:
    t0 = time.time()
    print(f"Downloading {len(UNIVERSE)} tickers x ~10y daily...")
    bars_by_ticker = {}
    for ticker in UNIVERSE:
        bars = _download(ticker)
        if bars:
            bars_by_ticker[ticker] = bars
        else:
            print(f"  {ticker}: no data, skipped")
    print(f"Downloaded {len(bars_by_ticker)} tickers in {time.time() - t0:.0f}s. "
          "Replaying signal stack...")

    results = backtest.run(bars_by_ticker, step=5)
    results["ran_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    results["universe_size"] = len(bars_by_ticker)
    results["step_days"] = 5

    os.makedirs(OUT.parent, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(f"Saved {OUT}\n")
    print(backtest.format_report(results))
    print(f"\nTotal {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
