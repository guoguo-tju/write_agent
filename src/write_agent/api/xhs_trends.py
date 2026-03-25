"""
小红书热点 API。
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from write_agent.observability import attach_obs_meta, emit_obs_event, obs_scope
from write_agent.services.xhs_trends_service import get_xhs_trends_service

router = APIRouter(prefix="/xhs-trends", tags=["小红书热点"])
service = get_xhs_trends_service()


class XhsCategory(BaseModel):
    key: str
    name: str
    name_en: str


class XhsTrendItem(BaseModel):
    id: str = ""
    title: str
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
            if request.background:
                background_tasks.add_task(service.refresh, request.category_key)
                emit_obs_event(
                    level="INFO",
                    message="api.xhs_trends.refresh.accepted",
                    entities={"category_key": request.category_key},
                    payload={"background": True},
                )
                return RefreshXhsTrendsResponse(
                    status="accepted",
                    updated_at=service.get_cache_updated_at(),
                    refreshed_categories=[],
                    errors={},
                )
            result = service.refresh(request.category_key)
            emit_obs_event(
                level="INFO",
                message="api.xhs_trends.refresh",
                entities={"category_key": request.category_key},
                payload={
                    "refreshed": len(result.get("refreshed_categories", [])),
                    "errors": len(result.get("errors", {})),
                },
            )
            return RefreshXhsTrendsResponse(status="ok", **result)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"刷新热点失败: {error}")


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
