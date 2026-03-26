"""
小红书热点 API。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from write_agent.observability import attach_obs_meta, emit_obs_event, obs_scope
from write_agent.services.xhs_trends_service import RefreshInProgressError, get_xhs_trends_service

router = APIRouter(prefix="/xhs-trends", tags=["小红书热点"])
service = get_xhs_trends_service()


class XhsCategory(BaseModel):
    key: str
    name: str
    name_en: str


class XhsTrendItem(BaseModel):
    id: str = ""
    title: str
    content: str = ""
    content_type: str
    like_count: int
    favorite_count: int
    comment_count: int
    publish_time: str
    source_url: str = ""
    hot_score: float
    interactions: int


class XhsTrendListResponse(BaseModel):
    category_key: str
    category_name: str
    category_name_en: str
    sort: str
    lookback_days: int
    min_interactions: int
    updated_at: str
    fetch_error: Optional[str] = None
    is_stale: bool = False
    items: list[XhsTrendItem]


class RefreshXhsTrendsRequest(BaseModel):
    category_key: Optional[str] = None
    background: bool = False


class RefreshXhsTrendsResponse(BaseModel):
    status: str
    updated_at: str
    refreshed_categories: list[str]
    errors: dict[str, str] = Field(default_factory=dict)


class XhsRecentEnrichStatus(BaseModel):
    ttl_seconds: int
    last_enriched_at: str = ""
    next_eligible_at: str = ""
    enriched_item_count: int = 0
    recent_item_count: int = 0
    is_recent: bool = False


class XhsRefreshStatusResponse(BaseModel):
    category_key: str
    category_name: str
    category_name_en: str
    updated_at: str
    fetch_error: Optional[str] = None
    refresh_in_progress: bool
    busy_categories: list[str] = Field(default_factory=list)
    refresh_lock: dict[str, Any] = Field(default_factory=dict)
    recent_enrich: XhsRecentEnrichStatus


class XhsCommentTopic(BaseModel):
    topic: str
    ratio: str
    sample_comment: str


class XhsInspirationCard(BaseModel):
    topic: str
    content_type: str
    title_hook: str
    rationale: str


class XhsTrendAnalysisDone(BaseModel):
    category_key: str
    category_name: str
    generated_at: str
    reason_points: list[str]
    comment_topics: list[XhsCommentTopic]
    inspiration_cards: list[XhsInspirationCard]


class XhsAnalysisSseEvent(BaseModel):
    type: str
    category_key: str
    stage: Optional[str] = None
    message: Optional[str] = None
    data: Optional[XhsTrendAnalysisDone] = None


def _refresh_in_progress_message() -> str:
    return "E_XHS_REFRESH_IN_PROGRESS: 分类刷新正在进行中，请稍后重试"


def _resolve_refresh_category_key(requested_key: Optional[str]) -> str:
    key = (requested_key or "").strip()
    if key:
        return key
    return service.get_default_category_key()


def _run_refresh_with_enrichment(category_key: str) -> None:
    try:
        result = service.refresh(category_key)
        refreshed_categories = list(result.get("refreshed_categories", []))
        if refreshed_categories:
            service.enrich_comments_for_categories(refreshed_categories)
    except RefreshInProgressError as error:
        emit_obs_event(
            level="INFO",
            message="api.xhs_trends.refresh.background_in_progress",
            entities={"category_key": category_key},
            payload={"busy_categories": error.category_keys},
        )
    except Exception as error:
        emit_obs_event(
            level="WARNING",
            message="api.xhs_trends.refresh.background_failed",
            entities={"category_key": category_key},
            error_code="E_XHS_REFRESH_BACKGROUND_FAILED",
            payload={"error": str(error)},
        )


@router.get("/categories", response_model=list[XhsCategory])
async def list_xhs_categories():
    with obs_scope("API.XHS_TRENDS.CATEGORIES", "HTTP_SYNC"):
        try:
            categories = service.list_categories()
            emit_obs_event(
                level="INFO",
                message="api.xhs_trends.categories",
                payload={"total": len(categories)},
            )
            return [XhsCategory(**item) for item in categories]
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"获取分类失败: {error}")


@router.get("", response_model=XhsTrendListResponse)
async def get_xhs_trends(
    category_key: str,
    sort: str = "hot",
    limit: int = 10,
):
    with obs_scope("API.XHS_TRENDS.GET", "HTTP_SYNC", entities={"category_key": category_key}):
        try:
            payload = service.get_trends(category_key, sort=sort, limit=limit)
            emit_obs_event(
                level="INFO",
                message="api.xhs_trends.get",
                entities={"category_key": category_key},
                payload={"sort": sort, "limit": limit, "items": len(payload.get("items", []))},
            )
            return XhsTrendListResponse(**payload)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"获取热点失败: {error}")


@router.post("/refresh", response_model=RefreshXhsTrendsResponse)
async def refresh_xhs_trends(request: RefreshXhsTrendsRequest, background_tasks: BackgroundTasks):
    with obs_scope(
        "API.XHS_TRENDS.REFRESH",
        "HTTP_SYNC",
        entities={"category_key": request.category_key},
    ):
        try:
            resolved_category_key = _resolve_refresh_category_key(request.category_key)
            if request.background:
                if service.is_refresh_in_progress(resolved_category_key):
                    emit_obs_event(
                        level="INFO",
                        message="api.xhs_trends.refresh.in_progress",
                        entities={"category_key": resolved_category_key},
                    )
                    return RefreshXhsTrendsResponse(
                        status="in_progress",
                        updated_at=service.get_cache_updated_at(),
                        refreshed_categories=[],
                        errors={resolved_category_key: _refresh_in_progress_message()},
                    )
                background_tasks.add_task(_run_refresh_with_enrichment, resolved_category_key)
                emit_obs_event(
                    level="INFO",
                    message="api.xhs_trends.refresh.accepted",
                    entities={"category_key": resolved_category_key},
                    payload={"background": True},
                )
                return RefreshXhsTrendsResponse(
                    status="accepted",
                    updated_at=service.get_cache_updated_at(),
                    refreshed_categories=[],
                    errors={},
                )
            result = service.refresh(resolved_category_key)
            refreshed_categories = list(result.get("refreshed_categories", []))
            if refreshed_categories:
                background_tasks.add_task(service.enrich_comments_for_categories, refreshed_categories)
            emit_obs_event(
                level="INFO",
                message="api.xhs_trends.refresh",
                entities={"category_key": resolved_category_key},
                payload={
                    "refreshed": len(result.get("refreshed_categories", [])),
                    "errors": len(result.get("errors", {})),
                },
            )
            return RefreshXhsTrendsResponse(status="ok", **result)
        except RefreshInProgressError as error:
            busy_categories = error.category_keys or [request.category_key or "unknown"]
            emit_obs_event(
                level="INFO",
                message="api.xhs_trends.refresh.in_progress",
                payload={"busy_categories": busy_categories},
            )
            return RefreshXhsTrendsResponse(
                status="in_progress",
                updated_at=service.get_cache_updated_at(),
                refreshed_categories=[],
                errors={key: _refresh_in_progress_message() for key in busy_categories},
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"刷新热点失败: {error}")


@router.get("/refresh/status", response_model=XhsRefreshStatusResponse)
async def get_xhs_refresh_status(category_key: Optional[str] = None):
    with obs_scope(
        "API.XHS_TRENDS.REFRESH_STATUS",
        "HTTP_SYNC",
        entities={"category_key": category_key},
    ):
        try:
            payload = service.get_refresh_status(category_key)
            emit_obs_event(
                level="INFO",
                message="api.xhs_trends.refresh_status",
                entities={"category_key": payload.get("category_key")},
                payload={
                    "refresh_in_progress": payload.get("refresh_in_progress"),
                    "recent_item_count": payload.get("recent_enrich", {}).get("recent_item_count", 0),
                },
            )
            return XhsRefreshStatusResponse(**payload)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"查询刷新状态失败: {error}")


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _analysis_sse_with_obs(
    payload: dict,
    *,
    category_key: str,
) -> str:
    enriched = attach_obs_meta(
        payload,
        node_key="API.XHS_TRENDS.SSE_EVENT",
        behavior_key="HTTP_SSE_STREAM",
        entities={"category_key": category_key, "stage": payload.get("stage")},
    )
    return _sse_event(enriched)


@router.get("/analysis/stream")
async def stream_xhs_trend_analysis(category_key: str):
    with obs_scope(
        "API.XHS_TRENDS.ANALYSIS_STREAM",
        "HTTP_SSE_STREAM",
        entities={"category_key": category_key},
    ):
        try:
            service.get_trends(category_key, sort="hot", limit=10)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"分析前检查失败: {error}")

        def generate():
            try:
                yield _analysis_sse_with_obs(
                    {
                        "type": "start",
                        "category_key": category_key,
                        "stage": "start",
                        "message": "开始分析",
                    },
                    category_key=category_key,
                )
                yield _analysis_sse_with_obs(
                    {
                        "type": "progress",
                        "category_key": category_key,
                        "stage": "aggregate",
                        "message": "整理热点样本",
                    },
                    category_key=category_key,
                )

                done_payload = XhsTrendAnalysisDone(**service.build_analysis(category_key))

                yield _analysis_sse_with_obs(
                    {
                        "type": "progress",
                        "category_key": category_key,
                        "stage": "summarize",
                        "message": "生成热点洞察",
                    },
                    category_key=category_key,
                )
                yield _analysis_sse_with_obs(
                    {
                        "type": "done",
                        "category_key": category_key,
                        "stage": "done",
                        "data": done_payload.model_dump(),
                    },
                    category_key=category_key,
                )
            except Exception as error:
                emit_obs_event(
                    level="ERROR",
                    message="api.xhs_trends.analysis.error",
                    entities={"category_key": category_key},
                    error_code="E_XHS_ANALYSIS_STREAM",
                    payload={"error": str(error)},
                )
                yield _analysis_sse_with_obs(
                    {
                        "type": "error",
                        "category_key": category_key,
                        "stage": "error",
                        "message": str(error),
                    },
                    category_key=category_key,
                )

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
