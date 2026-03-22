"""
GitHub 趋势 API。
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from write_agent.services.github_trending_service import (
    RefreshInProgressError,
    get_github_trending_service,
)

router = APIRouter(prefix="/github-trends", tags=["GitHub 趋势"])
service = get_github_trending_service()


class GitHubTrendItem(BaseModel):
    rank: int
    repo_full_name: str
    repo_name: str
    owner: str
    description: Optional[str] = None
    description_zh: Optional[str] = None
    repo_url: str
    stars_this_week: int
    language: Optional[str] = None
    total_stars: Optional[int] = None


class GitHubTrendSnapshotResponse(BaseModel):
    week_key: str
    requested_week_key: str
    snapshot_date: str
    captured_at: str
    is_weekly_archive: bool
    is_stale: bool
    is_refreshing: bool
    fetch_error: Optional[str] = None
    items: list[GitHubTrendItem]


class GitHubTrendWeekOption(BaseModel):
    week_key: str
    latest_snapshot_date: str
    latest_captured_at: str
    has_archive: bool


class AddItemMaterialRequest(BaseModel):
    week_key: str
    repo_full_name: str


class AddWeekDigestRequest(BaseModel):
    week_key: str


@router.get("", response_model=GitHubTrendSnapshotResponse)
async def get_github_trends(week_key: Optional[str] = None):
    try:
        data = service.get_snapshot(week_key=week_key)
        return GitHubTrendSnapshotResponse(**data)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"获取趋势失败: {error}")


@router.get("/weeks", response_model=list[GitHubTrendWeekOption])
async def get_github_trend_weeks():
    try:
        weeks = service.list_available_weeks()
        return [GitHubTrendWeekOption(**item) for item in weeks]
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"获取周列表失败: {error}")


@router.post("/refresh", response_model=GitHubTrendSnapshotResponse)
async def refresh_github_trends():
    try:
        await service.refresh_current_week_snapshot()
        data = service.get_snapshot(service.current_week_key())
        return GitHubTrendSnapshotResponse(**data)
    except RefreshInProgressError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"更新趋势失败: {error}")


@router.post("/materials/add-item")
async def add_item_to_materials(request: AddItemMaterialRequest):
    try:
        result = service.add_item_to_materials(
            week_key=request.week_key,
            repo_full_name=request.repo_full_name,
        )
        return {"status": "ok", **result}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"加入素材库失败: {error}")


@router.post("/materials/add-week-digest")
async def add_week_digest_to_materials(request: AddWeekDigestRequest):
    try:
        result = service.add_week_digest_to_materials(week_key=request.week_key)
        return {"status": "ok", **result}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"加入周报素材失败: {error}")
