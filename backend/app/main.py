"""FastAPI app factory. Run with:
    cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000
Serves the built frontend from frontend/dist when present."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import load_env
from .api import routers

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def create_app() -> FastAPI:
    load_env()
    app = FastAPI(title="AlphaMaxxin", version="2.0.0-dev")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite dev server
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in routers:
        app.include_router(router, prefix="/api")
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
    return app


app = create_app()
