"""
AlphaMaxxin — Interactive Brokers (IBKR) Position Layer
Live positions from a running TWS or IB Gateway instance via `ib_async`
(the maintained continuation of `ib_insync`). Read-only: no order entry.

Requires TWS or IB Gateway running locally with the API enabled
(Configuration > API > Settings > "Enable ActiveX and Socket Clients") and
"Read-Only API" left checked unless you specifically need write access
(this module never uses it).

Optional layer: if ib_async isn't installed or TWS/Gateway isn't reachable,
get_ibkr_positions() returns None and the caller falls back to whatever
else is configured (moomoo, Tiger, external_holdings.json).
"""
import asyncio
import os
import socket
import threading
import time

try:
    from ib_async import IB, Stock
    _IBKR_AVAILABLE = True
except ImportError:
    _IBKR_AVAILABLE = False

IBKR_HOST = os.environ.get("IBKR_HOST", "127.0.0.1")
# 7497 = TWS paper, 7496 = TWS live, 4002 = IB Gateway paper, 4001 = IB Gateway live.
IBKR_PORT = int(os.environ.get("IBKR_PORT", "7497"))
IBKR_CLIENT_ID = int(os.environ.get("IBKR_CLIENT_ID", "17"))
# ib_async's connectAsync() handshake alone can legitimately take close to
# 8 seconds against IB Gateway (it requests open/completed order state as
# part of connecting, which reliably times out server-side before falling
# through) — using the same 8s figure as both connectAsync's own timeout
# AND the outer thread-join bound left ~0 margin for the positions() call
# and disconnect after connecting, so the outer join routinely gave up a
# moment before the connection actually finished, silently discarding a
# successful fetch. _CONNECT_TIMEOUT bounds the handshake; _REQUEST_TIMEOUT
# (outer) must stay comfortably larger than it.
_CONNECT_TIMEOUT = 10
_REQUEST_TIMEOUT = 20  # max time we wait for connect + positions round trip

IBKR_AVAILABLE = _IBKR_AVAILABLE

_POSITIONS_CACHE_TTL = 60  # seconds
_positions_cache = None  # (timestamp, result)

_CONNECT_COOLDOWN = 30
_last_connect_failure = 0.0


def _gateway_reachable() -> bool:
    global _last_connect_failure
    if _last_connect_failure and (time.monotonic() - _last_connect_failure) < _CONNECT_COOLDOWN:
        return False
    try:
        with socket.create_connection((IBKR_HOST, IBKR_PORT), timeout=0.3):
            return True
    except OSError:
        _last_connect_failure = time.monotonic()
        return False


def get_ibkr_positions() -> list | None:
    """
    Live positions from the connected IBKR account. Returns a list of dicts
    shaped like Portfolio.md rows, or None if ib_async isn't installed,
    TWS/Gateway isn't reachable, or the request fails for any reason.
    """
    global _positions_cache
    if not IBKR_AVAILABLE:
        return None
    if _positions_cache and (time.monotonic() - _positions_cache[0]) < _POSITIONS_CACHE_TTL:
        return _positions_cache[1]
    if not _gateway_reachable():
        return None

    box = {}

    def _fetch():
        async def _run():
            ib = IB()
            try:
                await ib.connectAsync(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID, timeout=_CONNECT_TIMEOUT)
                positions = ib.positions()
                result = []
                for p in positions:
                    if not p.position:
                        continue
                    result.append({
                        "ticker": p.contract.symbol,
                        "company": p.contract.symbol,
                        "quantity": float(p.position),
                        "cost_price": float(p.avgCost or 0),
                        "currency": p.contract.currency or "USD",
                    })
                box["result"] = result
            except Exception:
                box["result"] = None
            finally:
                ib.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(timeout=_REQUEST_TIMEOUT)

    result = box.get("result")
    if result is not None:
        _positions_cache = (time.monotonic(), result)
    return result


def qualify_symbols(specs: list[dict]) -> dict[str, bool] | None:
    """Verification tool, not a live data source: for each
    {"key", "symbol", "exchange", "currency"} spec, resolve it against
    IBKR's real contract database and report whether it's a live, tradable
    listing. Returns {key: resolved_bool} keyed by the caller's own `key`
    (so callers needn't fight IBKR's symbol-format quirks — e.g. share
    classes as "BRK B" not "BRK-B" — to match results back), or None if
    ib_async isn't installed or TWS/Gateway isn't reachable.

    Read-only, no order entry. Meant for spot-checking scraped ticker
    lists (e.g. index_constituents.py's Wikipedia parse) against a real
    contract database — not wired into any hot path, run on demand."""
    if not IBKR_AVAILABLE or not specs:
        return None
    if not _gateway_reachable():
        return None

    box = {}

    def _fetch():
        async def _run():
            ib = IB()
            try:
                await ib.connectAsync(IBKR_HOST, IBKR_PORT,
                                      clientId=IBKR_CLIENT_ID + 1,  # distinct from positions()
                                      timeout=_CONNECT_TIMEOUT)
                contracts = [Stock(s["symbol"], s["exchange"], s["currency"])
                            for s in specs]
                qualified = await ib.qualifyContractsAsync(*contracts, returnAll=True)
                # returnAll=True keeps input order/length, unresolved -> None —
                # UNVERIFIED against a live account, matches ib_async's
                # documented contract but never actually run (house rule: no
                # live API calls during dev). Validate on first real use.
                box["result"] = {spec["key"]: (c is not None and bool(c.conId))
                                 for spec, c in zip(specs, qualified)}
            except Exception:
                box["result"] = None
            finally:
                ib.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(timeout=_REQUEST_TIMEOUT)
    return box.get("result")


