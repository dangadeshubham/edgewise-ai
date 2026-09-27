"""
EDGEWISE AI — FastAPI Application Entry Point

Assembles the application with:
- CORS middleware
- API routers
- Health endpoints
- Lifespan events (startup/shutdown)
- Request ID middleware
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import close_db, init_db
from app.core.logging import setup_logging

settings = get_settings()

APP_VERSION = "0.1.0"
APP_START_TIME: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    global APP_START_TIME
    APP_START_TIME = time.time()

    log = structlog.get_logger("edgewise.startup")

    # Setup logging
    setup_logging(settings.backend_log_level)

    # Ensure data directories exist
    settings.ensure_directories()

    # Initialize database tables
    await init_db()

    await log.ainfo(
        "edgewise_started",
        device_id=settings.device_id,
        device_name=settings.device_name,
        site=settings.device_site,
        version=APP_VERSION,
    )

    yield  # Application runs

    # Shutdown
    await close_db()
    await log.ainfo("edgewise_shutdown")


app = FastAPI(
    title="EDGEWISE AI",
    description="Offline-First AI Edge Memory & Intelligence Platform",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request ID Middleware ---
@app.middleware("http")
async def add_request_id(request: Request, call_next) -> Response:
    """Attach a unique request ID to every request for tracing."""
    request_id = str(uuid.uuid4())[:8]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"

    return response


# --- Mount Routers ---
from app.api.v1.health import router as health_router
from app.api.router import api_router

app.include_router(health_router)
app.include_router(api_router)


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with application info."""
    return {
        "name": "EDGEWISE AI",
        "tagline": "Offline Intelligence. Persistent Memory. Intelligent Sync.",
        "version": APP_VERSION,
        "device_id": settings.device_id,
        "docs": "/docs",
    }
