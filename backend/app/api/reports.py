"""Report runs (with SSE progress), history, presets, settings, costs."""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from .. import settings as settings_mod
from ..data.base import DiskTTLCache
from ..llm.analysts import lens_status
from ..llm.cache import LLMCache
from ..llm.costs import CostMeter
from ..reports import store
from ..reports.pipeline import run_report
from ..reports.presets import list_presets
from ..reports.progress import RUNS
from .deps import get_registry

router = APIRouter(tags=["reports"])

_meter = CostMeter()


class Target(BaseModel):
    kind: str = "portfolio"  # portfolio | tickers | watchlist
    tickers: list[str] = []
    watchlist_id: str | None = None


class RunRequest(BaseModel):
    preset: str = "Lite"
    target: Target = Target()
    model_overrides: dict[str, str] = {}


@router.post("/reports/run")
async def start_run(body: RunRequest, registry=Depends(get_registry)):
    run = RUNS.create(body.model_dump())
    user_settings = settings_mod.load_settings()
    cache = LLMCache(DiskTTLCache()) if user_settings["llm_cache_enabled"] else None

    async def execute():
        try:
            report_id = await run_report(
                registry, body.model_dump(), run.emit,
                cache=cache, meter=_meter, run_id=run.id,
                settings=user_settings)
            run.finish(report_id)
        except Exception as e:
            run.fail(str(e))

    asyncio.get_running_loop().create_task(execute())
    return {"run_id": run.id}


@router.get("/reports/run/{run_id}")
def run_status(run_id: str):
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run.snapshot()


@router.get("/reports/run/{run_id}/events")
async def run_events(run_id: str):
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "run not found")

    async def stream():
        async for event in run.stream():
            yield f"data: {json.dumps(event)}\n\n"
        yield f"data: {json.dumps(run.snapshot())}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/reports")
def report_history():
    return {"reports": store.list_reports()}


@router.get("/reports/{report_id}")
def get_report(report_id: str):
    report = store.load_report(report_id)
    if not report:
        raise HTTPException(404, "report not found")
    return report


@router.get("/reports/{report_id}/html")
def get_report_html(report_id: str):
    html = store.load_report_html(report_id)
    if html is None:
        raise HTTPException(404, "report not found")
    return HTMLResponse(html)


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: str):
    if not store.delete_report(report_id):
        raise HTTPException(404, "report not found")


@router.get("/presets")
def presets(registry=Depends(get_registry)):
    return {"presets": list_presets(),
            "lenses": lens_status(registry.feed_status())}


@router.get("/settings")
def get_settings():
    return settings_mod.load_settings()


@router.put("/settings")
def put_settings(body: dict):
    return settings_mod.save_settings(body)


@router.get("/costs")
def costs():
    return _meter.totals()
