"""Official exchange security lists for the HK and SG research universes.

`index_constituents.py` scrapes index membership — Hang Seng (85 names) and STI
(30). That is a benchmark, not a market: the Phase 1 census measured 0 HK and 0
SG industries reaching the 12-name peer minimum, and only one sector each. This
module goes to the exchanges themselves, which the brief (§3.4) names as the
expansion path.

Sources, both official and both free:

  HKEX  ListOfSecurities.xlsx — the exchange's own daily securities list,
        ~17.8k rows, with an explicit Category/Sub-Category taxonomy.
  SGX   api.sgx.com securities list — typed rows (stocks, reits, etfs,
        businesstrusts, warrants, ...).

A research universe is not "every symbol the exchange lists". Both feeds are
filtered deterministically, by fields the exchange itself publishes — never by
guesswork and never by a model:

  * HK: Category "Equity", Sub-Category "Main Board" (drops GEM, investment
    companies, trading-only lines and depositary receipts), and **Shortsell
    Eligible = Y**. That last one is the liquidity screen: HKEX maintains the
    Designated Securities list on market-cap and turnover criteria, so it is an
    exchange-published liquidity judgement rather than one invented here. It
    cuts 2,470 Main Board equities to ~805.
  * SG: type "stocks". REITs and business trusts are economically central in
    Singapore but need their own factor profile, so they sit behind an explicit
    flag rather than being silently included or silently dropped.

Parsing is separated from fetching so the whole taxonomy is fixture-testable
offline — the brief requires the broader adapter be implemented "only if its
format is stable and fixture-tested".
"""
import io
import json
import sys
import urllib.request

from .base import DiskTTLCache, TTL_UNIVERSE, guard_online

HKEX_URL = ("https://www.hkex.com.hk/eng/services/trading/securities/"
            "securitieslists/ListOfSecurities.xlsx")
SGX_URL = ("https://api.sgx.com/securities/v1.1?excludetypes=bonds"
           "&params=nc%2Cn%2Csip")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AlphaMaxxin/1.0)"}

_cache = DiskTTLCache()

# HK inclusion rules, as published by HKEX.
HK_CATEGORY_EQUITY = "Equity"
HK_CATEGORY_REIT = "Real Estate Investment Trusts"
HK_MAIN_BOARD = "Main Board"

# SGX row types. Anything not named here is excluded by default: an unknown
# type is not an equity until someone has looked at it.
SG_TYPE_STOCK = "stocks"
SG_TYPE_REIT = "reits"
SG_TYPE_TRUST = "businesstrusts"
SG_EXCLUDED_TYPES = ("etfs", "adrs", "companywarrants", "structuredwarrants",
                     "dlcertificates", "listedcertificates", "liprod", "others")


