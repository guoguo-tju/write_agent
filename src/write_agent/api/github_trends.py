"""
GitHub 趋势 API。
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from write_agent.observability import bind_entities, emit_obs_event, obs_scope
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
    enhance: bool = True


class AddWeekDigestRequest(BaseModel):
    week_key: str


class BuildItemRewriteRequest(BaseModel):
    week_key: str
    repo_full_name: str
    enhance: bool = True


@router.get("", response_model=GitHubTrendSnapshotResponse)
async def get_github_trends(week_key: Optional[str] = None):
    with obs_scope("API.GITHUB_TRENDS.GET", "HTTP_SYNC", entities={"week_key": week_key}):
        try:
            data = service.get_snapshot(week_key=week_key)
            emit_obs_event(
                level="INFO",
                message="api.github_trends.get",
                entities={"week_key": data.get("requested_week_key")},
            )
            return GitHubTrendSnapshotResponse(**data)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"获取趋势失败: {error}")


@router.get("/weeks", response_model=list[GitHubTrendWeekOption])
async def get_github_trend_weeks():
    with obs_scope("API.GITHUB_TRENDS.WEEKS", "HTTP_SYNC"):
        try:
            weeks = service.list_available_weeks()
            emit_obs_event(
                level="INFO",
                message="api.github_trends.weeks",
                payload={"total": len(weeks)},
            )
            return [GitHubTrendWeekOption(**item) for item in weeks]
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"获取周列表失败: {error}")


@router.post("/refresh", response_model=GitHubTrendSnapshotResponse)
async def refresh_github_trends():
    with obs_scope("API.GITHUB_TRENDS.REFRESH", "HTTP_SYNC"):
        try:
            await service.refresh_current_week_snapshot()
            data = service.get_snapshot(service.current_week_key())
            bind_entities({"week_key": data.get("week_key")})
            emit_obs_event(
                level="INFO",
                message="api.github_trends.refresh",
                entities={"week_key": data.get("week_key")},
            )
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
    with obs_scope(
        "API.GITHUB_TRENDS.ADD_ITEM",
        "HTTP_SYNC",
        entities={"week_key": request.week_key},
    ):
        try:
            result = service.add_item_to_materials(
                week_key=request.week_key,
                repo_full_name=request.repo_full_name,
                enhance=request.enhance,
            )
            bind_entities(
                {
                    "material_id": result.get("material_id"),
                    "week_key": request.week_key,
                }
            )
            emit_obs_event(
                level="INFO",
                message="api.github_trends.add_item",
                entities={
                    "material_id": result.get("material_id"),
                    "week_key": request.week_key,
                },
                payload={"repo_full_name": request.repo_full_name, "enhance": request.enhance},
            )
            return {"status": "ok", **result}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"加入素材库失败: {error}")


@router.post("/materials/add-week-digest")
async def add_week_digest_to_materials(request: AddWeekDigestRequest):
    with obs_scope(
        "API.GITHUB_TRENDS.ADD_WEEK_DIGEST",
        "HTTP_SYNC",
        entities={"week_key": request.week_key},
    ):
        try:
            result = service.add_week_digest_to_materials(week_key=request.week_key)
            bind_entities(
                {"material_id": result.get("material_id"), "week_key": request.week_key}
            )
            emit_obs_event(
                level="INFO",
                message="api.github_trends.add_week_digest",
                entities={"material_id": result.get("material_id"), "week_key": request.week_key},
            )
            return {"status": "ok", **result}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"加入周报素材失败: {error}")


@router.post("/rewrite/build-item")
async def build_item_rewrite_markdown(request: BuildItemRewriteRequest):
    with obs_scope(
        "API.GITHUB_TRENDS.BUILD_REWRITE",
        "HTTP_SYNC",
        entities={"week_key": request.week_key},
    ):
        try:
            result = service.build_item_rewrite_markdown(
                week_key=request.week_key,
                repo_full_name=request.repo_full_name,
                enhance=request.enhance,
            )
            emit_obs_event(
                level="INFO",
                message="api.github_trends.build_rewrite",
                entities={"week_key": request.week_key},
                payload={"repo_full_name": request.repo_full_name, "enhance": request.enhance},
            )
            return {"status": "ok", **result}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=f"构建改写内容失败: {error}")
