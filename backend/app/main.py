import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.routes import admin, auth, meetings, search
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import CorrelationMiddleware
from app.db.session import AsyncSessionLocal
from app.services.storage import internal_s3_client
from app.services.vector_store import qdrant_client

configure_logging()
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    structlog.get_logger().info("application_starting", environment=settings.app_env)
    yield
    structlog.get_logger().info("application_stopping")


app = FastAPI(
    title="MeetAI API",
    version="0.1.0",
    description="Tenant-safe meeting intelligence and grounded retrieval API",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None,
)
app.add_middleware(CorrelationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
for route_group in (auth.router, meetings.router, search.router, admin.router):
    app.include_router(route_group, prefix="/api/v1")


@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def readiness() -> ORJSONResponse:
    checks: dict[str, str] = {}
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["mysql"] = "ok"
    except Exception:
        checks["mysql"] = "unavailable"
    try:
        redis = Redis.from_url(settings.redis_url)
        await redis.ping()
        await redis.aclose()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable (optional)"
    qdrant = qdrant_client()
    if qdrant is not None:
        try:
            await qdrant.get_collections()
            checks["qdrant"] = "ok"
        except Exception:
            checks["qdrant"] = "unavailable"
    else:
        checks["qdrant"] = "not configured (optional)"
    try:
        s3 = internal_s3_client()
        if s3:
            await asyncio.to_thread(s3.head_bucket, Bucket=settings.aws_s3_bucket)
            checks["s3"] = "ok"
        else:
            checks["s3"] = "not configured (local file storage)"
    except Exception:
        checks["s3"] = "unavailable (using local storage)"
    essential_ok = checks.get("mysql") == "ok"
    return ORJSONResponse(
        {"status": "ok" if essential_ok else "degraded", "checks": checks},
        status_code=200 if essential_ok else 503,
    )


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> ORJSONResponse:
    correlation = getattr(request.state, "correlation_id", "unknown")
    structlog.get_logger().exception(
        "unhandled_exception", correlation_id=correlation, error_type=type(exc).__name__
    )
    return ORJSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "correlation_id": correlation},
    )