def _http_get_bytes(url: str, timeout: float = 60.0) -> bytes:
    guard_online()
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _http_get_json(url: str, timeout: float = 45.0):
    guard_online()
    request = urllib.request.Request(
        url, headers={**_HEADERS, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# HKEX
# ---------------------------------------------------------------------------
def hk_ticker(stock_code) -> str | None:
    """HKEX stock code -> AlphaMaxxin ticker. 5-digit codes are structured
    products, not the ordinary shares this universe wants."""
    try:
        code = int(str(stock_code).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    if not 1 <= code <= 9999:
        return None
    return f"{code:04d}.HK"


def parse_hkex_records(records, include_reits: bool = False) -> list:
    """Filter HKEX rows to a research universe. Pure — takes plain dicts."""
    allowed = {HK_CATEGORY_EQUITY}
    if include_reits:
        allowed.add(HK_CATEGORY_REIT)
    out, seen = [], set()
    for row in records or []:
        category = str(row.get("Category") or "").strip()
        if category not in allowed:
            continue
        sub = str(row.get("Sub-Category") or "").strip()
        is_reit = category == HK_CATEGORY_REIT
        # REITs carry their own sub-category text, so the Main Board rule is
        # applied to ordinary equities only.
        if not is_reit and HK_MAIN_BOARD not in sub:
            continue
        shortsell = str(row.get("Shortsell Eligible") or "").strip().upper()
        if not is_reit and shortsell not in ("Y", "YES"):
            continue          # HKEX's own liquidity designation
        ticker = hk_ticker(row.get("Stock Code"))
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        out.append({
            "ticker": ticker,
            "region": "HK",
            "source_symbol": str(row.get("Stock Code")).strip(),
            "long_name": str(row.get("Name of Securities") or "").strip() or None,
            "stock_type": "reit" if is_reit else "common",
            "board": "Main Board",
            "isin": str(row.get("ISIN") or "").strip() or None,
            "universe_source": "hkex_list_of_securities",
        })
    return sorted(out, key=lambda r: r["ticker"])


def _hkex_records_from_xlsx(blob: bytes) -> list:
    """Locate the header row rather than hard-coding it — HKEX prefixes the
    sheet with a title and an 'Updated as at' line, and a layout tweak that
    shifts them must not silently produce an empty universe."""
    import pandas as pd

    raw = pd.read_excel(io.BytesIO(blob), sheet_name=0, header=None, nrows=12)
    header_row = None
    for index in range(len(raw)):
        values = [str(v).strip() for v in raw.iloc[index].tolist()]
        if "Stock Code" in values and "Category" in values:
            header_row = index
            break
    if header_row is None:
        print("[exchange_universes] HKEX header row not found — layout changed",
              file=sys.stderr)
        return []
    frame = pd.read_excel(io.BytesIO(blob), sheet_name=0, header=header_row)
    return frame.to_dict("records")


def hkex_universe(include_reits: bool = False, cache=None) -> list | None:
    """The HK research universe, disk-cached 30 days. None on any failure —
    callers must fall back to the index list rather than proceed with a
    silently shrunken universe."""
    store = cache or _cache
    key = f"hkex_v1_reits={int(include_reits)}"

    def fetch():
        try:
            records = _hkex_records_from_xlsx(_http_get_bytes(HKEX_URL))
        except Exception as exc:                      # noqa: BLE001
            print(f"[exchange_universes] HKEX: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return None
        rows = parse_hkex_records(records, include_reits=include_reits)
        return rows or None

    return store.get_or_fetch("exchange_universes", key, TTL_UNIVERSE, fetch)


# ---------------------------------------------------------------------------
# SGX
# ---------------------------------------------------------------------------
def sg_ticker(code) -> str | None:
    text = str(code or "").strip().upper()
    return f"{text}.SI" if text.isalnum() and 1 <= len(text) <= 5 else None


def parse_sgx_payload(payload, include_reits: bool = False) -> list:
    """Filter the SGX securities response to a research universe. Pure."""
    allowed = {SG_TYPE_STOCK}
    if include_reits:
        allowed.update({SG_TYPE_REIT, SG_TYPE_TRUST})
    prices = ((payload or {}).get("data") or {}).get("prices") or []
    out, seen = [], set()
    for row in prices:
        row_type = str(row.get("type") or "").strip().lower()
        if row_type not in allowed:
            continue
        ticker = sg_ticker(row.get("nc"))
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        out.append({
            "ticker": ticker,
            "region": "SG",
            "source_symbol": str(row.get("nc")).strip(),
            "long_name": str(row.get("n") or "").strip() or None,
            "stock_type": "common" if row_type == SG_TYPE_STOCK else "reit",
            "board": "Mainboard",
            "universe_source": "sgx_securities_v1_1",
        })
    return sorted(out, key=lambda r: r["ticker"])


def sgx_universe(include_reits: bool = False, cache=None) -> list | None:
    store = cache or _cache
    key = f"sgx_v1_reits={int(include_reits)}"

    def fetch():
        try:
            payload = _http_get_json(SGX_URL)
        except Exception as exc:                      # noqa: BLE001
            print(f"[exchange_universes] SGX: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return None
        rows = parse_sgx_payload(payload, include_reits=include_reits)
        return rows or None

    return store.get_or_fetch("exchange_universes", key, TTL_UNIVERSE, fetch)


def tickers(rows) -> list:
    return [row["ticker"] for row in rows or []]
