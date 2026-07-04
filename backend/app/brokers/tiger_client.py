"""
AlphaMaxxin — Tiger Brokers Position Layer
Live positions from a Tiger Brokers account via the official `tigeropen`
SDK. Read-only: no order entry.

Requires a Tiger Open API account (separate signup from your regular
trading account, free) with an RSA keypair generated per Tiger's developer
docs: https://quant.itigerup.com/openapi/en/python/operation/step1.html
Set TIGER_ID, TIGER_ACCOUNT, and TIGER_PRIVATE_KEY_PATH in .env.

Optional layer: if tigeropen isn't installed or credentials aren't
configured, get_tiger_positions() returns None and the caller falls back
to whatever else is configured (moomoo, IBKR, external_holdings.json).
"""
import os
import threading
import time

try:
    from tigeropen.tiger_open_config import TigerOpenClientConfig
    from tigeropen.trade.trade_client import TradeClient
    _TIGER_AVAILABLE = True
except ImportError:
    _TIGER_AVAILABLE = False

TIGER_ID = os.environ.get("TIGER_ID", "")
TIGER_ACCOUNT = os.environ.get("TIGER_ACCOUNT", "")
TIGER_PRIVATE_KEY_PATH = os.environ.get("TIGER_PRIVATE_KEY_PATH", "")
_REQUEST_TIMEOUT = 8

TIGER_AVAILABLE = _TIGER_AVAILABLE and bool(TIGER_ID and TIGER_ACCOUNT and TIGER_PRIVATE_KEY_PATH)

_POSITIONS_CACHE_TTL = 60
_positions_cache = None  # (timestamp, result)


def _build_client() -> "TradeClient | None":
    if not TIGER_AVAILABLE or not os.path.exists(TIGER_PRIVATE_KEY_PATH):
        return None
    try:
        with open(TIGER_PRIVATE_KEY_PATH, "r", encoding="utf-8") as f:
            private_key = f.read()
        config = TigerOpenClientConfig()
        config.private_key = private_key
        config.tiger_id = TIGER_ID
        config.account = TIGER_ACCOUNT
        return TradeClient(config)
    except Exception:
        return None


def get_tiger_positions() -> list | None:
    """
    Live positions from the connected Tiger Brokers account. Returns a list
    of dicts shaped like Portfolio.md rows, or None if tigeropen isn't
    installed, credentials aren't configured, or the request fails.
    """
    global _positions_cache
    if _positions_cache and (time.monotonic() - _positions_cache[0]) < _POSITIONS_CACHE_TTL:
        return _positions_cache[1]

    box = {}

    def _fetch():
        client = _build_client()
        if client is None:
            box["result"] = None
            return
        try:
            positions = client.get_positions(account=TIGER_ACCOUNT)
            result = []
            for p in positions:
                qty = float(getattr(p, "quantity", 0) or 0)
                if not qty:
                    continue
                contract = getattr(p, "contract", None)
                symbol = getattr(contract, "symbol", None) or getattr(p, "symbol", "")
                currency = getattr(contract, "currency", None) or "USD"
                result.append({
                    "ticker": symbol,
                    "company": symbol,
                    "quantity": qty,
                    "cost_price": float(getattr(p, "average_cost", 0) or 0),
                    "currency": currency,
                })
            box["result"] = result
        except Exception:
            box["result"] = None

    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(timeout=_REQUEST_TIMEOUT)

    result = box.get("result")
    if result is not None:
        _positions_cache = (time.monotonic(), result)
    return result
