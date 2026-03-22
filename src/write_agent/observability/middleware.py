"""
可观测中间件。
"""
from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from write_agent.observability.context import (
    generate_request_id,
    generate_trace_id,
    reset_trace_request,
    set_trace_request,
)
from write_agent.observability.utils import emit_obs_event, obs_scope


class TraceContextMiddleware(BaseHTTPMiddleware):
    """为每个请求注入 trace_id/request_id，并记录请求级事件。"""

    async def dispatch(self, request: Request, call_next):
        incoming_trace_id = (request.headers.get("X-Trace-Id") or "").strip()
        trace_id = incoming_trace_id or generate_trace_id()
        request_id = generate_request_id()

        tokens = set_trace_request(trace_id, request_id)
        with obs_scope(
            node_key="API.MIDDLEWARE.REQUEST",
            behavior_key="HTTP_SYNC",
        ):
            emit_obs_event(
                level="INFO",
                message="request.start",
                api_path=request.url.path,
                http_method=request.method,
                payload={
                    "query": dict(request.query_params),
                    "client": request.client.host if request.client else "",
                },
            )
            try:
                response = await call_next(request)
            except Exception as error:
                emit_obs_event(
                    level="ERROR",
                    message="request.exception",
                    error_code="E_REQUEST_EXCEPTION",
                    api_path=request.url.path,
                    http_method=request.method,
                    payload={"error": str(error)},
                )
                reset_trace_request(tokens)
                raise

            response.headers["X-Trace-Id"] = trace_id
            response.headers["X-Request-Id"] = request_id

            emit_obs_event(
                level="INFO",
                message="request.end",
                api_path=request.url.path,
                http_method=request.method,
                http_status=response.status_code,
            )
            reset_trace_request(tokens)
            return response