# ---------------------------------------------------------------------------
# read-only contract taxonomy — sector research prototype, Phase 1
# ---------------------------------------------------------------------------
# Added for the sector-relative research feature
# (~/infra/SECTOR-ANALYSIS-WORK-BRIEF.md §3.3). It lives in this file rather
# than a new module so it reuses the connection, cooldown and timeout machinery
# above instead of duplicating it — the same reason qualify_symbols() is here.
#
# It reads contract metadata and nothing else: no positions, no account
# summary, no orders, no executions, no market data, no scanner subscription.
# Position/account behaviour above is untouched.
try:
    from ib_async.ib import StartupFetchNONE as _STARTUP_FETCH_NONE
except ImportError:          # older ib_async without the startup-fetch flag
    _STARTUP_FETCH_NONE = None

# Distinct from positions()/account_summary() (+0) and qualify_symbols() (+1).
# Sharing a client id with a live session silently steals its connection.
IBKR_TAXONOMY_CLIENT_ID = IBKR_CLIENT_ID + 2
_TAXONOMY_PAUSE_S = 0.12      # ~8 req/s, far inside IBKR's ceiling
_TAXONOMY_MAX_REQUESTS = 200  # a bounded sample, never an unbounded sweep


def contract_details_connect_kwargs(client_id: int | None = None) -> dict:
    """The exact connect arguments the taxonomy fetch uses.

    Exposed as data so the offline test can assert the safety properties —
    read-only, a distinct client id, and StartupFetchNONE so the handshake
    performs no positions/orders/account/executions fetch — without opening a
    connection. Asserting on a docstring proves nothing; asserting on the
    kwargs actually passed to connectAsync does.
    """
    kwargs = {
        "clientId": IBKR_TAXONOMY_CLIENT_ID if client_id is None else client_id,
        "timeout": _CONNECT_TIMEOUT,
        "readonly": True,
    }
    if _STARTUP_FETCH_NONE is not None:
        kwargs["fetchFields"] = _STARTUP_FETCH_NONE
    return kwargs


def taxonomy_row_from_details(details, key: str | None = None) -> dict:
    """One security-master row from one ib_async ContractDetails.

    Keeps only the fields the feature uses, under the names the security master
    expects. `subcategory` is deliberately NOT read: the brief fixes the
    taxonomy at two levels, and persisting a third level would invite ranking
    on it later.
    """
    contract = getattr(details, "contract", None)

    def field(obj, name):
        value = getattr(obj, name, None)
        return value or None      # IBKR returns "" for absent strings

    return {
        "key": key,
        "con_id": getattr(contract, "conId", None) or None,
        "source_symbol": field(contract, "symbol"),
        "local_symbol": field(contract, "localSymbol"),
        "primary_exchange": field(contract, "primaryExchange"),
        "currency": field(contract, "currency"),
        "long_name": field(details, "longName"),
        "stock_type": field(details, "stockType"),
        "ibkr_industry": field(details, "industry"),   # -> canonical sector
        "ibkr_category": field(details, "category"),   # -> canonical industry
    }


def fetch_contract_taxonomy(specs: list[dict], max_requests: int | None = None,
                            pause_s: float | None = None) -> dict | None:
    """Read-only ContractDetails for each {"key", "symbol", "exchange",
    "currency"} spec. Returns {key: row_or_None}, or None if ib_async is not
    installed or the gateway is unreachable.

    Requests are serialized with a pause between them and bounded by
    max_requests: this shares a gateway with the live TO pipeline, and a burst
    of parallel contract lookups is exactly the kind of thing that starves it.
    A failure on one spec records None for that key and continues, so a partial
    result is still usable by the resumable merge in security_master.

    UNVERIFIED against a live gateway — written and fixture-tested offline
    under the project's no-live-API-calls-during-dev rule, the same status
    qualify_symbols() carries. Validate on first real use.
    """
    if not IBKR_AVAILABLE or not specs:
        return None
    if not _gateway_reachable():
        return None

    limit = _TAXONOMY_MAX_REQUESTS if max_requests is None else max_requests
    pause = _TAXONOMY_PAUSE_S if pause_s is None else pause_s
    bounded = list(specs)[:limit]
    box = {}

    def _fetch():
        async def _run():
            ib = IB()
            results = {}
            try:
                await ib.connectAsync(IBKR_HOST, IBKR_PORT,
                                      **contract_details_connect_kwargs())
                for spec in bounded:
                    key = spec["key"]
                    try:
                        contract = Stock(spec["symbol"], spec["exchange"],
                                         spec["currency"])
                        found = await ib.reqContractDetailsAsync(contract)
                        results[key] = (taxonomy_row_from_details(found[0], key)
                                        if found else None)
                    except Exception:      # noqa: BLE001 — one bad symbol only
                        results[key] = None
                    await asyncio.sleep(pause)
                box["result"] = results
            except Exception:              # noqa: BLE001
                # Keep whatever resolved before the failure: the merge is
                # resumable, so a partial pass is progress, not garbage.
                box["result"] = results or None
            finally:
                ib.disconnect()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    # Bounded overall: connect + one round trip per spec + the pauses.
    budget = _REQUEST_TIMEOUT + len(bounded) * (pause + 1.0)
    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(timeout=budget)
    return box.get("result")
