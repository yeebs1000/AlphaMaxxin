"""
AlphaMaxxin — Moomoo Market Data Layer
Live quotes from the moomoo OpenD gateway via the official `moomoo-api`
package. Read-only: no order entry, no account/position access.

Neither OpenQuoteContext(...) nor get_market_snapshot(...) honor a timeout —
when OpenD isn't running, OpenQuoteContext's *synchronous* constructor retries
internally for 8+ seconds per attempt with no apparent upper bound, and an
async-connect context's first get_market_snapshot() call blocks the same way
waiting for the handshake. So every blocking call here runs in a daemon
worker thread and is bounded with thread.join(timeout=...) from the caller's
side; a slow/never-finishing attempt is simply abandoned rather than allowed
to block the GUI or an agent run.

Optional layer: if moomoo-api isn't installed or OpenD isn't reachable,
every function returns None and the caller (runner.fetch_live_price) falls
back to its existing Yahoo Finance path.
"""
import os
import socket
import threading
import time

try:
    from moomoo import (
        OpenQuoteContext, OpenSecTradeContext, RET_OK, TrdMarket, SecurityFirm,
        TrdEnv, SubType, KLType, AuType,
    )
    _MOOMOO_AVAILABLE = True
except ImportError:
    _MOOMOO_AVAILABLE = False

MOOMOO_HOST = os.environ.get("MOOMOO_HOST", "127.0.0.1")
MOOMOO_PORT = int(os.environ.get("MOOMOO_PORT", "11111"))
_REQUEST_TIMEOUT = 5  # max time we personally wait for any one quote call

# Singapore Exchange names traded from Portfolio.md — everything else is routed US.
_SGX_TICKERS = {"A31", "C6L", "D05"}

MOOMOO_AVAILABLE = _MOOMOO_AVAILABLE

_lock = threading.Lock()
_ctx: "OpenQuoteContext | None" = None

# If OpenD was unreachable recently, skip straight to None for this long
# instead of re-running the bounded-but-still-costly wait on every call.
_CONNECT_COOLDOWN = 30  # seconds
_last_connect_failure = 0.0


def _opend_reachable() -> bool:
    """Cheap TCP reachability probe, shared by every function below that
    would otherwise construct its own OpenQuoteContext/OpenSecTradeContext.
    Skips paying the constructor's internal 8+ second retry-on-connect (see
    module docstring) when OpenD isn't running at all — a real risk once
    several holdings each try a fresh lookup (e.g. 18 tickers x industry
    classification in one metrics refresh) while OpenD is down. Cooled down
    via the shared _last_connect_failure timestamp so a burst of calls only
    pays the socket-connect cost once per _CONNECT_COOLDOWN window."""
    global _last_connect_failure
    if _last_connect_failure and (time.monotonic() - _last_connect_failure) < _CONNECT_COOLDOWN:
        return False
    try:
        with socket.create_connection((MOOMOO_HOST, MOOMOO_PORT), timeout=0.3):
            return True
    except OSError:
        _last_connect_failure = time.monotonic()
        return False

# Quote cache for *successful* lookups — refresh periodically across a long
# multi-agent run (32 agents can each ask for the same ticker within minutes).
_QUOTE_CACHE_TTL = 300  # seconds
_quote_cache: dict = {}  # ticker -> (timestamp, result)

# Tickers with a real response but no quote permission — an account/subscription
# fact that won't change mid-session, so skip the network on repeat calls.
_no_entitlement_tickers: set = set()


