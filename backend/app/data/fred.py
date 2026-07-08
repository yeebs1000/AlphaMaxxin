"""FRED (Federal Reserve Economic Data) provider — US macro series.

Two access paths:
- With FRED_API_KEY (free): the official JSON API.
- Without a key: fredgraph.csv, which is public and keyless.

Both return the same shape: {"series_id", "observations": [{"date", "value"}]}
(newest last, non-numeric observations dropped).
"""
import csv
import io
import os

from .base import DiskTTLCache, guard_online, http_get_json, http_get_text, TTL_MACRO


class FredProvider:
    name = "fred"

    def __init__(self, cache: DiskTTLCache):
        self._cache = cache

    @property
    def api_key(self) -> str:
        return os.environ.get("FRED_API_KEY", "").strip()

    @property
    def available(self) -> bool:
        return True  # keyless CSV path always exists

    def series(self, series_id: str, limit: int = 400) -> dict | None:
        return self._cache.get_or_fetch("fred", f"{series_id}:{limit}", TTL_MACRO,
                                        lambda: self._fetch(series_id, limit))

    def _fetch(self, series_id: str, limit: int) -> dict | None:
        if self.api_key:
            obs = self._fetch_api(series_id, limit)
        else:
            obs = self._fetch_csv(series_id, limit)
        if not obs:
            return None
        return {"series_id": series_id, "observations": obs}

    def _fetch_api(self, series_id: str, limit: int) -> list[dict] | None:
        guard_online()  # outside the try — the offline tripwire must not be swallowed
        try:
            data = http_get_json(
                "https://api.stlouisfed.org/fred/series/observations"
                f"?series_id={series_id}&api_key={self.api_key}&file_type=json"
                f"&sort_order=desc&limit={limit}")
            obs = []
            for row in data.get("observations", []):
                try:
                    obs.append({"date": row["date"], "value": float(row["value"])})
                except (KeyError, ValueError):
                    continue
            obs.reverse()  # newest last
            return obs or None
        except Exception:
            return None

    def _fetch_csv(self, series_id: str, limit: int) -> list[dict] | None:
        guard_online()
        try:
            text = http_get_text(
                f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
            obs = []
            for row in rows[1:]:  # skip header
                if len(row) < 2:
                    continue
                try:
                    obs.append({"date": row[0], "value": float(row[1])})
                except ValueError:
                    continue  # "." = missing observation
            return obs[-limit:] or None
        except Exception:
            return None
