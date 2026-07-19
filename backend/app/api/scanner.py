"""Scanner status for the dashboard — running flag, latest setups, market
sessions. Market toggles persist through the existing PUT /api/settings."""
import os

from fastapi import APIRouter

from .. import market_calendar as cal
from .. import scanner as scanner_mod
from ..settings import load_settings

router = APIRouter(tags=["scanner"])


@router.get("/scanner")
def scanner_status():
    state = scanner_mod._load_state()
    settings = load_settings()
    return {
        "running": os.path.exists(scanner_mod.LOCK_FILE),
        "markets": {r: {"enabled": settings.get("scan_markets", {}).get(r, True),
                        "open": cal.status(r)["is_open"]}
                    for r in ("US", "SG", "HK", "JP", "KR")},
        "latest": state.get("latest", []),
        "cloud_runs_today": state.get("cloud_runs", {}),
        "local_llm": bool(os.environ.get("LOCAL_LLM_BASE_URL", "").strip()),
    }
