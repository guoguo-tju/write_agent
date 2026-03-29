"""
Linux.do 趋势服务测试。
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime

import requests

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

from sqlalchemy import delete
from sqlmodel import Session, select

from write_agent.models import LinuxDoTrendingItem, LinuxDoTrendingSnapshot, Material
from write_agent.services.linuxdo_trending_service import (
    RefreshCoolingDownError,
    RefreshRateLimitedError,
    get_linuxdo_trending_service,
)
from write_agent.services.material_service import engine


class _FakeResponse:
    def __init__(
        self,
        payload: dict | None = None,
        text: str = "",
        status_code: int = 200,
        headers: dict | None = None,
    ) -> None:
        self._payload = payload or {}
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = requests.HTTPError(f"http {self.status_code}")
            error.response = self
            raise error

    def json(self):
        return self._payload


SAMPLE_RSS_WEEKLY = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <item>
      <title>AI 工作流实战</title>
      <link>https://linux.do/t/ai-workflow/9001</link>
      <description><![CDATA[<p>这是一个很长的正文摘要{LONG_TEXT}</p><p>15 posts</p>]]></description>
      <category>ai</category>
      <dc:creator>alice</dc:creator>
      <pubDate>Sat, 28 Mar 2026 08:30:00 +0000</pubDate>
    </item>
    <item>
      <title>Linux 网络排障手册</title>
      <link>https://linux.do/t/linux-network/9002</link>
      <description><![CDATA[<p>短摘要</p><p>8 posts</p>]]></description>
      <category>linux</category>
      <dc:creator>bob</dc:creator>
      <pubDate>Fri, 27 Mar 2026 12:10:00 +0000</pubDate>
    </item>
  </channel>
</rss>
""".replace("{LONG_TEXT}", "A" * 520)

SAMPLE_TOPIC_9001 = {
    "id": 9001,
    "title": "AI 工作流实战",
    "slug": "ai-workflow",
    "views": 2345,
    "like_count": 88,
    "posts_count": 15,
    "tags": ["ai", "workflow"],
    "post_stream": {
        "posts": [
            {
                "id": 1,
                "username": "alice",
                "created_at": "2026-03-28T08:30:00.000Z",
                "cooked": "<p>第一段</p><p>第二段</p>",
                "raw": "第一段\\n\\n第二段",
            }
        ]
    },
}

SAMPLE_TOPIC_9002 = {
    "id": 9002,
    "title": "Linux 网络排障手册",
    "slug": "linux-network",
    "views": 1200,
    "like_count": 36,
    "posts_count": 8,
    "tags": ["linux", "network"],
    "post_stream": {
        "posts": [
            {
                "id": 2,
                "username": "bob",
                "created_at": "2026-03-27T12:10:00.000Z",
                "cooked": "<p>短摘要</p>",
                "raw": "短摘要",
            }
        ]
    },
}

SAMPLE_TOPIC_9001_LONG = {
    "id": 9001,
    "title": "AI 工作流实战",
    "slug": "ai-workflow",
    "views": 2345,
    "like_count": 88,
    "posts_count": 15,
    "tags": ["ai", "workflow"],
    "post_stream": {
        "posts": [
            {
                "id": 1,
                "username": "alice",
                "created_at": "2026-03-28T08:30:00.000Z",
                "cooked": "<p>" + "这是一段非常长的正文内容。" * 120 + "</p>",
                "raw": "这是一段非常长的正文内容。" * 120,
            }
        ]
    },
}


def _cleanup_tables() -> None:
    with Session(engine) as session:
        session.exec(delete(LinuxDoTrendingItem))
        session.exec(delete(LinuxDoTrendingSnapshot))
        session.exec(delete(Material).where(Material.tags.like("%linuxdo-trending%")))
        session.commit()


def _service_for_test():
    service = get_linuxdo_trending_service()
    service.refresh_cooldown_seconds = 0
    service._next_allowed_refresh_at = {"weekly": 0.0, "monthly": 0.0}
    service.rss_429_retries = 0
    service.rss_429_default_retry_after_seconds = 1
    service.rss_429_jitter_seconds = 0
    return service