def _get_or_create_ctx() -> "OpenQuoteContext | None":
    """Construct the shared context once (async-connect mode is documented to
    return instantly — the handshake happens in moomoo's own background thread —
    but in practice the constructor itself can hang if a trade context (e.g.
    from get_moomoo_positions) opened and closed its own OpenD connection
    moments earlier. Bounded by a worker thread so a stuck construction can't
    hold _lock forever and jam every later quote call). Reused across calls —
    never recreated just because a single quote timed out."""
    global _ctx
    with _lock:
        if _ctx is not None:
            return _ctx
        if not _opend_reachable():
            return None
        box = {}

        def _construct():
            try:
                box["ctx"] = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT, is_async_connect=True)
            except Exception:
                pass

        t = threading.Thread(target=_construct, daemon=True)
        t.start()
        t.join(timeout=_REQUEST_TIMEOUT)
        _ctx = box.get("ctx")
        return _ctx


def _make_code(ticker: str) -> str:
    ticker = ticker.upper().replace(".SI", "")
    if ticker in _SGX_TICKERS:
        return f"SG.{ticker}"
    # HK moomoo codes are always numeric (e.g. "01810"); no other market here
    # uses numeric tickers, so this routes correctly without hardcoding names.
    if ticker.isdigit():
        return f"HK.{ticker.zfill(5)}"
    return f"US.{ticker}"


def _is_real_price(p) -> bool:
    """0.0/NaN both mean 'no tick available' for moomoo fields, not a real $0 price."""
    try:
        return p is not None and p == p and float(p) > 0
    except (TypeError, ValueError):
        return False


def _snapshot_bounded(ctx, code: str) -> tuple | None:
    """Runs ctx.get_market_snapshot([code]) on a worker thread and waits at
    most _REQUEST_TIMEOUT seconds. Returns (ret, data) or None on timeout/error.
    A timed-out worker is abandoned (daemon thread) rather than blocking us."""
    box = {}

    def _work():
        try:
            box["result"] = ctx.get_market_snapshot([code])
        except Exception as e:
            box["error"] = e

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=_REQUEST_TIMEOUT)
    if t.is_alive() or "result" not in box:
        return None
    return box["result"]


def get_moomoo_quote(ticker: str) -> dict | None:
    """
    Live quote lookup via the moomoo OpenD gateway. Returns the same shape as
    runner.fetch_live_price(), or None if moomoo-api isn't installed, OpenD
    isn't reachable, or the ticker has no quote permission on this account.
    """
    global _last_connect_failure
    if not MOOMOO_AVAILABLE or not ticker:
        return None
    ticker = ticker.upper().replace(".SI", "")
    if ticker in _no_entitlement_tickers:
        return None
    cached = _quote_cache.get(ticker)
    if cached and (time.monotonic() - cached[0]) < _QUOTE_CACHE_TTL:
        return cached[1]
    if not _opend_reachable():
        return None

    ctx = _get_or_create_ctx()
    if ctx is None:
        _last_connect_failure = time.monotonic()
        return None

    code = _make_code(ticker)
    snapshot = _snapshot_bounded(ctx, code)
    if snapshot is None:
        _last_connect_failure = time.monotonic()
        return None
    ret, data = snapshot
    if ret != RET_OK or data is None or len(data) == 0:
        _no_entitlement_tickers.add(ticker)
        return None

    row = data.iloc[0]
    price = row.get("last_price")
    if not _is_real_price(price):
        _no_entitlement_tickers.add(ticker)
        return None
    prev_close = row.get("prev_close_price")
    prev_close = float(prev_close) if _is_real_price(prev_close) else float(price)
    change_pct = ((price - prev_close) / prev_close) * 100 if prev_close else 0.0
    currency = "SGD" if code.startswith("SG.") else "HKD" if code.startswith("HK.") else "USD"

    result = {
        "price": float(price),
        "name": ticker,
        "ticker": ticker,
        "yahoo_symbol": ticker,
        "currency": currency,
        "previous_close": prev_close,
        "change_pct": change_pct,
    }
    _quote_cache[ticker] = (time.monotonic(), result)
    return result


def _run_bounded(fn, timeout: float = _REQUEST_TIMEOUT):
    """Runs fn() on a worker thread, bounded by timeout. Returns fn()'s result
    or None on timeout/error. A timed-out worker is abandoned (daemon thread)."""
    box = {}

    def _work():
        try:
            box["result"] = fn()
        except Exception as e:
            box["error"] = e

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive() or "result" not in box:
        return None
    return box["result"]


