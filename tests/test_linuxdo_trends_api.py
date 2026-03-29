"""
Linux.do 趋势 API 回归测试。
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
from write_agent.services.linuxdo_trending_service import (
    RefreshCoolingDownError,
    RefreshInProgressError,
    RefreshRateLimitedError,
)


def test_get_linuxdo_trends_response_shape(monkeypatch) -> None:
    from write_agent.api import linuxdo_trends as linuxdo_trends_api

    monkeypatch.setattr(
        linuxdo_trends_api.service,
        "get_snapshot",
        lambda period_type="weekly", period_key=None, tag=None, limit=20: {
            "period_type": period_type,
            "period_key": "2026-W13",
            "requested_period_key": period_key or "2026-W13",
            "snapshot_date": "2026-03-28",
            "captured_at": "2026-03-28T09:10:00+08:00",
            "is_stale": False,
            "is_refreshing": False,
            "fetch_error": None,
            "available_tags": ["ai", "linux"],
            "items": [
                {
                    "rank": 1,
                    "topic_id": 9001,
                    "title": "AI 工作流实战",
                    "content": "摘要",
                    "author": "alice",
                    "tags": ["ai"],
                    "reply_count": 14,
                    "view_count": 2345,
                    "like_count": 88,
                    "publish_time": "2026-03-28T08:30:00+00:00",
                    "topic_url": "https://linux.do/t/ai-workflow/9001",
                }
            ],
        },
    )

    client = TestClient(app)
    resp = client.get("/api/linuxdo-trends", params={"period_type": "weekly"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["period_type"] == "weekly"
    assert data["items"][0]["topic_id"] == 9001


def test_get_linuxdo_periods(monkeypatch) -> None:
    from write_agent.api import linuxdo_trends as linuxdo_trends_api

    monkeypatch.setattr(
        linuxdo_trends_api.service,
        "list_periods",
        lambda period_type="weekly": [
            {
                "period_key": "2026-W13",
                "latest_snapshot_date": "2026-03-28",
                "latest_captured_at": "2026-03-28T09:10:00+08:00",
            }
        ],
    )

    client = TestClient(app)
    resp = client.get("/api/linuxdo-trends/periods", params={"period_type": "weekly"})
    assert resp.status_code == 200
    assert resp.json()[0]["period_key"] == "2026-W13"


def test_refresh_conflict_returns_409(monkeypatch) -> None:
    from write_agent.api import linuxdo_trends as linuxdo_trends_api

    async def fake_refresh(period_type: str = "weekly"):
        raise RefreshInProgressError("Linux.do 趋势更新中")

    monkeypatch.setattr(linuxdo_trends_api.service, "refresh_snapshot", fake_refresh)

    client = TestClient(app)
    resp = client.post("/api/linuxdo-trends/refresh", json={"period_type": "weekly"})
    assert resp.status_code == 409


def test_refresh_cooldown_returns_429(monkeypatch) -> None:
    from write_agent.api import linuxdo_trends as linuxdo_trends_api

    async def fake_refresh(period_type: str = "weekly"):
        raise RefreshCoolingDownError(15)

    monkeypatch.setattr(linuxdo_trends_api.service, "refresh_snapshot", fake_refresh)

    client = TestClient(app)
    resp = client.post("/api/linuxdo-trends/refresh", json={"period_type": "weekly"})
    assert resp.status_code == 429
    assert "15s" in resp.json().get("detail", "")
    assert resp.headers.get("Retry-After") == "15"


def test_refresh_rate_limited_returns_429(monkeypatch) -> None:
    from write_agent.api import linuxdo_trends as linuxdo_trends_api

    async def fake_refresh(period_type: str = "weekly"):
        raise RefreshRateLimitedError(8)

    monkeypatch.setattr(linuxdo_trends_api.service, "refresh_snapshot", fake_refresh)

    client = TestClient(app)
    resp = client.post("/api/linuxdo-trends/refresh", json={"period_type": "weekly"})
    assert resp.status_code == 429
    assert "8s" in resp.json().get("detail", "")
    assert resp.headers.get("Retry-After") == "8"


def test_get_topic_detail(monkeypatch) -> None:
    from write_agent.api import linuxdo_trends as linuxdo_trends_api

    monkeypatch.setattr(
        linuxdo_trends_api.service,
        "get_topic_detail",
        lambda topic_id: {
            "topic_id": topic_id,
            "title": "AI 工作流实战",
            "content": "正文",
            "author": "alice",
            "publish_time": "2026-03-28T08:30:00+00:00",
            "topic_url": "https://linux.do/t/ai-workflow/9001",
        },
    )

    client = TestClient(app)
    resp = client.get("/api/linuxdo-trends/topics/9001")
    assert resp.status_code == 200
    assert resp.json()["topic_id"] == 9001


def test_add_item_and_build_rewrite(monkeypatch) -> None:
    from write_agent.api import linuxdo_trends as linuxdo_trends_api

    monkeypatch.setattr(
        linuxdo_trends_api.service,
        "add_item_to_materials",
        lambda period_type, period_key, topic_id: {
            "material_id": 18,
            "created": True,
            "updated": False,
        },
    )
    monkeypatch.setattr(
        linuxdo_trends_api.service,
        "build_item_rewrite_markdown",
        lambda period_type, period_key, topic_id: {
            "title": "Linux.do 热帖 AI 工作流实战",
            "content": "prefill markdown",
        },
    )

    client = TestClient(app)
    add_resp = client.post(
        "/api/linuxdo-trends/materials/add-item",
        json={"period_type": "weekly", "period_key": "2026-W13", "topic_id": 9001},
    )
    assert add_resp.status_code == 200
    assert add_resp.json()["material_id"] == 18

    rewrite_resp = client.post(
        "/api/linuxdo-trends/rewrite/build-item",
        json={"period_type": "weekly", "period_key": "2026-W13", "topic_id": 9001},
    )
    assert rewrite_resp.status_code == 200
    assert "prefill" in rewrite_resp.json()["content"]
