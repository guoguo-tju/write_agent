"""
可观测能力回归测试。
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

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
import pytest
from sqlmodel import Session

from write_agent.core.database import engine
from write_agent.main import app
from write_agent.models import WritingStyle
from write_agent.observability.registry import resolve_node


def _decode_sse(raw_lines: list[str]) -> list[dict]:
    events: list[dict] = []
    for line in raw_lines:
        if not line or not line.startswith("data: "):
            continue
        events.append(json.loads(line[6:]))
    return events


def _create_style() -> int:
    with Session(engine) as session:
        style = WritingStyle(
            name="obs-test-style",
            style_description='{"overall_summary":"test"}',
            tags="obs",
        )
        session.add(style)
        session.commit()
        session.refresh(style)
        return style.id


def test_trace_headers_present_on_regular_request() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Trace-Id")
    assert resp.headers.get("X-Request-Id")


def test_error_payload_contains_observability_fields() -> None:
    client = TestClient(app)
    resp = client.get("/api/reviews/stream", params={"rewrite_id": 999999})
    assert resp.status_code == 404
    data = resp.json()
    assert data["detail"] == "改写记录不存在"
    assert data["trace_id"]
    assert data["request_id"]
    assert data["error_code"] == "E_NOT_FOUND"
    assert "node_id" in data
    assert "behavior_id" in data


def test_workflow_sse_events_include_obs(monkeypatch: pytest.MonkeyPatch) -> None:
    from write_agent.api import reviews as reviews_api

    client = TestClient(app)
    fake_job = SimpleNamespace(id=421, status="queued", rewrite_id=123, review_id=456, checkpoint_seq=0)

    def fake_create_job(**_kwargs):
        return fake_job, False

    def fake_stream_events(job_id: int, *, from_seq: int = 0, **_kwargs):
        yield {
            "type": "stage",
            "stage": "rewrite",
            "round": 1,
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 1,
        }
        yield {
            "type": "progress",
            "stage": "rewrite",
            "round": 1,
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 2,
            "message": "25%",
        }
        yield {
            "type": "content",
            "stage": "rewrite",
            "round": 1,
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 3,
            "delta": "chunk-1",
        }
        yield {
            "type": "done",
            "stage": "finalize",
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 4,
            "status": "passed",
            "passed": True,
        }

    monkeypatch.setattr(reviews_api.workflow_job_service, "create_job", fake_create_job)
    monkeypatch.setattr(reviews_api.workflow_job_service, "stream_events", fake_stream_events)

    style_id = _create_style()

    with client.stream(
        "POST",
        "/api/reviews/workflow",
        json={
            "source_article": "workflow observability test",
            "style_id": style_id,
            "target_words": 200,
            "enable_rag": False,
            "max_retries": 1,
        },
    ) as resp:
        assert resp.status_code == 200
        chunks = [line for line in resp.iter_lines() if line and line.startswith("data: ")]

    events = _decode_sse(chunks)
    assert events
    assert [event["type"] for event in events] == ["stage", "progress", "content", "done"]
    for event in events:
        obs = event.get("obs")
        assert isinstance(obs, dict)
        assert obs.get("trace_id")
        assert obs.get("node_id")
        assert obs.get("behavior_id")
        assert obs.get("event_id")
        assert obs.get("ts")


def test_observability_query_by_trace_id() -> None:
    client = TestClient(app)
    ping = client.get("/health")
    trace_id = ping.headers.get("X-Trace-Id")
    assert trace_id

    resp = client.get("/api/observability/events", params={"trace_id": trace_id, "limit": 200})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] >= 1
    assert any(item.get("trace_id") == trace_id for item in payload["items"])


def test_observability_token_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    from write_agent.api import observability as obs_api

    client = TestClient(app)
    old = obs_api.settings.obs_token
    monkeypatch.setattr(obs_api.settings, "obs_token", "obs-secret", raising=False)
    try:
        denied = client.get("/api/observability/nodes")
        assert denied.status_code == 401

        allowed = client.get(
            "/api/observability/nodes",
            headers={"X-Obs-Token": "obs-secret"},
        )
        assert allowed.status_code == 200
        data = allowed.json()
        assert data["total"] >= 1
    finally:
        monkeypatch.setattr(obs_api.settings, "obs_token", old, raising=False)


def test_unknown_node_raises_in_strict_mode() -> None:
    with pytest.raises(ValueError):
        resolve_node("UNREGISTERED.NODE.KEY")