def _build_fake_get(with_partial_topic_failure: bool = False, long_topic_content: bool = False):
    def _fake_get(url: str, *args, **kwargs):
        if "/top.rss" in url:
            return _FakeResponse(text=SAMPLE_RSS_WEEKLY)
        if url.endswith("/t/9001.json"):
            return _FakeResponse(SAMPLE_TOPIC_9001_LONG if long_topic_content else SAMPLE_TOPIC_9001)
        if url.endswith("/t/9002.json"):
            if with_partial_topic_failure:
                return _FakeResponse(status_code=503)
            return _FakeResponse(SAMPLE_TOPIC_9002)
        raise AssertionError(f"unexpected url: {url}")

    return _fake_get


def test_refresh_upserts_snapshot_and_summary(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()

    monkeypatch.setattr(
        "write_agent.services.linuxdo_trending_service.requests.get",
        _build_fake_get(),
    )

    asyncio.run(service.refresh_snapshot("weekly"))
    asyncio.run(service.refresh_snapshot("weekly"))

    today = datetime.now(service.timezone).date()
    period_key = service.period_key_for("weekly", today)

    with Session(engine) as session:
        snapshots = session.exec(
            select(LinuxDoTrendingSnapshot).where(
                LinuxDoTrendingSnapshot.period_type == "weekly",
                LinuxDoTrendingSnapshot.period_key == period_key,
                LinuxDoTrendingSnapshot.snapshot_date == today,
            )
        ).all()
        assert len(snapshots) == 1

        items = session.exec(
            select(LinuxDoTrendingItem)
            .where(LinuxDoTrendingItem.snapshot_id == snapshots[0].id)
            .order_by(LinuxDoTrendingItem.rank)
        ).all()
        assert len(items) == 2
        assert items[0].topic_id == 9001
        assert len(items[0].content_summary) <= 500
        assert items[0].view_count == 2345
        assert items[1].like_count == 36


def test_get_snapshot_supports_tag_filter_and_limit(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()

    monkeypatch.setattr(
        "write_agent.services.linuxdo_trending_service.requests.get",
        _build_fake_get(),
    )
    asyncio.run(service.refresh_snapshot("weekly"))

    payload = service.get_snapshot(period_type="weekly", tag="linux", limit=20)
    assert payload["period_type"] == "weekly"
    assert payload["requested_period_key"] == payload["period_key"]
    assert payload["is_stale"] is False
    assert len(payload["items"]) == 1
    assert payload["items"][0]["topic_id"] == 9002


def test_list_periods_returns_latest_12_for_monthly(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()

    monkeypatch.setattr(
        "write_agent.services.linuxdo_trending_service.requests.get",
        _build_fake_get(),
    )

    samples = [
        date(2026, 3, 15),
        date(2026, 2, 15),
        date(2026, 1, 15),
        date(2025, 12, 15),
        date(2025, 11, 15),
        date(2025, 10, 15),
        date(2025, 9, 15),
        date(2025, 8, 15),
        date(2025, 7, 15),
        date(2025, 6, 15),
        date(2025, 5, 15),
        date(2025, 4, 15),
        date(2025, 3, 15),
        date(2025, 2, 15),
    ]
    for d in samples:
        now_dt = datetime(d.year, d.month, d.day, 12, 0, tzinfo=service.timezone)
        asyncio.run(service.refresh_snapshot("monthly", now_dt=now_dt))

    periods = service.list_periods("monthly")
    assert len(periods) == 12


def test_get_topic_detail_returns_plain_text(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()

    monkeypatch.setattr(
        "write_agent.services.linuxdo_trending_service.requests.get",
        _build_fake_get(),
    )

    asyncio.run(service.refresh_snapshot("weekly"))
    detail = service.get_topic_detail(9001)

    assert detail["topic_id"] == 9001
    assert detail["title"] == "AI 工作流实战"
    assert "第一段" in detail["content"]


def test_refresh_uses_llm_summary_for_long_content(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()
    monkeypatch.setattr(service, "summary_use_llm", True)
    monkeypatch.setattr(service, "summary_llm_trigger_chars", 500)

    monkeypatch.setattr(
        "write_agent.services.linuxdo_trending_service.requests.get",
        _build_fake_get(long_topic_content=True),
    )

    called: list[tuple[int, int]] = []

    def _fake_summarize_with_llm(source_text: str, topic_id: int):
        called.append((topic_id, len(source_text)))
        return (
            "这篇帖子围绕社区运行情况展开，核心是指标增长与治理反馈。\n"
            "要点：\n- 点击量突破\n- 用户互动稳定\n- 讨论偏建设性"
        )

    monkeypatch.setattr(service, "_summarize_with_llm", _fake_summarize_with_llm)

    asyncio.run(service.refresh_snapshot("weekly"))
    period_key = service.current_period_key("weekly")
    payload = service.get_snapshot(period_type="weekly", period_key=period_key, limit=20)
    item = payload["items"][0]

    assert called
    assert called[0][0] == 9001
    assert "要点：" in item["content"]
    assert len(item["content"]) <= 500


def test_refresh_fallback_to_rule_summary_when_llm_returns_empty(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()
    monkeypatch.setattr(service, "summary_use_llm", True)
    monkeypatch.setattr(service, "summary_llm_trigger_chars", 500)

    monkeypatch.setattr(
        "write_agent.services.linuxdo_trending_service.requests.get",
        _build_fake_get(long_topic_content=True),
    )

    called: list[int] = []

    def _fake_summarize_with_llm(source_text: str, topic_id: int):
        called.append(topic_id)
        return None

    monkeypatch.setattr(service, "_summarize_with_llm", _fake_summarize_with_llm)

    asyncio.run(service.refresh_snapshot("weekly"))
    period_key = service.current_period_key("weekly")
    payload = service.get_snapshot(period_type="weekly", period_key=period_key, limit=20)
    item = payload["items"][0]

    assert called == [9001]
    assert "要点：" not in item["content"]
    assert len(item["content"]) <= 500


def test_refresh_short_content_skips_llm_summary(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()
    monkeypatch.setattr(service, "summary_use_llm", True)
    monkeypatch.setattr(service, "summary_llm_trigger_chars", 500)

    monkeypatch.setattr(
        "write_agent.services.linuxdo_trending_service.requests.get",
        _build_fake_get(),
    )

    def _raise_if_called(*args, **kwargs):
        raise AssertionError("short content should not trigger llm summary")

    monkeypatch.setattr(service, "_summarize_with_llm", _raise_if_called)
    asyncio.run(service.refresh_snapshot("weekly"))


def test_add_item_and_build_rewrite(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()

    monkeypatch.setattr(
        "write_agent.services.linuxdo_trending_service.requests.get",
        _build_fake_get(),
    )

    asyncio.run(service.refresh_snapshot("weekly"))
    period_key = service.current_period_key("weekly")

    added = service.add_item_to_materials("weekly", period_key, 9001)
    assert added["material_id"] > 0
    assert "created" in added

    rewrite_payload = service.build_item_rewrite_markdown("weekly", period_key, 9001)
    assert rewrite_payload["title"]
    assert "AI 工作流实战" in rewrite_payload["content"]
    assert "## 观察点（可补充）" not in rewrite_payload["content"]
    assert "## 改写提示（可补充）" not in rewrite_payload["content"]


def test_add_item_and_build_rewrite_degrade_when_detail_forbidden(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()

    def _fake_get(url: str, *args, **kwargs):
        if "/top.rss" in url:
            return _FakeResponse(text=SAMPLE_RSS_WEEKLY)
        if url.endswith("/t/9001.json"):
            return _FakeResponse(status_code=403)
        if url.endswith("/t/9002.json"):
            return _FakeResponse(SAMPLE_TOPIC_9002)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("write_agent.services.linuxdo_trending_service.requests.get", _fake_get)
    monkeypatch.setattr(
        service,
        "_summarize_with_llm",
        lambda source_text, topic_id: (_ for _ in ()).throw(
            AssertionError("fallback path should not trigger llm summary")
        ),
    )

    asyncio.run(service.refresh_snapshot("weekly"))
    period_key = service.current_period_key("weekly")

    added = service.add_item_to_materials("weekly", period_key, 9001)
    assert added["material_id"] > 0

    rewrite_payload = service.build_item_rewrite_markdown("weekly", period_key, 9001)
    assert rewrite_payload["title"]
    assert "AI 工作流实战" in rewrite_payload["content"]


def test_refresh_keeps_partial_success_when_some_topic_enrich_fail(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()

    monkeypatch.setattr(
        "write_agent.services.linuxdo_trending_service.requests.get",
        _build_fake_get(with_partial_topic_failure=True),
    )

    asyncio.run(service.refresh_snapshot("weekly"))
    payload = service.get_snapshot(period_type="weekly", limit=20)

    assert len(payload["items"]) == 2
    second_item = payload["items"][1]
    assert second_item["topic_id"] == 9002
    assert second_item["view_count"] == 0
    assert second_item["like_count"] == 0
    assert second_item["reply_count"] == 7


def test_refresh_rss_failure_marks_failed_snapshot(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()

    def _fake_get(url: str, *args, **kwargs):
        if "/top.rss" in url:
            return _FakeResponse(status_code=403)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("write_agent.services.linuxdo_trending_service.requests.get", _fake_get)

    try:
        asyncio.run(service.refresh_snapshot("weekly"))
        assert False, "refresh should fail when RSS is unavailable"
    except Exception as error:
        assert "Cloudflare challenge" in str(error)

    with Session(engine) as session:
        failed = session.exec(
            select(LinuxDoTrendingSnapshot)
            .where(
                LinuxDoTrendingSnapshot.period_type == "weekly",
                LinuxDoTrendingSnapshot.fetch_status == "failed",
            )
            .order_by(LinuxDoTrendingSnapshot.id.desc())
        ).first()
        assert failed is not None
        assert failed.fetch_error is not None
        assert "Cloudflare challenge" in failed.fetch_error


def test_refresh_hits_cooldown_after_success(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()
    service.refresh_cooldown_seconds = 30

    monkeypatch.setattr(
        "write_agent.services.linuxdo_trending_service.requests.get",
        _build_fake_get(),
    )

    asyncio.run(service.refresh_snapshot("weekly"))
    try:
        asyncio.run(service.refresh_snapshot("weekly"))
        assert False, "second refresh should be blocked by cooldown"
    except RefreshCoolingDownError as error:
        assert error.retry_after_seconds >= 1


def test_refresh_retries_when_rss_returns_429(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()
    service.rss_429_retries = 1

    calls = {"count": 0}
    sleep_calls: list[float] = []

    def _fake_get(url: str, *args, **kwargs):
        if "/top.rss" in url:
            calls["count"] += 1
            if calls["count"] == 1:
                return _FakeResponse(status_code=429, headers={"Retry-After": "2"})
            return _FakeResponse(text=SAMPLE_RSS_WEEKLY)
        if url.endswith("/t/9001.json"):
            return _FakeResponse(SAMPLE_TOPIC_9001)
        if url.endswith("/t/9002.json"):
            return _FakeResponse(SAMPLE_TOPIC_9002)
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("write_agent.services.linuxdo_trending_service.requests.get", _fake_get)
    monkeypatch.setattr("write_agent.services.linuxdo_trending_service.time.sleep", sleep_calls.append)

    asyncio.run(service.refresh_snapshot("weekly"))
    payload = service.get_snapshot(period_type="weekly", limit=20)

    assert calls["count"] == 2
    assert sleep_calls == [2.0]
    assert len(payload["items"]) == 2


def test_refresh_raises_rate_limited_after_retry_exhausted(monkeypatch) -> None:
    _cleanup_tables()
    service = _service_for_test()
    service.rss_429_retries = 1

    calls = {"count": 0}
    sleep_calls: list[float] = []

    def _fake_get(url: str, *args, **kwargs):
        if "/top.rss" in url:
            calls["count"] += 1
            return _FakeResponse(status_code=429, headers={"Retry-After": "3"})
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("write_agent.services.linuxdo_trending_service.requests.get", _fake_get)
    monkeypatch.setattr("write_agent.services.linuxdo_trending_service.time.sleep", sleep_calls.append)

    try:
        asyncio.run(service.refresh_snapshot("weekly"))
        assert False, "refresh should fail after 429 retries are exhausted"
    except RefreshRateLimitedError as error:
        assert error.retry_after_seconds == 3
        assert service._remaining_cooldown_seconds("weekly") >= 1
        assert calls["count"] == 2
        assert sleep_calls == [3.0]
