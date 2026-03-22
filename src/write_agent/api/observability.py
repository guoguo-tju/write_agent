"""
可观测检索 API。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from write_agent.core import get_settings
from write_agent.observability import (
    BEHAVIOR_REGISTRY,
    NODE_REGISTRY,
    emit_obs_event,
    obs_scope,
)
from write_agent.observability.emitter import get_observability_emitter

router = APIRouter(prefix="/observability", tags=["Observability"])
settings = get_settings()
emitter = get_observability_emitter()


def _is_loopback(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    return client_host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _require_obs_access(request: Request, token: Optional[str]) -> None:
    expected = (settings.obs_token or "").strip()
    if expected:
        if (token or "").strip() != expected:
            raise HTTPException(status_code=401, detail="observability token 无效")
        return
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="observability 仅允许本机访问")


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"无效时间格式: {value}")


def _event_to_dict(event) -> dict:
    payload = {}
    if event.payload_json:
        try:
            payload = json.loads(event.payload_json)
        except Exception:
            payload = {"raw": event.payload_json}
    return {
        "event_id": event.event_id,
        "ts": event.ts.isoformat(),
        "level": event.level,
        "trace_id": event.trace_id,
        "request_id": event.request_id,
        "node_id": event.node_id,
        "node_key": event.node_key,
        "behavior_id": event.behavior_id,
        "behavior_key": event.behavior_key,
        "service": event.service,
        "api_path": event.api_path,
        "http_method": event.http_method,
        "http_status": event.http_status,
        "rewrite_id": event.rewrite_id,
        "review_id": event.review_id,
        "material_id": event.material_id,
        "cover_id": event.cover_id,
        "week_key": event.week_key,
        "stage": event.stage,
        "round": event.round,
        "error_code": event.error_code,
        "message": event.message,
        "payload": payload,
    }


@router.get("/events")
async def query_observability_events(
    request: Request,
    trace_id: Optional[str] = None,
    node_id: Optional[str] = None,
    behavior_id: Optional[str] = None,
    rewrite_id: Optional[int] = None,
    review_id: Optional[int] = None,
    material_id: Optional[int] = None,
    cover_id: Optional[int] = None,
    week_key: Optional[str] = None,
    level: Optional[str] = None,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    x_obs_token: Optional[str] = Header(default=None, alias="X-Obs-Token"),
):
    _require_obs_access(request, x_obs_token)
    with obs_scope("OBS.API.QUERY_EVENTS", "HTTP_SYNC"):
        events, total = emitter.query_events(
            trace_id=trace_id,
            node_id=node_id,
            behavior_id=behavior_id,
            rewrite_id=rewrite_id,
            review_id=review_id,
            material_id=material_id,
            cover_id=cover_id,
            week_key=week_key,
            level=level,
            from_ts=_parse_iso_datetime(from_ts),
            to_ts=_parse_iso_datetime(to_ts),
            limit=limit,
            offset=offset,
        )
        emit_obs_event(
            level="INFO",
            message="observability.query_events",
            payload={
                "trace_id": trace_id,
                "node_id": node_id,
                "behavior_id": behavior_id,
                "limit": limit,
                "offset": offset,
                "total": total,
            },
        )
        return {
            "items": [_event_to_dict(event) for event in events],
            "total": total,
            "page": offset // limit + 1,
            "limit": limit,
        }


@router.get("/traces/{trace_id}")
async def get_trace_timeline(
    trace_id: str,
    request: Request,
    x_obs_token: Optional[str] = Header(default=None, alias="X-Obs-Token"),
):
    _require_obs_access(request, x_obs_token)
    with obs_scope("OBS.API.TRACE_DETAIL", "HTTP_SYNC"):
        rows = emitter.trace_timeline(trace_id)
        emit_obs_event(
            level="INFO",
            message="observability.trace_timeline",
            payload={"trace_id": trace_id, "count": len(rows)},
        )
        entities = {
            "rewrite_ids": sorted(
                {item.rewrite_id for item in rows if item.rewrite_id is not None}
            ),
            "review_ids": sorted(
                {item.review_id for item in rows if item.review_id is not None}
            ),
            "material_ids": sorted(
                {item.material_id for item in rows if item.material_id is not None}
            ),
            "cover_ids": sorted(
                {item.cover_id for item in rows if item.cover_id is not None}
            ),
            "week_keys": sorted({item.week_key for item in rows if item.week_key}),
        }
        return {
            "trace_id": trace_id,
            "timeline": [_event_to_dict(item) for item in rows],
            "entities": entities,
            "total": len(rows),
        }


@router.get("/nodes")
async def list_observability_nodes(
    request: Request,
    x_obs_token: Optional[str] = Header(default=None, alias="X-Obs-Token"),
):
    _require_obs_access(request, x_obs_token)
    with obs_scope("OBS.API.NODES", "HTTP_SYNC"):
        items = [
            {
                "node_id": node.node_id,
                "node_key": node.node_key,
                "module_path": node.module_path,
                "function_name": node.function_name,
                "owner": node.owner,
                "description": node.description,
                "in_out_contract": node.in_out_contract,
            }
            for node in sorted(NODE_REGISTRY.values(), key=lambda item: item.node_id)
        ]
        return {"items": items, "total": len(items)}


@router.get("/nodes/{node_id}")
async def get_observability_node(
    node_id: str,
    request: Request,
    x_obs_token: Optional[str] = Header(default=None, alias="X-Obs-Token"),
):
    _require_obs_access(request, x_obs_token)
    with obs_scope("OBS.API.NODE_DETAIL", "HTTP_SYNC"):
        target = None
        for node in NODE_REGISTRY.values():
            if node.node_id == node_id:
                target = node
                break
        if target is None:
            raise HTTPException(status_code=404, detail=f"node_id 不存在: {node_id}")

        return {
            "node_id": target.node_id,
            "node_key": target.node_key,
            "module_path": target.module_path,
            "function_name": target.function_name,
            "owner": target.owner,
            "description": target.description,
            "in_out_contract": target.in_out_contract,
            "behaviors": [
                {
                    "behavior_id": item.behavior_id,
                    "behavior_key": item.behavior_key,
                    "description": item.description,
                }
                for item in sorted(
                    BEHAVIOR_REGISTRY.values(), key=lambda value: value.behavior_id
                )
            ],
            "common_error_codes": [
                "E_BAD_REQUEST",
                "E_NOT_FOUND",
                "E_CONFLICT",
                "E_INTERNAL",
                "E_NODE_UNREGISTERED",
                "E_BEHAVIOR_UNREGISTERED",
            ],
        }
