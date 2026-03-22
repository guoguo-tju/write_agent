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
