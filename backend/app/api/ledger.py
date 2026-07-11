"""Conviction ledger endpoint — entries, latest levels per ticker, and the
calibration summary, scored against live (cached) quotes on each read."""
from fastapi import APIRouter, Depends

from ..data.live_quote import live_quote
from ..reports import ledger
from .deps import get_registry

router = APIRouter(tags=["ledger"])


@router.get("/ledger")
def get_ledger(registry=Depends(get_registry)):
    data = ledger.score(lambda t: live_quote(t, registry.yahoo))
    return {"entries": data["entries"], "levels": data["levels"],
            "summary": ledger.summary()}
