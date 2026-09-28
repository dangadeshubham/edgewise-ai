"""
EDGEWISE AI — FastAPI Application Entry Point

Assembles the application with:
- Structured logging with structlog
- Request ID tracing middleware
- Consistent error handling (no leaked secrets or tracebacks)
- Environment-driven configuration
- Real health and observability endpoints
- Lifespan events
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import close_db
from app.core.logging import setup_logging

settings = get_settings()

from app import __version__ as APP_VERSION
APP_START_TIME: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    global APP_START_TIME
    APP_START_TIME = time.time()

    log = structlog.get_logger("edgewise.startup")

    # Setup structured logging
    setup_logging(settings.backend_log_level)

    # Ensure required data directories exist
    settings.ensure_directories()

    # Ensure SQLite audit immutability triggers are installed
    try:
        from app.core.database import engine, install_audit_immutability
        async with engine.begin() as conn:
            await install_audit_immutability(conn)
    except Exception as e:
        await log.awarning("audit_immutability_trigger_install_failed", error=str(e))

    # Initialize connectivity manager and run initial check
    from app.services.connectivity.manager import get_connectivity_manager
    connectivity = get_connectivity_manager()

    import asyncio

    async def _audit_connectivity_listener(event):
        try:
            from app.core.database import async_session_factory
            from app.repositories.audit import AuditRepository
            async with async_session_factory() as sess:
                repo = AuditRepository(sess)
                ev_type = event.event_type.value
                if ev_type == "STATE_CHANGED":
                    ev_type = f"CONNECTIVITY_{event.new_status.upper()}"
                await repo.log_event(
                    event_type=ev_type,
                    description=event.message,
                    entity_type="connectivity",
                    entity_id=event.dependency.value if event.dependency else None,
                    details={"old": event.old_status, "new": event.new_status},
                    severity="warning" if "OFFLINE" in ev_type or "DEGRADED" in ev_type else "info",
                    device_id=settings.device_id,
                )
                await sess.commit()
        except Exception:
            pass

    connectivity.register_event_listener(
        lambda ev: asyncio.create_task(_audit_connectivity_listener(ev))
    )
    try:
        initial_state = await connectivity.check_all()
        await log.ainfo(
            "connectivity_initial_check",
            state=initial_state.value,
            mode=connectivity.application_mode,
        )
    except Exception as e:
        await log.awarning("connectivity_initial_check_failed", error=str(e))

    # Register local development device ONLY if explicitly configured
    if settings.auto_register_local_device:
        from app.core.database import async_session_factory
        from app.schemas.api import DeviceCreate
        from app.services.device.service import DeviceService
        async with async_session_factory() as session:
            service = DeviceService(session)
            dev_id = settings.device_id
            try:
                uuid.UUID(dev_id)
            except ValueError:
                dev_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, settings.device_id))
            try:
                await service.get_device(dev_id)
            except HTTPException:
                await service.register_device(
                    DeviceCreate(
                        id=dev_id,
                        name=settings.device_name,
                        site=settings.device_site,
                        status="active",
                        software_version=APP_VERSION,
                    )
                )
                await session.commit()
                await log.ainfo("local_device_registered", device_id=dev_id)

    # Phase 6: Recover abandoned sync jobs on startup
    try:
        from app.core.database import async_session_factory
        from app.services.synchronization.queue_service import SyncQueueService
        async with async_session_factory() as session:
            queue_svc = SyncQueueService(session)
            recovered = await queue_svc.recover_abandoned()
            if recovered:
                await session.commit()
                await log.ainfo("abandoned_sync_jobs_recovered_on_startup", count=len(recovered))
    except Exception as e:
        await log.awarning("sync_recovery_on_startup_failed", error=str(e))

    # Start background connectivity polling
    import asyncio

    async def _connectivity_poll():
        """Background task: periodic connectivity check."""
        while True:
            try:
                await asyncio.sleep(30)
                await connectivity.check_all()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    poll_task = asyncio.create_task(_connectivity_poll())

    await log.ainfo(
        "edgewise_started",
        device_id=settings.device_id,
        device_name=settings.device_name,
        site=settings.device_site,
        version=APP_VERSION,
        connectivity=connectivity.application_mode,
    )

    yield  # Application running

    # Shutdown
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass
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


# --- Request ID & Telemetry Middleware ---
@app.middleware("http")
async def add_request_id(request: Request, call_next) -> Response:
    """Attach a unique request ID to every request and collect latency metrics."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    from app.core.metrics import get_metrics_registry

    start = time.perf_counter()
    response = await call_next(request)
    duration_s = time.perf_counter() - start
    duration_ms = duration_s * 1000

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"

    # Collect telemetry metrics
    metrics = get_metrics_registry()
    path = request.url.path
    metrics.inc_request(request.method, path, response.status_code)
    metrics.observe_request_duration(request.method, path, duration_s)

    return response


