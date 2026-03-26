"""
小红书热点服务测试。
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timedelta
from requests import Response
import pytest

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

from write_agent.services import xhs_trends_service as xhs_service_module
from write_agent.services.xhs_trends_service import RefreshInProgressError, XhsTrendsService


def _create_service(tmp_path) -> XhsTrendsService:
    categories_file = tmp_path / "xhs_categories.json"
    categories_file.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "key": "tech",
                        "name": "科技",
                        "name_en": "Tech",
                        "keywords": ["AI", "编程"],
                    },
                    {
                        "key": "workplace",
                        "name": "职场",
                        "name_en": "Workplace",
                        "keywords": ["职场", "面试"],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cache_file = tmp_path / "xhs_cache.json"
    service = XhsTrendsService(
        categories_file=str(categories_file),
        cache_file=str(cache_file),
    )
    # 固定关键阈值，避免受本地 .env 漂移影响测试结果。
    service.lookback_days = 7
    service.min_interactions = 100
    service.comment_detail_limit = 12
    service.max_keywords_per_category = 5
    return service


def _set_http_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        xhs_service_module.settings,
        "xhs_trends_provider",
        "http_api",
        raising=False,
    )
    monkeypatch.setattr(
        xhs_service_module.settings,
        "xhs_trends_api_base_url",
        "https://demo-provider.local",
        raising=False,
    )


def _set_algovate_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        xhs_service_module.settings,
        "xhs_trends_provider",
        "algovate_mcp",
        raising=False,
    )
    monkeypatch.setattr(
        xhs_service_module.settings,
        "xhs_mcp_url",
        "http://127.0.0.1:3000/mcp",
        raising=False,
    )


def test_summarize_note_content_rules(tmp_path) -> None:
    service = _create_service(tmp_path)
    short_text = "这是短正文"
    assert service._summarize_note_content(short_text, fallback_title="标题") == short_text

    long_text = "这是一段较长的热点正文。"
    long_text = long_text * 80
    summarized = service._summarize_note_content(long_text, fallback_title="标题")
    assert len(summarized) <= 501
    assert summarized.endswith("…")

    assert service._summarize_note_content("", fallback_title="兜底标题") == "兜底标题"


def test_refresh_and_hot_sort_filters_items(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_http_provider(monkeypatch)
    now = datetime.now(service.timezone)

    sample_items = [
        {
            "id": "n1",
            "title": "科技选题A",
            "content": "这是科技选题A的原文内容，字数较短。",
            "content_type": "video",
            "like_count": 200,
            "favorite_count": 100,
            "comment_count": 50,
            "publish_time": (now - timedelta(days=1)).isoformat(),
            "source_url": "https://example.com/1",
        },
        {
            "id": "n2",
            "title": "科技选题B",
            "content_type": "image_text",
            "like_count": 180,
            "favorite_count": 20,
            "comment_count": 10,
            "publish_time": (now - timedelta(days=2)).isoformat(),
            "source_url": "https://example.com/2",
        },
        {
            "id": "n3",
            "title": "低互动样本",
            "content_type": "video",
            "like_count": 50,
            "favorite_count": 20,
            "comment_count": 10,
            "publish_time": (now - timedelta(days=1)).isoformat(),
            "source_url": "https://example.com/3",
        },
        {
            "id": "n4",
            "title": "超时窗样本",
            "content_type": "video",
            "like_count": 500,
            "favorite_count": 50,
            "comment_count": 30,
            "publish_time": (now - timedelta(days=10)).isoformat(),
            "source_url": "https://example.com/4",
        },
    ]

    monkeypatch.setattr(service, "_fetch_category_items", lambda category_key: sample_items)

    refreshed = service.refresh("tech")
    assert refreshed["refreshed_categories"] == ["tech"]
    assert refreshed["errors"] == {}

    payload = service.get_trends("tech", sort="hot", limit=10)
    assert payload["category_key"] == "tech"
    assert payload["sort"] == "hot"
    assert len(payload["items"]) == 2
    assert payload["items"][0]["title"] == "科技选题A"
    assert payload["items"][0]["hot_score"] == 305.0
    assert payload["items"][0]["content"] == "这是科技选题A的原文内容，字数较短。"
    assert payload["items"][1]["hot_score"] == 201.0
    assert payload["items"][1]["content"] == "科技选题B"


def test_latest_sort_uses_publish_time_desc(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_http_provider(monkeypatch)
    now = datetime.now(service.timezone)

    sample_items = [
        {
            "id": "n1",
            "title": "较旧但更热",
            "content_type": "video",
            "like_count": 600,
            "favorite_count": 100,
            "comment_count": 60,
            "publish_time": (now - timedelta(days=3)).isoformat(),
            "source_url": "https://example.com/1",
        },
        {
            "id": "n2",
            "title": "较新",
            "content_type": "image_text",
            "like_count": 140,
            "favorite_count": 30,
            "comment_count": 20,
            "publish_time": (now - timedelta(hours=6)).isoformat(),
            "source_url": "https://example.com/2",
        },
    ]

    monkeypatch.setattr(service, "_fetch_category_items", lambda category_key: sample_items)
    service.refresh("tech")

    payload = service.get_trends("tech", sort="latest", limit=10)
    assert len(payload["items"]) == 2
    assert payload["items"][0]["title"] == "较新"
    assert payload["items"][1]["title"] == "较旧但更热"


def test_build_analysis_returns_required_shape(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_http_provider(monkeypatch)
    now = datetime.now(service.timezone)

    sample_items = [
        {
            "id": "n1",
            "title": "AI 工具提高效率",
            "content_type": "video",
            "like_count": 220,
            "favorite_count": 80,
            "comment_count": 40,
            "publish_time": (now - timedelta(days=1)).isoformat(),
            "source_url": "https://example.com/1",
            "top_comments": ["求详细步骤", "这个成本高吗？"],
        },
        {
            "id": "n2",
            "title": "职场沟通技巧模板",
            "content_type": "image_text",
            "like_count": 180,
            "favorite_count": 60,
            "comment_count": 30,
            "publish_time": (now - timedelta(days=2)).isoformat(),
            "source_url": "https://example.com/2",
            "top_comments": ["有没有避坑建议"],
        },
        {
            "id": "n3",
            "title": "复盘框架直接套用",
            "content_type": "video",
            "like_count": 160,
            "favorite_count": 40,
            "comment_count": 20,
            "publish_time": (now - timedelta(days=2)).isoformat(),
            "source_url": "https://example.com/3",
            "top_comments": ["能给个模板吗"],
        },
    ]

    monkeypatch.setattr(service, "_fetch_category_items", lambda category_key: sample_items)
    monkeypatch.setattr(service, "_try_llm_analysis", lambda **kwargs: None)

    service.refresh("tech")
    analysis = service.build_analysis("tech")

    assert analysis["category_key"] == "tech"
    assert len(analysis["reason_points"]) == 3
    assert len(analysis["comment_topics"]) == 3
    assert len(analysis["inspiration_cards"]) == 3
    assert all(len(item) <= 40 for item in analysis["reason_points"])
    assert all("topic" in topic and "ratio" in topic for topic in analysis["comment_topics"])
    assert all(
        "topic" in card and "content_type" in card and "title_hook" in card
        for card in analysis["inspiration_cards"]
    )


def test_refresh_without_base_url_falls_back_to_cache(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    monkeypatch.setattr(
        xhs_service_module.settings,
        "xhs_trends_provider",
        "http_api",
        raising=False,
    )
    monkeypatch.setattr(
        xhs_service_module.settings,
        "xhs_trends_api_base_url",
        "",
        raising=False,
    )
    now = datetime.now(service.timezone)
    cache_payload = {
        "updated_at": now.isoformat(),
        "categories": {
            "tech": {
                "updated_at": now.isoformat(),
                "fetch_error": "old error",
                "items": [
                    {
                        "id": "demo-1",
                        "title": "缓存样本",
                        "content_type": "video",
                        "like_count": 120,
                        "favorite_count": 30,
                        "comment_count": 10,
                        "publish_time": now.isoformat(),
                        "source_url": "https://example.com/1",
                        "hot_score": 149.0,
                        "interactions": 160,
                        "top_comments": [],
                    }
                ],
            }
        },
    }
    service.cache_file.write_text(json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8")

    result = service.refresh("tech")
    assert "tech" in result["errors"]
    assert result["errors"]["tech"].startswith("E_XHS_BASE_URL_MISSING")
    assert result["refreshed_categories"] == []

    payload = service.get_trends("tech", sort="hot", limit=10)
    assert len(payload["items"]) == 1
    assert payload["fetch_error"] == result["errors"]["tech"]


def test_algovate_mcp_refresh_aggregates_keywords_and_enriches_comments(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_algovate_provider(monkeypatch)
    now = datetime.now(service.timezone)

    detail_calls = {"count": 0}

    def _fake_mcp(tool_name: str, arguments: dict) -> dict:
        if tool_name == "xhs_auth_status":
            return {"success": True, "status": "logged_in", "loggedIn": True}
        if tool_name == "xhs_search_note":
            keyword = arguments["keyword"]
            if keyword == "AI":
                return {
                    "success": True,
                    "feeds": [
                        {
                            "id": "note-a",
                            "title": "AI 选题模板",
                            "time": int((now - timedelta(hours=2)).timestamp() * 1000),
                            "xsecToken": "tok-a",
                            "interact_info": {
                                "liked_count": "220",
                                "collected_count": "80",
                                "comment_count": "36",
                            },
                            "type": "video",
                        }
                    ],
                }
            return {
                "success": True,
                "feeds": [
                    {
                        "id": "note-a",
                        "title": "AI 选题模板",
                        "time": int((now - timedelta(hours=2)).timestamp() * 1000),
                        "xsecToken": "tok-a",
                        "interact_info": {
                            "liked_count": "220",
                            "collected_count": "80",
                            "comment_count": "36",
                        },
                        "type": "video",
                    },
                    {
                        "id": "note-b",
                        "title": "编程副业实战",
                        "time": int((now - timedelta(hours=6)).timestamp() * 1000),
                        "xsecToken": "tok-b",
                        "interact_info": {
                            "liked_count": "180",
                            "collected_count": "55",
                            "comment_count": "20",
                        },
                        "type": "image_text",
                    },
                ],
            }
        if tool_name == "xhs_get_note_detail":
            detail_calls["count"] += 1
            if arguments["feed_id"] == "note-a":
                return {"data": {"comments": {"list": [{"content": "求完整步骤"}, {"content": "成本多少"}]}}}
            return {"data": {"comments": {"list": [{"content": "能给模板吗"}]}}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr(service, "_mcp_call_tool", _fake_mcp)

    refreshed = service.refresh("tech")
    assert refreshed["errors"] == {}
    assert refreshed["refreshed_categories"] == ["tech"]
    assert detail_calls["count"] == 0

    payload = service.get_trends("tech", sort="hot", limit=10)
    assert len(payload["items"]) == 2
    assert payload["items"][0]["id"] == "note-a"

    service.enrich_comments_for_categories(["tech"])
    assert detail_calls["count"] >= 1

    cache = service._read_cache()
    cached_items = cache["categories"]["tech"]["items"]
    top_comments = [row.get("top_comments") for row in cached_items if row.get("id") == "note-a"][0]
    assert top_comments == ["求完整步骤", "成本多少"]


def test_algovate_mcp_refresh_supports_corner_tag_relative_publish_time(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_algovate_provider(monkeypatch)

    def _fake_mcp(tool_name: str, arguments: dict) -> dict:
        if tool_name == "xhs_auth_status":
            return {"success": True, "status": "logged_in", "loggedIn": True}
        if tool_name == "xhs_search_note":
            return {
                "success": True,
                "feeds": [
                    {
                        "id": "note-relative",
                        "xsecToken": "tok-relative",
                        "noteCard": {
                            "displayTitle": "相对时间发布时间兼容",
                            "type": "video",
                            "interactInfo": {
                                "likedCount": "320",
                                "collectedCount": "90",
                                "commentCount": "28",
                            },
                            "cornerTagInfo": [{"type": "publish_time", "text": "昨天 17:21"}],
                        },
                    }
                ],
            }
        if tool_name == "xhs_get_note_detail":
            return {"data": {"comments": {"list": []}}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr(service, "_mcp_call_tool", _fake_mcp)

    refreshed = service.refresh("tech")
    assert refreshed["errors"] == {}
    assert refreshed["refreshed_categories"] == ["tech"]

    payload = service.get_trends("tech", sort="hot", limit=10)
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "note-relative"


def test_refresh_rejects_concurrent_calls(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_http_provider(monkeypatch)
    now = datetime.now(service.timezone)
    started = threading.Event()
    released = threading.Event()

    def _slow_fetch(category_key: str) -> list[dict]:
        started.set()
        released.wait(timeout=2)
        return [
            {
                "id": "n1",
                "title": "慢请求样本",
                "content_type": "video",
                "like_count": 180,
                "favorite_count": 30,
                "comment_count": 15,
                "publish_time": now.isoformat(),
                "source_url": "https://example.com/1",
            }
        ]

    monkeypatch.setattr(service, "_fetch_category_items", _slow_fetch)

    def _run_first():
        service.refresh("tech")

    thread = threading.Thread(target=_run_first, daemon=True)
    thread.start()
    assert started.wait(timeout=1)

    with pytest.raises(RefreshInProgressError):
        service.refresh("tech")

    released.set()
    thread.join(timeout=2)


def test_refresh_rejects_cross_process_calls(monkeypatch, tmp_path) -> None:
    service_a = _create_service(tmp_path)
    service_b = _create_service(tmp_path)
    _set_http_provider(monkeypatch)
    now = datetime.now(service_a.timezone)
    started = threading.Event()
    released = threading.Event()

    def _slow_fetch(category_key: str) -> list[dict]:
        started.set()
        released.wait(timeout=2)
        return [
            {
                "id": "n1",
                "title": "慢请求样本",
                "content_type": "video",
                "like_count": 180,
                "favorite_count": 30,
                "comment_count": 15,
                "publish_time": now.isoformat(),
                "source_url": "https://example.com/1",
            }
        ]

    monkeypatch.setattr(service_a, "_fetch_category_items", _slow_fetch)
    monkeypatch.setattr(service_b, "_fetch_category_items", lambda category_key: [])

    thread = threading.Thread(target=lambda: service_a.refresh("tech"), daemon=True)
    thread.start()
    assert started.wait(timeout=1)

    with pytest.raises(RefreshInProgressError):
        service_b.refresh("tech")

    released.set()
    thread.join(timeout=2)


def test_enrich_comments_retries_on_rate_limit(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_algovate_provider(monkeypatch)
    now = datetime.now(service.timezone)
    detail_calls = {"count": 0}
    sleep_calls: list[float] = []
    service.mcp_detail_retries = 1
    service.mcp_detail_interval_seconds = 0.2
    service.mcp_detail_retry_backoff_seconds = 0.5

    def _fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr(xhs_service_module.time, "sleep", _fake_sleep)

    def _fake_mcp(tool_name: str, arguments: dict) -> dict:
        if tool_name == "xhs_auth_status":
            return {"success": True, "status": "logged_in", "loggedIn": True}
        if tool_name == "xhs_search_note":
            return {
                "success": True,
                "feeds": [
                    {
                        "id": "note-a",
                        "title": "AI 热点",
                        "time": int((now - timedelta(hours=1)).timestamp() * 1000),
                        "xsecToken": "tok-a",
                        "interact_info": {
                            "liked_count": "220",
                            "collected_count": "80",
                            "comment_count": "36",
                        },
                        "type": "video",
                    }
                ],
            }
        if tool_name == "xhs_get_note_detail":
            detail_calls["count"] += 1
            if detail_calls["count"] == 1:
                raise ValueError("429 limited")
            return {"data": {"comments": {"list": [{"content": "重试后拿到评论"}]}}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr(service, "_mcp_call_tool", _fake_mcp)

    refreshed = service.refresh("tech")
    assert refreshed["refreshed_categories"] == ["tech"]
    service.enrich_comments_for_categories(["tech"])

    cache = service._read_cache()
    items = cache["categories"]["tech"]["items"]
    assert [row.get("top_comments") for row in items if row.get("id") == "note-a"][0] == ["重试后拿到评论"]
    assert detail_calls["count"] == 2
    assert 0.5 in sleep_calls


def test_enrich_comments_uses_ttl_to_skip_recent_notes(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_algovate_provider(monkeypatch)
    service.comment_enrichment_ttl_seconds = 3600
    now = datetime.now(service.timezone)
    cache_payload = {
        "updated_at": now.isoformat(),
        "categories": {
            "tech": {
                "updated_at": now.isoformat(),
                "fetch_error": None,
                "items": [
                    {
                        "id": "note-a",
                        "title": "AI 选题模板",
                        "content_type": "video",
                        "like_count": 220,
                        "favorite_count": 80,
                        "comment_count": 36,
                        "publish_time": now.isoformat(),
                        "source_url": "https://example.com/1",
                        "hot_score": 300.0,
                        "interactions": 336,
                        "top_comments": [],
                        "_xsec_token": "tok-a",
                    }
                ],
            }
        },
    }
    service.cache_file.write_text(json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8")

    detail_calls = {"count": 0}

    def _fake_mcp(tool_name: str, arguments: dict) -> dict:
        if tool_name == "xhs_get_note_detail":
            detail_calls["count"] += 1
            return {"data": {"comments": {"list": [{"content": "求完整步骤"}]}}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr(service, "_mcp_call_tool", _fake_mcp)

    service.enrich_comments_for_categories(["tech"])
    service.enrich_comments_for_categories(["tech"])

    cache = service._read_cache()
    items = cache["categories"]["tech"]["items"]
    assert detail_calls["count"] == 1
    assert [row.get("top_comments") for row in items if row.get("id") == "note-a"][0] == ["求完整步骤"]
    assert [row.get("_top_comments_enriched_at") for row in items if row.get("id") == "note-a"][0]


def test_mcp_call_tool_reuses_http_session(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_algovate_provider(monkeypatch)

    session_counts = {"initialize": 0, "notify": 0, "tool": 0}

    class _FakeResponse:
        def __init__(self, payload: dict, *, headers: dict[str, str] | None = None):
            self._payload = payload
            self.headers = headers or {}
            self.status_code = 200

        def raise_for_status(self) -> None:
            return None

        @property
        def content(self) -> bytes:
            return json.dumps(self._payload, ensure_ascii=False).encode("utf-8")

        @property
        def text(self) -> str:
            return json.dumps(self._payload, ensure_ascii=False)

    class _FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            method = (json or {}).get("method")
            if method == "initialize":
                session_counts["initialize"] += 1
                return _FakeResponse({}, headers={"Mcp-Session-Id": "session-1"})
            if method == "notifications/initialized":
                session_counts["notify"] += 1
                return _FakeResponse({})
            if method == "tools/call":
                session_counts["tool"] += 1
                return _FakeResponse(
                    {
                        "result": {
                            "structuredContent": {
                                "success": True,
                                "feeds": [],
                            }
                        }
                    }
                )
            raise AssertionError(f"unexpected method: {method}")

        def close(self):
            return None

    fake_session = _FakeSession()
    monkeypatch.setattr(xhs_service_module.requests, "Session", lambda: fake_session)

    first = service._mcp_call_tool("xhs_search_note", {"keyword": "AI"})
    second = service._mcp_call_tool("xhs_search_note", {"keyword": "编程"})

    assert first["success"] is True
    assert second["success"] is True
    assert session_counts["initialize"] == 1
    assert session_counts["notify"] == 1
    assert session_counts["tool"] == 2


def test_get_refresh_status_reports_recent_enrichment(tmp_path) -> None:
    service = _create_service(tmp_path)
    now = datetime.now(service.timezone)
    cache_payload = {
        "updated_at": now.isoformat(),
        "categories": {
            "tech": {
                "updated_at": now.isoformat(),
                "fetch_error": None,
                "items": [
                    {
                        "id": "note-a",
                        "title": "AI 选题模板",
                        "content_type": "video",
                        "like_count": 220,
                        "favorite_count": 80,
                        "comment_count": 36,
                        "publish_time": now.isoformat(),
                        "source_url": "https://example.com/1",
                        "hot_score": 300.0,
                        "interactions": 336,
                        "top_comments": ["求完整步骤"],
                        "_top_comments_enriched_at": now.isoformat(),
                    }
                ],
            }
        },
    }
    service.cache_file.write_text(json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8")

    status = service.get_refresh_status("tech")
    assert status["category_key"] == "tech"
    assert status["refresh_in_progress"] is False
    assert status["recent_enrich"]["is_recent"] is True
    assert status["recent_enrich"]["recent_item_count"] == 1
    assert status["recent_enrich"]["ttl_seconds"] == service.comment_enrichment_ttl_seconds


def test_get_trends_sanitizes_untrusted_source_url(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_http_provider(monkeypatch)
    now = datetime.now(service.timezone)
    monkeypatch.setattr(
        service,
        "_fetch_category_items",
        lambda category_key: [
            {
                "id": "unsafe-note",
                "title": "链接安全样本",
                "content_type": "video",
                "like_count": 180,
                "favorite_count": 30,
                "comment_count": 15,
                "publish_time": now.isoformat(),
                "source_url": "javascript:alert(1)",
            }
        ],
    )

    service.refresh("tech")
    payload = service.get_trends("tech", sort="hot", limit=10)
    assert len(payload["items"]) == 1
    assert payload["items"][0]["source_url"].startswith("https://")
    assert "javascript:" not in payload["items"][0]["source_url"]


def test_algovate_mcp_unavailable_keeps_cache_and_returns_error(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_algovate_provider(monkeypatch)
    now = datetime.now(service.timezone)
    cache_payload = {
        "updated_at": now.isoformat(),
        "categories": {
            "tech": {
                "updated_at": now.isoformat(),
                "fetch_error": None,
                "items": [
                    {
                        "id": "cache-1",
                        "title": "缓存热点",
                        "content_type": "video",
                        "like_count": 120,
                        "favorite_count": 40,
                        "comment_count": 20,
                        "publish_time": now.isoformat(),
                        "source_url": "https://example.com/1",
                        "hot_score": 162.0,
                        "interactions": 180,
                        "top_comments": [],
                    }
                ],
            }
        },
    }
    service.cache_file.write_text(json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8")

    def _raise_unavailable(tool_name: str, arguments: dict) -> dict:
        raise ValueError("xhs-mcp 服务不可用，请先启动 npx xhs-mcp mcp --mode http --port 3000")

    monkeypatch.setattr(service, "_mcp_call_tool", _raise_unavailable)
    result = service.refresh("tech")
    assert result["refreshed_categories"] == []
    assert "tech" in result["errors"]
    assert "xhs-mcp 服务不可用" in result["errors"]["tech"]

    payload = service.get_trends("tech", sort="hot", limit=10)
    assert len(payload["items"]) == 1
    assert payload["is_stale"] is True
    assert payload["fetch_error"] == result["errors"]["tech"]


def test_algovate_mcp_transient_status_check_error_does_not_block_refresh(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_algovate_provider(monkeypatch)
    now = datetime.now(service.timezone)

    def _fake_mcp(tool_name: str, arguments: dict) -> dict:
        if tool_name == "xhs_auth_status":
            raise ValueError("StatusCheckError")
        if tool_name == "xhs_search_note":
            return {
                "success": True,
                "feeds": [
                    {
                        "id": "note-a",
                        "title": "AI 选题模板",
                        "time": int((now - timedelta(hours=2)).timestamp() * 1000),
                        "xsecToken": "tok-a",
                        "interact_info": {
                            "liked_count": "220",
                            "collected_count": "80",
                            "comment_count": "36",
                        },
                        "type": "video",
                    }
                ],
            }
        if tool_name == "xhs_get_note_detail":
            return {"data": {"comments": {"list": [{"content": "求完整步骤"}]}}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr(service, "_mcp_call_tool", _fake_mcp)

    refreshed = service.refresh("tech")
    assert refreshed["errors"] == {}
    assert refreshed["refreshed_categories"] == ["tech"]

    payload = service.get_trends("tech", sort="hot", limit=10)
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "note-a"


def test_extract_text_payload_from_sse_keeps_chinese_text(tmp_path) -> None:
    service = _create_service(tmp_path)
    raw_sse = (
        'event: message\n'
        'data: {"result":{"content":[{"type":"text","text":"{\\\\n  \\"success\\": true,\\\\n'
        '  \\"keyword\\": \\"科技\\",\\\\n  \\"feeds\\": [{\\"title\\": \\"中文标题\\"}]\\\\n}"}]},'
        '"jsonrpc":"2.0","id":"tool-1"}\n'
    )

    payload = service._extract_text_payload_from_sse(raw_sse)
    assert payload is not None
    text = payload["result"]["content"][0]["text"]
    assert "中文标题" in text
    assert "科技" in text


def test_decode_mcp_http_payload_uses_utf8_for_sse(tmp_path) -> None:
    service = _create_service(tmp_path)
    response = Response()
    response.status_code = 200
    response.headers["Content-Type"] = "text/event-stream"
    response._content = (
        b'event: message\n'
        b'data: {"result":{"content":[{"type":"text","text":"{\\"success\\":true,\\"title\\":\\"'
        + "中文标题".encode("utf-8")
        + b'\\"}"}]},"jsonrpc":"2.0","id":"1"}\n'
    )
    payload = service._decode_mcp_http_payload(response)
    text = payload["result"]["content"][0]["text"]
    parsed = json.loads(text)
    assert parsed["title"] == "中文标题"
