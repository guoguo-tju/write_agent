"""
小红书热点服务测试。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from requests import Response

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
from write_agent.services.xhs_trends_service import XhsTrendsService


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


def test_refresh_and_hot_sort_filters_items(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_http_provider(monkeypatch)
    now = datetime.now(service.timezone)

    sample_items = [
        {
            "id": "n1",
            "title": "科技选题A",
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
    assert payload["items"][1]["hot_score"] == 201.0


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
    assert result["errors"] == {}
    assert result["refreshed_categories"] == []

    payload = service.get_trends("tech", sort="hot", limit=10)
    assert len(payload["items"]) == 1
    assert payload["fetch_error"] is None


def test_algovate_mcp_refresh_aggregates_keywords_and_enriches_comments(monkeypatch, tmp_path) -> None:
    service = _create_service(tmp_path)
    _set_algovate_provider(monkeypatch)
    now = datetime.now(service.timezone)

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
            if arguments["feed_id"] == "note-a":
                return {"data": {"comments": {"list": [{"content": "求完整步骤"}, {"content": "成本多少"}]}}}
            return {"data": {"comments": {"list": [{"content": "能给模板吗"}]}}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr(service, "_mcp_call_tool", _fake_mcp)

    refreshed = service.refresh("tech")
    assert refreshed["errors"] == {}
    assert refreshed["refreshed_categories"] == ["tech"]

    payload = service.get_trends("tech", sort="hot", limit=10)
    assert len(payload["items"]) == 2
    assert payload["items"][0]["id"] == "note-a"

    cache = service._read_cache()
    cached_items = cache["categories"]["tech"]["items"]
    top_comments = [row.get("top_comments") for row in cached_items if row.get("id") == "note-a"][0]
    assert top_comments == ["求完整步骤", "成本多少"]


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
