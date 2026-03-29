"""Linux.do 趋势 API。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from write_agent.observability import bind_entities, emit_obs_event, obs_scope
from write_agent.services.linuxdo_trending_service import (
    RefreshCoolingDownError,
    RefreshInProgressError,
    RefreshRateLimitedError,
    get_linuxdo_trending_service,
)

router = APIRouter(prefix="/linuxdo-trends", tags=["Linux.do 趋势"])
service = get_linuxdo_trending_service()


class LinuxDoTrendItem(BaseModel):
    rank: int
    topic_id: int
    title: str
    content: str
    author: Optional[str] = None
    tags: list[str] = []
    reply_count: int
    view_count: int
    like_count: int
    publish_time: str
    topic_url: str


class LinuxDoTrendSnapshotResponse(BaseModel):
    period_type: str
    period_key: str
    requested_period_key: str
    snapshot_date: str
    captured_at: str
    is_stale: bool
    is_refreshing: bool
    fetch_error: Optional[str] = None
    available_tags: list[str] = []
    items: list[LinuxDoTrendItem]


class LinuxDoTrendPeriodOption(BaseModel):
    period_key: str
    latest_snapshot_date: str
    latest_captured_at: str


class LinuxDoRefreshRequest(BaseModel):
    period_type: str = Field(default="weekly")


class LinuxDoAddItemRequest(BaseModel):
    period_type: str
    period_key: str
    topic_id: int


class LinuxDoBuildRewriteRequest(BaseModel):
    period_type: str
    period_key: str
    topic_id: int


class LinuxDoTopicDetailResponse(BaseModel):
    topic_id: int
    title: str
    content: str
    author: str
    publish_time: str
    topic_url: str


@router.get("", response_model=LinuxDoTrendSnapshotResponse)
async def get_linuxdo_trends(
    period_type: str = "weekly",
    period_key: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 20,
):
    with obs_scope(
        "API.LINUXDO_TRENDS.GET",
        "HTTP_SYNC",
        entities={"period_type": period_type, "period_key": period_key},
    ):
        try:
            data = service.get_snapshot(
                period_type=period_type,
                period_key=period_key,
                tag=tag,
                limit=limit,
            )
            emit_obs_event(
                level="INFO",
                message="api.linuxdo_trends.get",
                entities={
                    "period_type": data.get("period_type"),
                    "period_key": data.get("requested_period_key"),
                },
            )
            return LinuxDoTrendSnapshotResponse(**data)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"获取 Linux.do 趋势失败: {error}")


@router.get("/periods", response_model=list[LinuxDoTrendPeriodOption])
async def get_linuxdo_trend_periods(period_type: str = "weekly"):
    with obs_scope(
        "API.LINUXDO_TRENDS.PERIODS",
        "HTTP_SYNC",
        entities={"period_type": period_type},
    ):
        try:
            periods = service.list_periods(period_type=period_type)
            emit_obs_event(
                level="INFO",
                message="api.linuxdo_trends.periods",
                payload={"period_type": period_type, "total": len(periods)},
            )
            return [LinuxDoTrendPeriodOption(**item) for item in periods]
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"获取 Linux.do 周期列表失败: {error}")


@router.post("/refresh", response_model=LinuxDoTrendSnapshotResponse)
async def refresh_linuxdo_trends(request: LinuxDoRefreshRequest):
    with obs_scope(
        "API.LINUXDO_TRENDS.REFRESH",
        "HTTP_SYNC",
        entities={"period_type": request.period_type},
    ):
        try:
            snapshot = await service.refresh_snapshot(period_type=request.period_type)
            data = service.get_snapshot(period_type=request.period_type, period_key=snapshot.period_key)
            bind_entities({"period_key": data.get("period_key")})
            emit_obs_event(
                level="INFO",
                message="api.linuxdo_trends.refresh",
                entities={"period_type": request.period_type, "period_key": data.get("period_key")},
            )
            return LinuxDoTrendSnapshotResponse(**data)
        except RefreshInProgressError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
        except RefreshCoolingDownError as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(error),
                headers={"Retry-After": str(error.retry_after_seconds)},
            )
        except RefreshRateLimitedError as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(error),
                headers={"Retry-After": str(error.retry_after_seconds)},
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"更新 Linux.do 趋势失败: {error}")


@router.get("/topics/{topic_id}", response_model=LinuxDoTopicDetailResponse)
async def get_linuxdo_topic_detail(topic_id: int):
    with obs_scope(
        "API.LINUXDO_TRENDS.TOPIC_DETAIL",
        "HTTP_SYNC",
        entities={"topic_id": topic_id},
    ):
        try:
            detail = service.get_topic_detail(topic_id)
            emit_obs_event(
                level="INFO",
                message="api.linuxdo_trends.topic_detail",
                entities={"topic_id": topic_id},
            )
            return LinuxDoTopicDetailResponse(**detail)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"获取帖子详情失败: {error}")


@router.post("/materials/add-item")
async def add_linuxdo_item_to_materials(request: LinuxDoAddItemRequest):
    with obs_scope(
        "API.LINUXDO_TRENDS.ADD_ITEM",
        "HTTP_SYNC",
        entities={"period_type": request.period_type, "period_key": request.period_key},
    ):
        try:
            result = service.add_item_to_materials(
                period_type=request.period_type,
                period_key=request.period_key,
                topic_id=request.topic_id,
            )
            bind_entities({"material_id": result.get("material_id")})
            emit_obs_event(
                level="INFO",
                message="api.linuxdo_trends.add_item",
                entities={"material_id": result.get("material_id")},
                payload={"topic_id": request.topic_id},
            )
            return {"status": "ok", **result}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"加入素材库失败: {error}")


@router.post("/rewrite/build-item")
async def build_linuxdo_item_rewrite(request: LinuxDoBuildRewriteRequest):
    with obs_scope(
        "API.LINUXDO_TRENDS.BUILD_REWRITE",
        "HTTP_SYNC",
        entities={"period_type": request.period_type, "period_key": request.period_key},
    ):
        try:
            result = service.build_item_rewrite_markdown(
                period_type=request.period_type,
                period_key=request.period_key,
                topic_id=request.topic_id,
            )
            emit_obs_event(
                level="INFO",
                message="api.linuxdo_trends.build_rewrite",
                payload={"topic_id": request.topic_id},
            )
            return {"status": "ok", **result}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"构建改写内容失败: {error}")
