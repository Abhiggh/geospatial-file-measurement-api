from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.routes import router
from .config import get_settings
from .db import create_all_tables
from .services.processing import worker_loop
from .services.storage import ensure_storage_dirs

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all_tables()
    ensure_storage_dirs()
    stop_event = threading.Event()
    worker_thread = None
    if settings.embedded_worker and not getattr(app.state, "testing", False):
        worker_thread = threading.Thread(target=worker_loop, args=(stop_event,), daemon=True, name="geospatial-worker")
        worker_thread.start()
    app.state.worker_stop_event = stop_event
    app.state.worker_thread = worker_thread
    yield
    stop_event.set()
    if worker_thread is not None:
        worker_thread.join(timeout=2)


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Scalable backend for KML and Shapefile measurement. "
        "Measurements are calculated locally using geospatial libraries; no external geospatial API is required."
    ),
    lifespan=lifespan,
)
app.include_router(router)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error [request_id=%s]", getattr(request.state, "request_id", "unknown"), exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error.", "request_id": getattr(request.state, "request_id", "unknown")},
    )


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": settings.app_name}


@app.get("/ready", tags=["system"])
def ready():
    # Table creation occurs during lifespan. A successful query proves the DB is reachable.
    from .db import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    finally:
        db.close()
