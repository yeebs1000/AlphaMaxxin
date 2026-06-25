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
    from ib_async import IB
    _IBKR_AVAILABLE = True
except ImportError:
    _IBKR_AVAILABLE = False

IBKR_HOST = os.environ.get("IBKR_HOST", "127.0.0.1")
# 7497 = TWS paper, 7496 = TWS live, 4002 = IB Gateway paper, 4001 = IB Gateway live.
IBKR_PORT = int(os.environ.get("IBKR_PORT", "7497"))
IBKR_CLIENT_ID = int(os.environ.get("IBKR_CLIENT_ID", "17"))
_REQUEST_TIMEOUT = 8  # max time we wait for connect + positions round trip

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
                await ib.connectAsync(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID, timeout=_REQUEST_TIMEOUT)
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