# --- Exception Handlers ---
from app.core.errors import EdgewiseException


@app.exception_handler(EdgewiseException)
async def edgewise_exception_handler(
    request: Request, exc: EdgewiseException
) -> JSONResponse:
    """Standardized handler for domain exceptions mapping to categorized error taxonomy."""
    request_id = getattr(request.state, "request_id", None) or structlog.contextvars.get_contextvars().get("request_id")
    payload = exc.to_dict()
    payload["request_id"] = request_id

    from app.core.metrics import get_metrics_registry
    get_metrics_registry().inc_error(exc.category.value)

    log = structlog.get_logger("edgewise.error")
    await log.awarning(
        "domain_exception_handled",
        category=exc.category.value,
        status_code=exc.status_code,
        message=exc.message,
        operation_id=exc.operation_id,
        request_id=request_id,
    )
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Standardized validation error response without leaking internals."""
    request_id = getattr(request.state, "request_id", None) or structlog.contextvars.get_contextvars().get("request_id")
    errors = exc.errors()
    formatted = [
        f"{'.'.join(str(loc) for loc in err.get('loc', []))}: {err.get('msg')}"
        for err in errors
    ]
    from app.core.metrics import get_metrics_registry
    get_metrics_registry().inc_error("VALIDATION_ERROR")
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "category": "VALIDATION_ERROR",
            "detail": "; ".join(formatted),
            "request_id": request_id,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Standardized HTTP exception response."""
    request_id = getattr(request.state, "request_id", None) or structlog.contextvars.get_contextvars().get("request_id")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": f"http_{exc.status_code}",
            "detail": exc.detail,
            "request_id": request_id,
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all unhandled error handler. Never exposes raw stack traces or secrets."""
    request_id = getattr(request.state, "request_id", None) or structlog.contextvars.get_contextvars().get("request_id")
    from app.core.metrics import get_metrics_registry
    get_metrics_registry().inc_error("INTERNAL_SERVER_ERROR")

    log = structlog.get_logger("edgewise.error")
    await log.aerror("unhandled_exception", error=str(exc), exc_info=True, request_id=request_id)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "detail": "An unexpected internal server error occurred.",
            "request_id": request_id,
        },
    )


# --- Observability & Metrics Endpoints ---
from fastapi.responses import PlainTextResponse


@app.get("/metrics", tags=["Observability"])
async def prometheus_metrics() -> Response:
    """Prometheus-compatible plaintext metrics endpoint."""
    from app.core.metrics import get_metrics_registry
    return PlainTextResponse(
        get_metrics_registry().to_prometheus_format(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/api/metrics", tags=["Observability"])
async def json_metrics() -> dict:
    """Structured JSON operational metrics endpoint."""
    from app.core.metrics import get_metrics_registry
    return get_metrics_registry().to_json()


# --- Mount Routers ---
from app.api.router import api_router
from app.api.v1.health import router as health_router

app.include_router(health_router)
app.include_router(api_router)


from pathlib import Path
from fastapi.staticfiles import StaticFiles

frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
if frontend_dir.exists():
    app.mount("/copilot", StaticFiles(directory=str(frontend_dir), html=True), name="copilot")


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with application info."""
    return {
        "name": "EDGEWISE AI",
        "tagline": "Offline Intelligence. Persistent Memory. Intelligent Sync.",
        "version": APP_VERSION,
        "device_id": settings.device_id,
        "docs": "/docs",
        "copilot_ui": "/copilot/",
    }

