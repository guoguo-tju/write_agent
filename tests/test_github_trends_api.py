"""
GitHub 趋势 API 回归测试。
"""
from __future__ import annotations

import os
import sys

venv_path = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    ".venv",
    "lib",
    "python3.10",
    "site-packages",
)
if os.path.exists(venv_path):
    sys.path.insert(0, venv_path)

src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
sys.path.insert(0, src_path)

from fastapi.testclient import TestClient

from write_agent.main import app
from write_agent.services.github_trending_service import RefreshInProgressError


def test_refresh_conflict_returns_409(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    async def fake_refresh():
        raise RefreshInProgressError("GitHub 趋势更新中")

    monkeypatch.setattr(github_trends_api.service, "refresh_current_week_snapshot", fake_refresh)

    client = TestClient(app)
    resp = client.post("/api/github-trends/refresh")
    assert resp.status_code == 409
    assert "更新中" in resp.json()["detail"]


def test_get_trends_response_shape(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    monkeypatch.setattr(
        github_trends_api.service,
        "get_snapshot",
        lambda week_key=None: {
            "week_key": "2026-W12",
            "requested_week_key": week_key or "2026-W12",
            "snapshot_date": "2026-03-20",
            "captured_at": "2026-03-20T09:05:00+08:00",
            "is_weekly_archive": False,
            "is_stale": False,
            "is_refreshing": False,
            "fetch_error": None,
            "items": [
                {
                    "rank": 1,
                    "repo_full_name": "owner/repo",
                    "repo_name": "repo",
                    "owner": "owner",
                    "description": "desc",
                    "description_zh": "中文简介",
                    "repo_url": "https://github.com/owner/repo",
                    "stars_this_week": 1234,
                    "language": "Python",
                    "total_stars": 9999,
                }
            ],
        },
    )

    client = TestClient(app)
    resp = client.get("/api/github-trends", params={"week_key": "2026-W12"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["week_key"] == "2026-W12"
    assert data["requested_week_key"] == "2026-W12"
    assert len(data["items"]) == 1
    assert data["items"][0]["repo_full_name"] == "owner/repo"
    assert data["items"][0]["description_zh"] == "中文简介"


def test_add_item_materials_supports_enhance_flag(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    called = {}

    def fake_add_item_to_materials(week_key: str, repo_full_name: str, enhance: bool = True):
        called["week_key"] = week_key
        called["repo_full_name"] = repo_full_name
        called["enhance"] = enhance
        return {
            "material_id": 7,
            "created": False,
            "updated": True,
            "enrich": {
                "attempted": True,
                "cache_hit": False,
                "degraded": True,
                "degrade_reason": "missing_github_token",
                "duration_ms": 3,
                "fetched_at": "",
                "sources": [],
            },
        }

    monkeypatch.setattr(github_trends_api.service, "add_item_to_materials", fake_add_item_to_materials)

    client = TestClient(app)
    resp = client.post(
        "/api/github-trends/materials/add-item",
        json={
            "week_key": "2026-W12",
            "repo_full_name": "owner/repo",
            "enhance": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["material_id"] == 7
    assert data["updated"] is True
    assert data["enrich"]["degraded"] is True
    assert called == {
        "week_key": "2026-W12",
        "repo_full_name": "owner/repo",
        "enhance": False,
    }


def test_build_item_rewrite_endpoint(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    called = {}

    def fake_build_item_rewrite_markdown(
        week_key: str,
        repo_full_name: str,
        enhance: bool = True,
    ):
        called["week_key"] = week_key
        called["repo_full_name"] = repo_full_name
        called["enhance"] = enhance
        return {
            "title": "owner/repo（2026-W12）",
            "content": "prefill markdown",
            "enrich": {
                "attempted": True,
                "cache_hit": True,
                "degraded": False,
                "degrade_reason": "",
                "duration_ms": 2,
                "fetched_at": "2026-03-22T09:00:00+08:00",
                "sources": ["github_api", "readme"],
            },
        }

    monkeypatch.setattr(
        github_trends_api.service,
        "build_item_rewrite_markdown",
        fake_build_item_rewrite_markdown,
    )

    client = TestClient(app)
    resp = client.post(
        "/api/github-trends/rewrite/build-item",
        json={
            "week_key": "2026-W12",
            "repo_full_name": "owner/repo",
            "enhance": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["title"] == "owner/repo（2026-W12）"
    assert data["content"] == "prefill markdown"
    assert data["enrich"]["cache_hit"] is True
    assert called == {
        "week_key": "2026-W12",
        "repo_full_name": "owner/repo",
        "enhance": True,
    }
