"""Portfolio health — the PM-grade structural assessment.

Separate from /api/portfolio (positions and valuation) and /api/reports
(LLM write-ups): this is deterministic portfolio construction analysis and
spends nothing, so it is safe to poll from the dashboard.
"""
from fastapi import APIRouter, Query

router = APIRouter(tags=["health"])


@router.get("/portfolio/health")
def portfolio_health(sync: bool = Query(False, description="pull live broker positions first")):
    from ..health_check import run
    return run(sync_brokers=sync)
