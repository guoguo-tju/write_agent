"""
小红书热点 API 回归测试。
"""
from __future__ import annotations

import json
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


def _decode_sse(raw_lines: list[str]) -> list[dict]:
    events: list[dict] = []
    for line in raw_lines:
        if not line or not line.startswith("data: "):
            continue
        events.append(json.loads(line[6:]))
    return events


def test_get_categories_response_shape(monkeypatch) -> None:
    from write_agent.api import xhs_trends as xhs_trends_api

    monkeypatch.setattr(
        xhs_trends_api.service,
        "list_categories",
        lambda: [
            {"key": "tech", "name": "科技", "name_en": "Tech"},
            {"key": "workplace", "name": "职场", "name_en": "Workplace"},
        ],
    )

    client = TestClient(app)
    resp = client.get("/api/xhs-trends/categories")
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 2
    assert payload[0]["key"] == "tech"


def test_get_trends_response_shape(monkeypatch) -> None:
    from write_agent.api import xhs_trends as xhs_trends_api

    monkeypatch.setattr(
        xhs_trends_api.service,
        "get_trends",
        lambda category_key, sort="hot", limit=10: {
            "category_key": category_key,
            "category_name": "科技",
            "category_name_en": "Tech",
            "sort": sort,
            "lookback_days": 7,
            "min_interactions": 100,
            "updated_at": "2026-03-23T10:00:00+08:00",
            "fetch_error": None,
            "is_stale": False,
            "items": [
                {
                    "id": "n1",
                    "title": "科技热点",
                    "content": "热点正文摘要",
                    "content_type": "video",
                    "like_count": 200,
                    "favorite_count": 50,
                    "comment_count": 20,
                    "publish_time": "2026-03-22T08:00:00+08:00",
                    "source_url": "https://example.com/1",
                    "hot_score": 250.0,
                    "interactions": 270,
                }
            ],
        },
    )

    client = TestClient(app)
    resp = client.get("/api/xhs-trends", params={"category_key": "tech", "sort": "hot", "limit": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["category_key"] == "tech"
    assert len(data["items"]) == 1
    assert data["items"][0]["hot_score"] == 250.0
    assert data["items"][0]["content"] == "热点正文摘要"


def test_refresh_endpoint(monkeypatch) -> None:
    from write_agent.api import xhs_trends as xhs_trends_api

    monkeypatch.setattr(
        xhs_trends_api.service,
        "refresh",
        lambda category_key=None: {
            "updated_at": "2026-03-23T10:00:00+08:00",
            "refreshed_categories": ["tech"],
            "errors": {},
        },
    )
    monkeypatch.setattr(xhs_trends_api.service, "is_refresh_in_progress", lambda category_key=None: False)

    client = TestClient(app)
    resp = client.post("/api/xhs-trends/refresh", json={"category_key": "tech"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["refreshed_categories"] == ["tech"]


def test_refresh_endpoint_background_mode(monkeypatch) -> None:
    from write_agent.api import xhs_trends as xhs_trends_api

    called = {"count": 0}
    called_keys: list[str | None] = []

    def _fake_refresh(category_key=None):
        called["count"] += 1
        called_keys.append(category_key)
        return {
            "updated_at": "2026-03-23T10:00:00+08:00",
            "refreshed_categories": ["tech"],
            "errors": {},
        }

    monkeypatch.setattr(xhs_trends_api.service, "refresh", _fake_refresh)
    monkeypatch.setattr(xhs_trends_api.service, "is_refresh_in_progress", lambda category_key=None: False)
    monkeypatch.setattr(xhs_trends_api.service, "get_default_category_key", lambda: "tech")
    monkeypatch.setattr(
        xhs_trends_api.service,
        "get_cache_updated_at",
        lambda: "2026-03-23T10:00:00+08:00",
    )

    client = TestClient(app)
    resp = client.post("/api/xhs-trends/refresh", json={"background": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["refreshed_categories"] == []
    assert data["errors"] == {}
    assert called["count"] >= 1
    assert called_keys and called_keys[0] == "tech"


def test_refresh_endpoint_background_in_progress(monkeypatch) -> None:
    from write_agent.api import xhs_trends as xhs_trends_api

    monkeypatch.setattr(xhs_trends_api.service, "get_default_category_key", lambda: "tech")
    monkeypatch.setattr(xhs_trends_api.service, "is_refresh_in_progress", lambda category_key=None: True)
    monkeypatch.setattr(
        xhs_trends_api.service,
        "get_cache_updated_at",
        lambda: "2026-03-23T10:00:00+08:00",
    )

    client = TestClient(app)
    resp = client.post("/api/xhs-trends/refresh", json={"background": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "in_progress"
    assert "tech" in data["errors"]


def test_refresh_status_endpoint(monkeypatch) -> None:
    from write_agent.api import xhs_trends as xhs_trends_api

    monkeypatch.setattr(
        xhs_trends_api.service,
        "get_refresh_status",
        lambda category_key=None: {
            "category_key": category_key or "tech",
            "category_name": "科技",
            "category_name_en": "Tech",
            "updated_at": "2026-03-23T10:00:00+08:00",
            "fetch_error": None,
            "refresh_in_progress": False,
            "busy_categories": [],
            "refresh_lock": {"category_key": "tech", "pid": 1234, "locked_at": "2026-03-23T10:00:00+08:00"},
            "recent_enrich": {
                "ttl_seconds": 1800,
                "last_enriched_at": "2026-03-23T09:30:00+08:00",
                "next_eligible_at": "2026-03-23T10:00:00+08:00",
                "enriched_item_count": 1,
                "recent_item_count": 1,
                "is_recent": True,
            },
        },
    )

    client = TestClient(app)
    resp = client.get("/api/xhs-trends/refresh/status", params={"category_key": "tech"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["category_key"] == "tech"
    assert data["refresh_in_progress"] is False
    assert data["recent_enrich"]["is_recent"] is True


def test_analysis_stream_events_include_obs(monkeypatch) -> None:
    from write_agent.api import xhs_trends as xhs_trends_api

    monkeypatch.setattr(
        xhs_trends_api.service,
        "get_trends",
        lambda category_key, sort="hot", limit=10: {
            "category_key": category_key,
            "category_name": "科技",
            "category_name_en": "Tech",
            "sort": sort,
            "lookback_days": 7,
            "min_interactions": 100,
            "updated_at": "2026-03-23T10:00:00+08:00",
            "fetch_error": None,
            "is_stale": False,
            "items": [
                {
                    "id": "n1",
                    "title": "科技热点",
                    "content_type": "video",
                    "like_count": 200,
                    "favorite_count": 50,
                    "comment_count": 20,
                    "publish_time": "2026-03-22T08:00:00+08:00",
                    "source_url": "https://example.com/1",
                    "hot_score": 250.0,
                    "interactions": 270,
                }
            ],
        },
    )
    monkeypatch.setattr(
        xhs_trends_api.service,
        "build_analysis",
        lambda category_key: {
            "category_key": category_key,
            "category_name": "科技",
            "generated_at": "2026-03-23T10:10:00+08:00",
            "reason_points": ["点1", "点2", "点3"],
            "comment_topics": [
                {"topic": "实操步骤", "ratio": "45%", "sample_comment": "求步骤"},
                {"topic": "成本门槛", "ratio": "30%", "sample_comment": "成本如何"},
                {"topic": "避坑建议", "ratio": "25%", "sample_comment": "有哪些坑"},
            ],
            "inspiration_cards": [
                {
                    "topic": "选题A",
                    "content_type": "video",
                    "title_hook": "3分钟讲清选题A",
                    "rationale": "互动高",
                },
                {
                    "topic": "选题B",
                    "content_type": "image_text",
                    "title_hook": "一篇讲透选题B",
                    "rationale": "收藏高",
                },
                {
                    "topic": "选题C",
                    "content_type": "video",
                    "title_hook": "手把手拆解选题C",
                    "rationale": "评论高",
                },
            ],
        },
    )

    client = TestClient(app)
    with client.stream("GET", "/api/xhs-trends/analysis/stream", params={"category_key": "tech"}) as resp:
        assert resp.status_code == 200
        lines = [line for line in resp.iter_lines() if line and line.startswith("data: ")]

    events = _decode_sse(lines)
    assert len(events) >= 4
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "done"
    for event in events:
        obs = event.get("obs")
        assert isinstance(obs, dict)
        assert obs.get("trace_id")
        assert obs.get("node_id")
        assert obs.get("behavior_id")
        assert obs.get("event_id")
        assert obs.get("ts")


def test_invalid_category_returns_400_with_trace_fields(monkeypatch) -> None:
    from write_agent.api import xhs_trends as xhs_trends_api

    def _raise_invalid(*args, **kwargs):
        raise ValueError("未找到分类: unknown")

    monkeypatch.setattr(xhs_trends_api.service, "get_trends", _raise_invalid)

    client = TestClient(app)
    resp = client.get("/api/xhs-trends", params={"category_key": "unknown"})
    assert resp.status_code == 400
    data = resp.json()
    assert data["detail"] == "未找到分类: unknown"
    assert data["trace_id"]
    assert data["request_id"]
