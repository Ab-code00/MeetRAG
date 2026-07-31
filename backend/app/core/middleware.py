import time
import uuid

import structlog
from fastapi import Request, Response
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

REQUEST_COUNT = Counter(
    "meetai_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "meetai_http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))[:36]
        request.state.correlation_id = correlation_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            status = response.status_code if response else 500
            duration = time.perf_counter() - started
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            REQUEST_COUNT.labels(request.method, path, status).inc()
            REQUEST_LATENCY.labels(request.method, path).observe(duration)
            structlog.get_logger().info(
                "request_complete",
                method=request.method,
                path=path,
                status=status,
                latency_ms=round(duration * 1000),
            )
            if response:
                response.headers["X-Correlation-ID"] = correlation_id