# Positions/dividends use a longer budget than quotes — trade context login and
# account enumeration round-trip OpenD more than a single snapshot call does.
_PORTFOLIO_TIMEOUT = 10
_POSITIONS_CACHE_TTL = 60  # seconds — positions change far less often than quotes
_positions_cache: dict = {}  # trd_env -> (timestamp, result)


def get_moomoo_positions(trd_env: str = "REAL") -> list | None:
    """
    Live positions from the moomoo trading account (across all markets/firms the
    account is authorized for). Returns a list of dicts shaped like Portfolio.md
    rows, or None if moomoo-api isn't installed, OpenD isn't reachable, or no
    trade-enabled account is found. Read-only: never places or modifies orders.
    """
    if not MOOMOO_AVAILABLE:
        return None
    cached = _positions_cache.get(trd_env)
    if cached and (time.monotonic() - cached[0]) < _POSITIONS_CACHE_TTL:
        return cached[1]
    if not _opend_reachable():
        return None

    def _fetch():
        env = TrdEnv.REAL if trd_env.upper() == "REAL" else TrdEnv.SIMULATE
        ctx = OpenSecTradeContext(
            host=MOOMOO_HOST, port=MOOMOO_PORT,
            filter_trdmarket=TrdMarket.NONE, security_firm=SecurityFirm.NONE,
        )
        try:
            ret, accs = ctx.get_acc_list()
            if ret != RET_OK or accs is None or len(accs) == 0:
                return None
            # Prefer a non-master account matching the requested environment.
            candidates = accs[accs["trd_env"] == env] if hasattr(accs, "__getitem__") else accs
            if hasattr(candidates, "__len__") and len(candidates) == 0:
                candidates = accs
            row = candidates.iloc[0] if hasattr(candidates, "iloc") else candidates[0]
            acc_id = int(row["acc_id"])

            ret, pos_data = ctx.position_list_query(trd_env=env, acc_id=acc_id, refresh_cache=True)
            if ret != RET_OK or pos_data is None:
                return None

            positions = []
            for i in range(len(pos_data)):
                p = pos_data.iloc[i]
                positions.append({
                    "code": str(p.get("code", "")),
                    "name": str(p.get("stock_name", "")),
                    "qty": float(p.get("qty", 0) or 0),
                    "average_cost": float(p.get("average_cost", 0) or 0),
                    "market_val": float(p.get("market_val", 0) or 0),
                    "unrealized_pl": float(p.get("unrealized_pl", 0) or 0),
                    "pl_ratio_avg_cost": float(p.get("pl_ratio_avg_cost", 0) or 0),
                })
            return positions
        finally:
            ctx.close()

    result = _run_bounded(_fetch, timeout=_PORTFOLIO_TIMEOUT)
    if result is not None:
        _positions_cache[trd_env] = (time.monotonic(), result)
    return result


_DIVIDEND_CACHE_TTL = 3600  # seconds — dividend history changes rarely
_dividend_cache: dict = {}  # code -> (timestamp, result)


def get_moomoo_dividends(ticker: str) -> list | None:
    """
    Dividend history for a ticker via the moomoo quote gateway. Returns a list
    of dicts (pub_date/record_date/ex_date/dividend_payable_date/statement), or
    None if moomoo-api isn't installed, OpenD isn't reachable, or no dividend
    data is available.
    """
    if not MOOMOO_AVAILABLE or not ticker:
        return None
    code = _make_code(ticker)
    cached = _dividend_cache.get(code)
    if cached and (time.monotonic() - cached[0]) < _DIVIDEND_CACHE_TTL:
        return cached[1]
    if not _opend_reachable():
        return None

    def _fetch():
        # Uses its own short-lived context rather than the shared persistent
        # quote ctx — interleaving this with trade-context churn (positions
        # opening/closing its own connection) deadlocked the shared async ctx.
        ctx = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)
        try:
            ret, data = ctx.get_corporate_actions_dividends(code)
            if ret != RET_OK or not isinstance(data, dict):
                return None
            return data.get("dividend_list") or None
        finally:
            ctx.close()

    result = _run_bounded(_fetch, timeout=_PORTFOLIO_TIMEOUT)
    if result is not None:
        _dividend_cache[code] = (time.monotonic(), result)
    return result


