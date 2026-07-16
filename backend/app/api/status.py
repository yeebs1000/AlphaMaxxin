import os

from fastapi import APIRouter, Depends

from ..config import key_status
from .deps import get_registry

router = APIRouter(tags=["status"])


def _gateway_status(available: bool, host: str, port: int,
                    package: str, listener_hint: str) -> dict:
    """Shared local-gateway probe (moomoo OpenD / IB Gateway). Local-only TCP,
    never an external call — still skipped under the offline tripwire so the
    test suite stays fully network-free."""
    if not available:
        return {"connected": False,
                "reason": f"{package} package not installed — "
                          "pip install -r backend/requirements-backend.txt"}
    if os.environ.get("ALPHAMAXXIN_OFFLINE") == "1":
        return {"connected": False, "reason": "gateway probe skipped (offline mode)"}
    import socket
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return {"connected": True, "reason": None}
    except OSError:
        return {"connected": False,
                "reason": f"nothing listening at {host}:{port} — {listener_hint}"}


def _moomoo_status() -> dict:
    from ..brokers.moomoo_client import MOOMOO_AVAILABLE, MOOMOO_HOST, MOOMOO_PORT
    return _gateway_status(MOOMOO_AVAILABLE, MOOMOO_HOST, MOOMOO_PORT, "moomoo-api",
                           "make sure OpenD is running and logged in.")


def _ibkr_status() -> dict:
    from ..brokers.ibkr_client import IBKR_AVAILABLE, IBKR_HOST, IBKR_PORT
    return _gateway_status(IBKR_AVAILABLE, IBKR_HOST, IBKR_PORT, "ib_async",
                           "check TWS/IB Gateway is running and logged in, and "
                           "that IBKR_PORT in .env matches it (7497 TWS paper, "
                           "7496 TWS live, 4002 Gateway paper, 4001 Gateway live).")


def _tiger_status() -> dict:
    try:
        from ..brokers.tiger_client import TIGER_AVAILABLE
        if TIGER_AVAILABLE:
            return {"connected": True, "reason": None}
        return {"connected": False,
                "reason": "tigeropen installed but TIGER_ID/TIGER_ACCOUNT/"
                          "TIGER_PRIVATE_KEY_PATH aren't fully set in .env."}
    except ImportError:
        return {"connected": False,
                "reason": "tigeropen package not installed — "
                          "pip install -r backend/requirements-backend.txt"}


@router.get("/status")
def status(registry=Depends(get_registry)):
    return {
        "version": "2.0.0-dev",
        "keys": key_status(),
        "feeds": registry.feed_status(),
        "brokers": {"moomoo": _moomoo_status(), "ibkr": _ibkr_status(),
                    "tiger": _tiger_status()},
    }
