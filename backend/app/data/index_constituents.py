"""Real index constituents — the screener's actual "market" instead of a
hand-curated watchlist. Keyless: scrapes the constituents table off each
index's Wikipedia page (a proper index-provider API is the honest upgrade,
but every real one needs a paid key). Disk-cached 30 days — these lists
move a handful of times a year, not daily.

Every fetch degrades to None on failure (missing pandas/lxml, page moved,
structure change) — screener.py falls back to its curated static lists, so a
Wikipedia edit can only shrink the universe back to where it already was,
never break a scan. Failures are LOGGED (stderr), not silent: a swallowed
None here quietly ran the whole scan on the tiny curated fallback for days
before it was caught.

Validated live 2026-07-24: S&P 500 (503) + S&P 400 (400), Hang Seng (85),
STI (30). The column picker takes the header-matching column that yields the
MOST valid tickers, so a stray "code" column in an early table can't win over
the real constituents table.
"""
import io
import re
import sys
from functools import lru_cache

from .base import DiskTTLCache, TTL_UNIVERSE, guard_online, http_get_text

_cache = DiskTTLCache()
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AlphaMaxxin/1.0)"}


@lru_cache(maxsize=1)
def _pd():
    """pandas, or None if it (or lxml, its HTML parser) isn't available —
    both come transitively via akshare/moomoo-api, neither is a hard dep."""
    try:
        import pandas
        import lxml  # noqa: F401 — pandas.read_html's default parser
        return pandas
    except ImportError:
        return None


def _wiki_tables(page: str):
    pd = _pd()
    if pd is None:
        return None
    guard_online()  # outside the try — the offline tripwire must not be swallowed
    try:
        html = http_get_text(f"https://en.wikipedia.org/wiki/{page}",
                             headers=_HEADERS, timeout=15)
        # pandas 3.x: read_html treats a bare string as a FILE PATH and raises
        # FileNotFoundError on the HTML itself — wrap in StringIO. (This exact
        # miss silently broke every universe fetch until 2026-07-24.)
        return pd.read_html(io.StringIO(html))
    except Exception as e:  # noqa: BLE001
        print(f"[index_constituents] {page}: {type(e).__name__}: {e}",
              file=sys.stderr)
        return None


_MIN_VALID = 10  # a real index has more constituents than a stray code column


def _extract(tables, hints, normalizer):
    """First hint-matching column (table then column order) that yields a real
    constituent count. First-match, not longest: 'longest' grabs the S&P
    'recent changes' tables (historical adds AND drops) and inflates the list
    with delisted names; the >= _MIN_VALID floor skips stray early-table
    columns that normalize to near-nothing (the old first-match's HK failure)."""
    hint_l = [h.lower() for h in hints]
    for table in (tables or []):
        for col in table.columns:
            if any(h in str(col).lower() for h in hint_l):
                vals = [normalizer(str(v).strip()) for v in table[col].tolist()]
                vals = [v for v in vals if v]
                if len(vals) >= _MIN_VALID:
                    return vals
    return None


# --- per-region cell normalizers (validated against live 2026-07-24 pages) --
def _us_code(cell: str):
    t = cell.upper().replace(".", "-")          # BRK.B -> BRK-B
    return t if re.fullmatch(r"[A-Z][A-Z\-]{0,5}", t) else None


def _hk_code(cell: str):
    digits = re.sub(r"\D", "", cell)            # "SEHK:\xa0388" -> "388"
    return f"{digits.zfill(4)}.HK" if 1 <= len(digits) <= 5 else None


def _sg_code(cell: str):
    code = cell.split(":")[-1].strip().upper()  # "SGX: A17U" -> "A17U"
    return f"{code}.SI" if re.fullmatch(r"[A-Z0-9]{1,5}", code) else None


def _cached(key: str, fetch):
    return _cache.get_or_fetch("index_constituents", key, TTL_UNIVERSE, fetch)


def sp500_tickers():
    return _cached("sp500", lambda: _extract(
        _wiki_tables("List_of_S%26P_500_companies"), ("symbol", "ticker"), _us_code))


def sp400_tickers():
    return _cached("sp400", lambda: _extract(
        _wiki_tables("List_of_S%26P_400_companies"), ("symbol", "ticker"), _us_code))


def hang_seng_tickers():
    return _cached("hsi", lambda: _extract(
        _wiki_tables("Hang_Seng_Index"), ("ticker", "stock code", "code"), _hk_code))


def sti_tickers():
    return _cached("sti", lambda: _extract(
        _wiki_tables("Straits_Times_Index"),
        ("stock symbol", "sgx code", "symbol", "code"), _sg_code))


def _merge(*lists):
    seen, out = set(), []
    for lst in lists:
        for t in (lst or []):
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out or None


def us_universe():
    """S&P 500 + S&P MidCap 400 — the real ~900-name mid/large-cap market."""
    return _merge(sp500_tickers(), sp400_tickers())


def hk_universe():
    """Hang Seng Index constituents (~85, already includes the big tech names
    since HSI broadened). No separate HSTECH page exists on Wikipedia."""
    return hang_seng_tickers()


def sg_universe():
    return sti_tickers()


# IBKR contract-spec conversion per region (exchange, currency, and how to
# turn our ticker format back into IBKR's local-symbol convention).
_IBKR_REGION = {
    "US": ("SMART", "USD", lambda t: t.replace("-", " ")),          # BRK-B -> BRK B
    "HK": ("SEHK", "HKD", lambda t: t.split(".")[0].lstrip("0") or "0"),  # 0700.HK -> 700
    "SG": ("SGX", "SGD", lambda t: t.split(".")[0]),                # D05.SI -> D05
}


def audit_against_ibkr(tickers: list, region: str):
    """Verification tool: resolve each ticker against IBKR's real contract
    database. {"resolved": [...], "unresolved": [...]} or None if IBKR isn't
    installed/connected. Manual, on-demand — not part of any scan."""
    from ..brokers.ibkr_client import qualify_symbols
    region_info = _IBKR_REGION.get(region)
    if not region_info or not tickers:
        return None
    exchange, currency, to_local = region_info
    specs = [{"key": t, "symbol": to_local(t), "exchange": exchange,
             "currency": currency} for t in tickers]
    results = qualify_symbols(specs)
    if results is None:
        return None
    return {"resolved": [t for t in tickers if results.get(t)],
            "unresolved": [t for t in tickers if not results.get(t)]}
