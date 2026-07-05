"""Congressional trading disclosures — real filings instead of the v1
Politician Portfolio Scanner's LLM recall.

Source: the free Senate/House Stock Watcher JSON dumps (public S3 mirrors of
official PTR filings, no key). Updates are irregular; when the feed is
unreachable the Insider Edge lens reports that instead of guessing.
"""
import datetime

from ..data.base import DiskTTLCache, guard_online, http_get_json, TTL_CALENDAR

SENATE_URL = ("https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com"
              "/aggregate/all_transactions.json")
HOUSE_URL = ("https://house-stock-watcher-data.s3-us-west-2.amazonaws.com"
             "/data/all_transactions.json")


class PoliticianTradesProvider:
    """Lives in skills/ because the parsing is the substance, but follows the
    provider pattern (cache + offline guard) for its fetch."""
    name = "politician_trades"
    available = True  # keyless

    def __init__(self, cache: DiskTTLCache):
        self._cache = cache

    def _fetch(self, url: str) -> list | None:
        guard_online()
        try:
            data = http_get_json(url, timeout=30)
            return data if isinstance(data, list) else None
        except Exception:
            return None

    def all_transactions(self) -> dict:
        senate = self._cache.get_or_fetch("politician", "senate", TTL_CALENDAR,
                                          lambda: self._fetch(SENATE_URL))
        house = self._cache.get_or_fetch("politician", "house", TTL_CALENDAR,
                                         lambda: self._fetch(HOUSE_URL))
        return {"senate": senate or [], "house": house or [],
                "feed_ok": bool(senate or house)}


def recent_trades(transactions: dict, tickers: list[str],
                  window_days: int = 90,
                  today: datetime.date | None = None) -> dict:
    """Filter raw dump rows to the given tickers within the window.
    Returns {"trades": [{politician, chamber, ticker, txn_type, amount, date}],
    "feed_ok"}. Handles both dumps' shapes (senator/representative field)."""
    today = today or datetime.date.today()
    cutoff = today - datetime.timedelta(days=window_days)
    wanted = {t.replace(".SI", "").upper() for t in tickers}
    trades = []
    for chamber, rows in (("senate", transactions.get("senate", [])),
                          ("house", transactions.get("house", []))):
        for row in rows:
            ticker = (row.get("ticker") or "").upper().strip()
            if ticker not in wanted:
                continue
            date_s = row.get("transaction_date", "")
            try:
                tx_date = datetime.datetime.strptime(date_s, "%Y-%m-%d").date()
            except ValueError:
                try:
                    tx_date = datetime.datetime.strptime(date_s, "%m/%d/%Y").date()
                except ValueError:
                    continue
            if tx_date < cutoff:
                continue
            trades.append({
                "politician": row.get("senator") or row.get("representative") or "?",
                "chamber": chamber,
                "ticker": ticker,
                "txn_type": (row.get("type") or "").lower(),
                "amount": row.get("amount", ""),
                "date": tx_date.isoformat(),
            })
    trades.sort(key=lambda t: t["date"], reverse=True)
    return {"trades": trades, "feed_ok": transactions.get("feed_ok", False)}
