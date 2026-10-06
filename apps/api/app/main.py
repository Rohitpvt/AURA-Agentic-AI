"""AURA Control Plane - FastAPI Main Application Entrypoint."""

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.errors import (
    AuraException,
    aura_exception_handler,
    generic_exception_handler,
)
from app.core.logging import correlation_id_ctx, logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and shutdown hooks."""
    setup_logging(log_level=settings.AURA_LOG_LEVEL)
    logger.info(
        f"Starting AURA Control Plane [env={settings.AURA_ENV}, local_model={settings.LOCAL_MODEL_GENERAL}]"
    )
    logger.info(f"Ollama local runtime endpoint configured at: {settings.OLLAMA_BASE_URL}")

    from app.workers.scheduler_daemon import scheduler_daemon
    from app.workers.telegram_daemon import telegram_daemon
    if not settings.is_testing:
        await scheduler_daemon.start()
        await telegram_daemon.start()

    from app.db.session import async_session_factory
    from app.services.file_job_service import file_job_service
    from app.services.task_recovery_service import task_recovery_service
    async with async_session_factory() as session:
        await file_job_service.recover_stuck_jobs(session)
        await task_recovery_service.startup_recovery_sweep(session)

    from app.tray.ipc import AuraNamedPipeServer
    import platform
    ipc_server = AuraNamedPipeServer()
    if not settings.is_testing and platform.system() == "Windows":
        await ipc_server.start()

    yield

    if not settings.is_testing and platform.system() == "Windows":
        await ipc_server.stop()

    if not settings.is_testing:
        await telegram_daemon.stop()
        await scheduler_daemon.stop()

    from app.services.tools.browser_manager import browser_manager
    await browser_manager.close()

    logger.info("Shutting down AURA Control Plane")


app = FastAPI(
    title="AURA Control Plane API",
    description="Deterministic Control Plane for the AURA Personal Agentic AI Operating System (100% Zero-Cost Local-First)",
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)

from app.core.telemetry import telemetry_manager

# 1. CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "X-Response-Time-Ms", "X-Trace-ID", "traceparent"],
)


# 2. Correlation ID, Distributed Tracing & Execution Timing Middleware
@app.middleware("http")
async def correlation_and_timing_middleware(request: Request, call_next) -> Response:
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    correlation_id_ctx.set(correlation_id)

    # Extract incoming W3C trace context (e.g. from upstream client / web dashboard)
    parent_ctx = telemetry_manager.extract_trace_context(dict(request.headers))
    url_path = request.url.path

    start_time = time.perf_counter()
    async with telemetry_manager.start_async_span(
        name=f"http.{request.method.lower()} {url_path}",
        span_type="http.server",
        parent_context=parent_ctx,
        attributes={
            "http.method": request.method,
            "http.url_path": url_path,
            "aura.correlation_id": correlation_id,
        },
    ) as span:
        try:
            response: Response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            
            # Inject active trace_id and W3C traceparent into response headers while inside span
            active_trace_id = telemetry_manager.get_current_trace_id()
            if active_trace_id:
                response.headers["X-Trace-ID"] = active_trace_id
                telemetry_manager.inject_trace_context(response.headers)
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            correlation_id_ctx.set("")

    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"
    return response


# 3. Exception Handlers
app.add_exception_handler(AuraException, aura_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# 4. Mount API Routers
app.include_router(api_v1_router)


# 5. Root Liveness Probe Alias
@app.get("/health", tags=["Health"], summary="Root Liveness Probe")
async def root_health():
    return {
        "status": "healthy",
        "service": "aura-control-plane",
        "version": "1.0.0",
        "zero_cost_mode": True,
    }