# Book moves every tick — cache is just to dedupe rapid re-renders (e.g. a GUI
# panel refreshing every second), not a substitute for re-fetching.
_ORDERBOOK_CACHE_TTL = 1.5  # seconds
_orderbook_cache: dict = {}  # code -> (timestamp, result)

# ORDER_BOOK subscriptions persist on the shared ctx's connection for its
# lifetime — OpenD enforces a subscription quota ("Sub" in the OpenD GUI), so
# we subscribe each code at most once rather than on every call.
_orderbook_subscribed: set = set()


def get_moomoo_orderbook(ticker: str, depth: int = 10) -> dict | None:
    """
    Live order book (market depth) for a ticker via the moomoo OpenD gateway.
    Subscribes the shared quote context to ORDER_BOOK push for this code on
    first use. Returns {"code", "bids": [{"price","volume"}...], "asks": [...]}
    (best price first in each list), or None if unavailable/unentitled.
    """
    if not MOOMOO_AVAILABLE or not ticker:
        return None
    code = _make_code(ticker)
    cached = _orderbook_cache.get(code)
    if cached and (time.monotonic() - cached[0]) < _ORDERBOOK_CACHE_TTL:
        return cached[1]

    ctx = _get_or_create_ctx()
    if ctx is None:
        return None

    def _fetch():
        if code not in _orderbook_subscribed:
            ret, _ = ctx.subscribe([code], [SubType.ORDER_BOOK])
            if ret != RET_OK:
                return None
            _orderbook_subscribed.add(code)
        ret, data = ctx.get_order_book(code, num=depth)
        if ret != RET_OK or not isinstance(data, dict):
            return None
        return {
            "code": code,
            "bids": [{"price": float(p), "volume": float(v)} for p, v, *_ in data.get("Bid", [])],
            "asks": [{"price": float(p), "volume": float(v)} for p, v, *_ in data.get("Ask", [])],
        }

    result = _run_bounded(_fetch, timeout=_REQUEST_TIMEOUT)
    if result is not None:
        _orderbook_cache[code] = (time.monotonic(), result)
    return result


_INDUSTRY_CACHE_TTL = 86400  # seconds — industry classification essentially never changes
_industry_cache: dict = {}  # code -> (timestamp, result)


def get_moomoo_industry(ticker: str) -> str | None:
    """
    Industry classification for a ticker (e.g. "Software - Infrastructure"),
    sourced from moomoo's plate/sector membership data (get_owner_plate's
    INDUSTRY-type row) — get_company_profile has no sector/industry field at
    all, so this is the actual source for that classification. Returns None
    if unavailable.
    """
    if not MOOMOO_AVAILABLE or not ticker:
        return None
    code = _make_code(ticker)
    cached = _industry_cache.get(code)
    if cached and (time.monotonic() - cached[0]) < _INDUSTRY_CACHE_TTL:
        return cached[1]
    if not _opend_reachable():
        return None

    def _fetch():
        ctx = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)
        try:
            ret, data = ctx.get_owner_plate([code])
            if ret != RET_OK or data is None or len(data) == 0:
                return None
            industry_rows = data[data["plate_type"] == "INDUSTRY"]
            if len(industry_rows) == 0:
                return None
            return str(industry_rows.iloc[0]["plate_name"])
        finally:
            ctx.close()

    result = _run_bounded(_fetch, timeout=_PORTFOLIO_TIMEOUT)
    if result is not None:
        _industry_cache[code] = (time.monotonic(), result)
    return result


