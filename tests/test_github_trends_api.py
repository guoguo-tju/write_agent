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


def test_refresh_supports_daily_period_type(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    called = {}

    async def fake_refresh_snapshot(
        period_type: str = "weekly",
        *,
        period_key: str | None = None,
        retry_untranslated_only: bool = False,
    ):
        called["period_type"] = period_type
        called["period_key"] = period_key
        called["retry_untranslated_only"] = retry_untranslated_only

    monkeypatch.setattr(github_trends_api.service, "refresh_snapshot", fake_refresh_snapshot)
    monkeypatch.setattr(
        github_trends_api.service,
        "get_snapshot",
        lambda week_key=None, period_type="weekly", period_key=None: {
            "week_key": "2026-W12",
            "requested_week_key": week_key or "2026-W12",
            "period_type": period_type,
            "period_key": period_key or "2026-03-20",
            "snapshot_date": "2026-03-20",
            "captured_at": "2026-03-20T09:05:00+08:00",
            "is_weekly_archive": False,
            "is_stale": False,
            "is_refreshing": False,
            "fetch_error": None,
            "items": [],
        },
    )

    client = TestClient(app)
    resp = client.post("/api/github-trends/refresh", json={"period_type": "daily"})
    assert resp.status_code == 200
    assert called["period_type"] == "daily"
    assert called["period_key"] is None
    assert called["retry_untranslated_only"] is False
    assert resp.json()["period_type"] == "daily"


def test_refresh_supports_retry_untranslated_only(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    called = {}

    async def fake_refresh_snapshot(
        period_type: str = "weekly",
        *,
        period_key: str | None = None,
        retry_untranslated_only: bool = False,
    ):
        called["period_type"] = period_type
        called["period_key"] = period_key
        called["retry_untranslated_only"] = retry_untranslated_only

    monkeypatch.setattr(github_trends_api.service, "refresh_snapshot", fake_refresh_snapshot)
    monkeypatch.setattr(
        github_trends_api.service,
        "get_snapshot",
        lambda week_key=None, period_type="weekly", period_key=None: {
            "week_key": "2026-W15",
            "requested_week_key": week_key or "2026-W15",
            "period_type": period_type,
            "period_key": period_key or "2026-W15",
            "snapshot_date": "2026-04-07",
            "captured_at": "2026-04-07T09:05:00+08:00",
            "is_weekly_archive": False,
            "is_stale": False,
            "is_refreshing": False,
            "fetch_error": None,
            "items": [],
        },
    )

    client = TestClient(app)
    resp = client.post(
        "/api/github-trends/refresh",
        json={
            "period_type": "weekly",
            "period_key": "2026-W15",
            "retry_untranslated_only": True,
        },
    )
    assert resp.status_code == 200
    assert called == {
        "period_type": "weekly",
        "period_key": "2026-W15",
        "retry_untranslated_only": True,
    }


def test_get_trends_response_shape(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    monkeypatch.setattr(
        github_trends_api.service,
        "get_snapshot",
        lambda week_key=None, period_type="weekly", period_key=None: {
            "week_key": "2026-W12",
            "requested_week_key": week_key or "2026-W12",
            "period_type": period_type,
            "period_key": period_key or "2026-W12",
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


def test_get_trends_supports_daily_params(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    called = {}

    monkeypatch.setattr(
        github_trends_api.service,
        "get_snapshot",
        lambda week_key=None, period_type="weekly", period_key=None: called.update(
            {
                "week_key": week_key,
                "period_type": period_type,
                "period_key": period_key,
            }
        )
        or {
            "week_key": "2026-W14",
            "requested_week_key": "2026-W14",
            "period_type": period_type,
            "period_key": period_key or "2026-03-30",
            "snapshot_date": "2026-03-30",
            "captured_at": "2026-03-30T09:05:00+08:00",
            "is_weekly_archive": False,
            "is_stale": False,
            "is_refreshing": False,
            "fetch_error": None,
            "items": [],
        },
    )

    client = TestClient(app)
    resp = client.get(
        "/api/github-trends",
        params={"period_type": "daily", "period_key": "2026-03-30"},
    )
    assert resp.status_code == 200
    assert resp.json()["period_type"] == "daily"
    assert called["period_type"] == "daily"
    assert called["period_key"] == "2026-03-30"


def test_get_github_trend_periods_daily(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    monkeypatch.setattr(
        github_trends_api.service,
        "list_available_periods",
        lambda period_type, limit=12: [
            {
                "period_type": period_type,
                "period_key": "2026-03-30",
                "latest_snapshot_date": "2026-03-30",
                "latest_captured_at": "2026-03-30T09:05:00+08:00",
                "has_archive": False,
            }
        ],
    )

    client = TestClient(app)
    resp = client.get("/api/github-trends/periods", params={"period_type": "daily"})
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["period_type"] == "daily"
    assert data[0]["period_key"] == "2026-03-30"


def test_add_item_materials_supports_enhance_flag(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    called = {}

    def fake_add_item_to_materials(
        week_key: str | None = None,
        repo_full_name: str = "",
        enhance: bool = True,
        *,
        period_type: str = "weekly",
        period_key: str | None = None,
    ):
        called["week_key"] = week_key
        called["repo_full_name"] = repo_full_name
        called["enhance"] = enhance
        called["period_type"] = period_type
        called["period_key"] = period_key
        return {
            "material_id": 7,
            "created": False,
            "updated": True,
            "period_type": period_type,
            "period_key": period_key or week_key or "",
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
        "period_type": "weekly",
        "period_key": None,
    }


def test_add_item_materials_supports_daily_period(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    called = {}

    def fake_add_item_to_materials(
        week_key=None,
        repo_full_name: str = "",
        enhance: bool = True,
        *,
        period_type: str = "weekly",
        period_key=None,
    ):
        called["week_key"] = week_key
        called["repo_full_name"] = repo_full_name
        called["enhance"] = enhance
        called["period_type"] = period_type
        called["period_key"] = period_key
        return {
            "material_id": 11,
            "created": True,
            "updated": False,
            "period_type": period_type,
            "period_key": period_key or "2026-03-30",
            "enrich": {
                "attempted": False,
                "cache_hit": False,
                "degraded": False,
                "degrade_reason": "",
                "duration_ms": 0,
                "fetched_at": "",
                "sources": [],
            },
        }

    monkeypatch.setattr(github_trends_api.service, "add_item_to_materials", fake_add_item_to_materials)

    client = TestClient(app)
    resp = client.post(
        "/api/github-trends/materials/add-item",
        json={
            "period_type": "daily",
            "period_key": "2026-03-30",
            "repo_full_name": "owner/repo",
            "enhance": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["material_id"] == 11
    assert called["period_type"] == "daily"
    assert called["period_key"] == "2026-03-30"


def test_build_item_rewrite_endpoint(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    called = {}

    def fake_build_item_rewrite_markdown(
        week_key: str | None = None,
        repo_full_name: str = "",
        enhance: bool = True,
        *,
        period_type: str = "weekly",
        period_key: str | None = None,
    ):
        called["week_key"] = week_key
        called["repo_full_name"] = repo_full_name
        called["enhance"] = enhance
        called["period_type"] = period_type
        called["period_key"] = period_key
        return {
            "title": "owner/repo（2026-W12）",
            "content": "prefill markdown",
            "period_type": period_type,
            "period_key": period_key or week_key or "",
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
        "period_type": "weekly",
        "period_key": None,
    }


def test_build_item_rewrite_supports_daily_period(monkeypatch) -> None:
    from write_agent.api import github_trends as github_trends_api

    called = {}

    def fake_build_item_rewrite_markdown(
        week_key=None,
        repo_full_name: str = "",
        enhance: bool = True,
        *,
        period_type: str = "weekly",
        period_key=None,
    ):
        called["week_key"] = week_key
        called["repo_full_name"] = repo_full_name
        called["enhance"] = enhance
        called["period_type"] = period_type
        called["period_key"] = period_key
        return {
            "title": "owner/repo（日榜 2026-03-30）",
            "content": "prefill markdown daily",
            "period_type": period_type,
            "period_key": period_key or "2026-03-30",
            "enrich": {
                "attempted": False,
                "cache_hit": False,
                "degraded": False,
                "degrade_reason": "",
                "duration_ms": 0,
                "fetched_at": "",
                "sources": [],
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
            "period_type": "daily",
            "period_key": "2026-03-30",
            "repo_full_name": "owner/repo",
            "enhance": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["title"] == "owner/repo（日榜 2026-03-30）"
    assert called["period_type"] == "daily"
    assert called["period_key"] == "2026-03-30"
