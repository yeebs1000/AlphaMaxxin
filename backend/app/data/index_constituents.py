"""Real index constituents — the screener's actual "market" instead of a
hand-curated watchlist. Keyless: scrapes the constituents table off each
index's Wikipedia page (a proper index-provider API is the honest upgrade,
but every real one needs a paid key). Disk-cached 30 days — these lists
move a handful of times a year, not daily.

Every fetch degrades to None on any failure (missing pandas/lxml, page
structure change, network hiccup) — screener.py falls back to its curated
static lists, so a Wikipedia edit can only shrink the universe back to
where it already was, never break a scan.
# ponytail: table-column-finder is generic (matches on header text) rather
# than a hardcoded table index, but the exact Wikipedia table structure is
# UNVERIFIED — this project's hard rule is no live fetches during dev.
# Validate with one real online run before trusting the output, same as
# akshare_provider.py's fetch parsing.
"""
from functools import lru_cache

from .base import DiskTTLCache, TTL_UNIVERSE, guard_online, http_get_text

_cache = DiskTTLCache()

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AlphaMaxxin/1.0)"}


@lru_cache(maxsize=1)
def _pd():
    """pandas, or None if it (or lxml, its default HTML parser) isn't
    available — both are already pulled transitively by akshare/moomoo-api,
    but neither is a hard AlphaMaxxin dependency."""
    try:
        import pandas
        import lxml  # noqa: F401 — pandas.read_html's default parser
        return pandas
    except ImportError:
        return None


def _find_ticker_column(tables: list, *header_hints: str) -> list | None:
    """First table with a column whose header matches one of the hints
    (case-insensitive substring) → that column's values as strings."""
    hints = [h.lower() for h in header_hints]
    for table in tables:
        for col in table.columns:
            col_str = str(col).lower()
            if any(h in col_str for h in hints):
                return [str(v).strip() for v in table[col].tolist()]
    return None


def _wiki_tables(page: str) -> list | None:
    pd = _pd()
    if pd is None:
        return None
    guard_online()  # outside the try — the tripwire must not be swallowed
    try:
        html = http_get_text(f"https://en.wikipedia.org/wiki/{page}",
                             headers=_HEADERS, timeout=15)
        return pd.read_html(html)
    except Exception:
        return None


def _cached(key: str, fetch) -> list | None:
    return _cache.get_or_fetch("index_constituents", key, TTL_UNIVERSE, fetch)


def sp500_tickers() -> list | None:
    def fetch():
        tables = _wiki_tables("List_of_S%26P_500_companies")
        col = _find_ticker_column(tables or [], "symbol", "ticker") if tables else None
        return [t.replace(".", "-") for t in col] if col else None
    return _cached("sp500", fetch)


def sp400_tickers() -> list | None:
    def fetch():
        tables = _wiki_tables("List_of_S%26P_400_companies")
        col = _find_ticker_column(tables or [], "symbol", "ticker") if tables else None
        return [t.replace(".", "-") for t in col] if col else None
    return _cached("sp400", fetch)


def hang_seng_tickers() -> list | None:
    def fetch():
        tables = _wiki_tables("Hang_Seng_Index")
        col = _find_ticker_column(tables or [], "stock code", "code", "ticker") \
            if tables else None
        return [f"{c.zfill(4)}.HK" for c in col if c.isdigit()] if col else None
    return _cached("hsi", fetch)


def hstech_tickers() -> list | None:
    def fetch():
        tables = _wiki_tables("Hang_Seng_TECH_Index")
        col = _find_ticker_column(tables or [], "stock code", "code", "ticker") \
            if tables else None
        return [f"{c.zfill(4)}.HK" for c in col if c.isdigit()] if col else None
    return _cached("hstech", fetch)


def sti_tickers() -> list | None:
    def fetch():
        tables = _wiki_tables("Straits_Times_Index")
        col = _find_ticker_column(tables or [], "sgx code", "code", "ticker",
                                  "symbol") if tables else None
        return [f"{c}.SI" for c in col] if col else None
    return _cached("sti", fetch)


def _merge(*lists: list | None) -> list | None:
    seen, out = set(), []
    for lst in lists:
        for t in (lst or []):
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out or None


def us_universe() -> list | None:
    """S&P 500 + S&P MidCap 400 — same non-mega-cap spirit as the curated
    fallback, just the real thing instead of ~30 hand-picks."""
    return _merge(sp500_tickers(), sp400_tickers())


def hk_universe() -> list | None:
    return _merge(hang_seng_tickers(), hstech_tickers())


def sg_universe() -> list | None:
    return sti_tickers()