_KLINE_CACHE_TTL = 3600  # seconds — daily/weekly bars don't need refreshing more than hourly
_kline_cache: dict = {}  # (code, ktype) -> (timestamp, result)


def get_moomoo_kline(ticker: str, ktype: str = "K_DAY", max_count: int = 260) -> list | None:
    """
    Historical OHLCV bars via moomoo's history K-line API, for real (not
    LLM-estimated) technical indicator calculation. Each row is one
    regular-session bar: {"time","open","high","low","close","volume",
    "turnover"}. `volume` is share count; `turnover` is price x volume (a
    value metric) — moomoo reports both as separate columns, never summed,
    and this never touches pre/after-hours fields (those only exist on
    intraday snapshots, not K-line bars). Returns None if unavailable.
    """
    if not MOOMOO_AVAILABLE or not ticker:
        return None
    code = _make_code(ticker)
    cache_key = (code, ktype)
    cached = _kline_cache.get(cache_key)
    if cached and (time.monotonic() - cached[0]) < _KLINE_CACHE_TTL:
        return cached[1]
    if not _opend_reachable():
        return None

    def _fetch():
        ctx = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)
        try:
            kl_type = getattr(KLType, ktype, KLType.K_DAY)
            ret, data, _page_key = ctx.request_history_kline(
                code, ktype=kl_type, autype=AuType.QFQ, max_count=max_count,
            )
            if ret != RET_OK or data is None or len(data) == 0:
                return None
            rows = []
            for i in range(len(data)):
                r = data.iloc[i]
                rows.append({
                    "time": str(r.get("time_key", "")),
                    "open": float(r.get("open", 0) or 0),
                    "high": float(r.get("high", 0) or 0),
                    "low": float(r.get("low", 0) or 0),
                    "close": float(r.get("close", 0) or 0),
                    "volume": float(r.get("volume", 0) or 0),
                    "turnover": float(r.get("turnover", 0) or 0),
                })
            return rows
        finally:
            ctx.close()

    result = _run_bounded(_fetch, timeout=_PORTFOLIO_TIMEOUT)
    if result is not None:
        _kline_cache[cache_key] = (time.monotonic(), result)
    return result


_ANALYST_CACHE_TTL = 21600  # seconds (6h) — consensus updates at most daily
_analyst_cache: dict = {}  # code -> (timestamp, result)


def get_moomoo_analyst_consensus(ticker: str) -> dict | None:
    """
    Analyst consensus for a ticker: target price range/average, overall
    rating, buy/hold/sell split, and analyst count. Returns None if
    unavailable (e.g. no analyst coverage, or moomoo/OpenD unreachable).
    """
    if not MOOMOO_AVAILABLE or not ticker:
        return None
    code = _make_code(ticker)
    cached = _analyst_cache.get(code)
    if cached and (time.monotonic() - cached[0]) < _ANALYST_CACHE_TTL:
        return cached[1]
    if not _opend_reachable():
        return None

    def _fetch():
        ctx = OpenQuoteContext(host=MOOMOO_HOST, port=MOOMOO_PORT)
        try:
            ret, data = ctx.get_research_analyst_consensus(code)
            if ret != RET_OK or not isinstance(data, dict) or not data:
                return None
            return {
                "target_high": data.get("highest"),
                "target_avg": data.get("average"),
                "target_low": data.get("lowest"),
                "rating": data.get("rating"),
                "analyst_count": data.get("total"),
                "buy_pct": data.get("buy"),
                "hold_pct": data.get("hold"),
                "sell_pct": data.get("sell"),
                "updated": data.get("update_time_str"),
            }
        finally:
            ctx.close()

    result = _run_bounded(_fetch, timeout=_PORTFOLIO_TIMEOUT)
    if result is not None:
        _analyst_cache[code] = (time.monotonic(), result)
    return result
