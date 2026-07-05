from fastapi import APIRouter, Depends

from ..config import key_status
from .deps import get_registry

router = APIRouter(tags=["status"])


@router.get("/status")
def status(registry=Depends(get_registry)):
    broker_status = {}
    try:
        from ..brokers.moomoo_client import MOOMOO_AVAILABLE
        broker_status["moomoo"] = bool(MOOMOO_AVAILABLE)
    except ImportError:
        broker_status["moomoo"] = False
    try:
        from ..brokers.ibkr_client import IBKR_AVAILABLE
        broker_status["ibkr"] = bool(IBKR_AVAILABLE)
    except ImportError:
        broker_status["ibkr"] = False
    try:
        from ..brokers.tiger_client import TIGER_AVAILABLE
        broker_status["tiger"] = bool(TIGER_AVAILABLE)
    except ImportError:
        broker_status["tiger"] = False

    return {
        "version": "2.0.0-dev",
        "keys": key_status(),
        "feeds": registry.feed_status(),
        "brokers": broker_status,
    }
