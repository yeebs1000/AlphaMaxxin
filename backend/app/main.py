"""FastAPI app factory. Run with:
    cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000
Serves the built frontend from frontend/dist when present."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import load_env
from .api import routers

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
LOCAL_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173",
                 "http://localhost:8000", "http://127.0.0.1:8000"]


def create_app() -> FastAPI:
    load_env()
    app = FastAPI(title="AlphaMaxxin", version="2.0.0-dev")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=LOCAL_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_local_browser_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if (request.method not in {"GET", "HEAD", "OPTIONS"}
                and origin is not None and origin not in LOCAL_ORIGINS):
            return JSONResponse({"detail": "untrusted browser origin"}, status_code=403)
        return await call_next(request)

    app.add_middleware(TrustedHostMiddleware,
                       allowed_hosts=["localhost", "127.0.0.1"], www_redirect=False)
    for router in routers:
        app.include_router(router, prefix="/api")
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
    return app


app = create_app()
