"""
可观测工具函数。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

from write_agent.observability.context import current_context, scoped_node_behavior
from write_agent.observability.emitter import get_observability_emitter
from write_agent.observability.registry import resolve_behavior, resolve_node


def emit_obs_event(
    *,
    level: str,
    message: str,
    node_key: Optional[str] = None,
    behavior_key: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    error_code: Optional[str] = None,
    api_path: Optional[str] = None,
    http_method: Optional[str] = None,
    http_status: Optional[int] = None,
    entities: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    emitter = get_observability_emitter()
    return emitter.emit(
        level=level,
        message=message,
        node_key=node_key,
        behavior_key=behavior_key,
        payload=payload,
        error_code=error_code,
        api_path=api_path,
        http_method=http_method,
        http_status=http_status,
        extra_entities=entities,
    )


@contextmanager
def obs_scope(
    node_key: str,
    behavior_key: str,
    entities: Optional[dict[str, Any]] = None,
):
    node = resolve_node(node_key)
    behavior = resolve_behavior(behavior_key)
    with scoped_node_behavior(
        node_id=node.node_id,
        node_key=node.node_key,
        behavior_id=behavior.behavior_id,
        behavior_key=behavior.behavior_key,
        entities=entities,
    ):
        yield


def build_obs_meta(
    node_key: Optional[str] = None,
    behavior_key: Optional[str] = None,
) -> dict[str, Any]:
    ctx = current_context()
    node = resolve_node(node_key or ctx.node_key or None)
    behavior = resolve_behavior(behavior_key or ctx.behavior_key or None)
    return {
        "trace_id": ctx.trace_id,
        "request_id": ctx.request_id,
        "node_id": node.node_id,
        "node_key": node.node_key,
        "behavior_id": behavior.behavior_id,
        "behavior_key": behavior.behavior_key,
        "ts": datetime.now().isoformat(),
    }


def attach_obs_meta(
    event: dict[str, Any],
    *,
    node_key: Optional[str] = None,
    behavior_key: Optional[str] = None,
    entities: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    enriched = dict(event)
    obs = build_obs_meta(node_key=node_key, behavior_key=behavior_key)
    emitted = emit_obs_event(
        level="INFO",
        message=f"sse:{event.get('type', 'event')}",
        node_key=node_key,
        behavior_key=behavior_key,
        payload={"type": event.get("type"), "stage": event.get("stage")},
        entities={
            "rewrite_id": event.get("rewrite_id") or event.get("task_id"),
            "review_id": event.get("review_id"),
            "round": event.get("round"),
            "stage": event.get("stage"),
            **(entities or {}),
        },
    )
    obs["event_id"] = emitted.get("event_id", "")
    obs["ts"] = emitted.get("ts") or obs["ts"]
    enriched["obs"] = obs
    return enriched
