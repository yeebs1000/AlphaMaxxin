"""Common close-date intervals for local-currency portfolio return inputs."""
import datetime
import math

import numpy as np


def _dated_closes(bars):
    stamps = (bars or {}).get("timestamps") or []
    closes = (bars or {}).get("closes") or []
    if not stamps or len(stamps) != len(closes):
        return {}, "missing or mismatched timestamps"
    out = {}
    for stamp, close in zip(stamps, closes):
        try:
            close = float(close)
            if not math.isfinite(close) or close <= 0:
                continue
            if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
                when = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc)
            elif isinstance(stamp, datetime.datetime):
                when = stamp
            elif isinstance(stamp, datetime.date):
                when = datetime.datetime.combine(stamp, datetime.time())
            else:
                when = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if when.tzinfo is not None:
                when = when.astimezone(datetime.timezone.utc)
            out[when.date()] = close  # last valid observation wins on duplicate dates
        except (TypeError, ValueError, OverflowError, OSError):
            continue
    return out, None if len(out) >= 2 else "fewer than two valid dated closes"


def align_daily_returns(daily_by_ticker: dict, benchmark_daily: dict | None = None) -> dict:
    """Intersect close dates BEFORE calculating returns, including the benchmark.

    `dates` identifies return end dates. A holiday can make an interval span
    multiple days; every asset and benchmark still uses the same endpoints.
    Historical FX is absent, so these are explicitly local-currency returns.
    """
    series, excluded = {}, {}
    for ticker, bars in daily_by_ticker.items():
        dated, error = _dated_closes(bars)
        if error:
            excluded[ticker] = error
        else:
            series[ticker] = dated
    benchmark, error = _dated_closes(benchmark_daily)
    if benchmark_daily is not None and error:
        excluded["benchmark"] = error
    valid = list(series.values()) + ([benchmark] if not error else [])
    common = sorted(set.intersection(*(set(s) for s in valid))) if valid else []
    result = {"returns": {}, "benchmark_returns": None, "dates": [],
              "interval_business_days": [],
              "excluded": excluded,
              "basis": "local_currency_close_returns; historical_fx_not_included"}
    if len(common) < 2:
        excluded.update({t: "fewer than two common close dates" for t in series})
        return result
    def returns(s):
        return [s[end] / s[start] - 1.0 for start, end in zip(common, common[1:])]
    result["returns"] = {t: returns(s) for t, s in series.items()}
    result["dates"] = [d.isoformat() for d in common[1:]]
    result["interval_business_days"] = [int(np.busday_count(start, end))
                                        for start, end in zip(common, common[1:])]
    if not error:
        result["benchmark_returns"] = returns(benchmark)
    return result
