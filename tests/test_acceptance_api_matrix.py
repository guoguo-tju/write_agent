"""
接口端到端验收矩阵：
- 正常流
- 降级流
- 失败流
- 人工介入流
"""
from __future__ import annotations

import json
import os
import sys
import uuid

# 与现有测试保持一致：显式挂载 venv site-packages 与 src 路径
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
from sqlmodel import Session, SQLModel

from write_agent.core.database import engine
from write_agent.main import app
from write_agent.models import WritingStyle


def setup_module() -> None:
    SQLModel.metadata.create_all(engine)


def _create_style() -> int:
    with Session(engine) as session:
        style = WritingStyle(
            name=f"acceptance-style-{uuid.uuid4().hex[:8]}",
            style_description='{"overall_summary":"acceptance"}',
            tags="acceptance",
        )
        session.add(style)
        session.commit()
        session.refresh(style)
        return int(style.id)


def _collect_sse_events(resp) -> list[dict]:
    chunks = [line for line in resp.iter_lines() if line and line.startswith("data: ")]
    return [json.loads(line[6:]) for line in chunks]


def test_acceptance_normal_flow_stream_done(monkeypatch):
    """正常流：stream 返回 stage->progress->content->done。"""
    from write_agent.api import reviews as reviews_api

    client = TestClient(app)
    style_id = _create_style()
    monkeypatch.setattr(reviews_api.workflow_job_service, "enqueue_job", lambda *_args, **_kwargs: None)

    def fake_stream_events(job_id: int, *, from_seq: int = 0, **_kwargs):
        yield {"type": "stage", "stage": "rewrite", "job_id": job_id, "seq": 1}
        yield {"type": "progress", "stage": "rewrite", "job_id": job_id, "seq": 2, "message": "50%"}
        yield {"type": "content", "stage": "rewrite", "job_id": job_id, "seq": 3, "delta": "chunk"}
        yield {
            "type": "done",
            "stage": "finalize",
            "job_id": job_id,
            "seq": 4,
            "status": "passed",
            "passed": True,
        }

    monkeypatch.setattr(reviews_api.workflow_job_service, "stream_events", fake_stream_events)

    created = client.post(
        "/api/reviews/workflow/jobs",
        json={
            "source_article": "normal flow",
            "style_id": style_id,
            "target_words": 200,
            "enable_rag": False,
            "max_retries": 1,
            "idempotency_key": f"normal-{uuid.uuid4().hex}",
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    with client.stream("GET", f"/api/reviews/workflow/jobs/{job_id}/stream", params={"from_seq": 0}) as resp:
        assert resp.status_code == 200
        events = _collect_sse_events(resp)

    assert [event["type"] for event in events] == ["stage", "progress", "content", "done"]
    assert events[-1]["status"] == "passed"
    assert events[-1]["passed"] is True
    assert all(event.get("obs", {}).get("trace_id") for event in events)


def test_acceptance_degraded_flow_stream_still_parseable(monkeypatch):
    """降级流：出现降级提示但事件结构可解析且终态可收敛。"""
    from write_agent.api import reviews as reviews_api

    client = TestClient(app)
    style_id = _create_style()
    monkeypatch.setattr(reviews_api.workflow_job_service, "enqueue_job", lambda *_args, **_kwargs: None)

    def fake_stream_events(job_id: int, *, from_seq: int = 0, **_kwargs):
        yield {"type": "stage", "stage": "rewrite", "job_id": job_id, "seq": 1}
        yield {
            "type": "progress",
            "stage": "rewrite",
            "job_id": job_id,
            "seq": 2,
            "message": "上游不可用，已降级为规则路径",
        }
        yield {
            "type": "done",
            "stage": "finalize",
            "job_id": job_id,
            "seq": 3,
            "status": "reached_max_loops",
            "passed": False,
        }

    monkeypatch.setattr(reviews_api.workflow_job_service, "stream_events", fake_stream_events)

    created = client.post(
        "/api/reviews/workflow/jobs",
        json={
            "source_article": "degraded flow",
            "style_id": style_id,
            "target_words": 200,
            "enable_rag": False,
            "max_retries": 1,
            "idempotency_key": f"degraded-{uuid.uuid4().hex}",
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    with client.stream("GET", f"/api/reviews/workflow/jobs/{job_id}/stream", params={"from_seq": 0}) as resp:
        assert resp.status_code == 200
        events = _collect_sse_events(resp)

    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "reached_max_loops"
    assert any("降级" in (event.get("message") or "") for event in events)


def test_acceptance_failure_flow_stream_error(monkeypatch):
    """失败流：stream 返回 error 且结构可被前端解析。"""
    from write_agent.api import reviews as reviews_api

    client = TestClient(app)
    style_id = _create_style()
    monkeypatch.setattr(reviews_api.workflow_job_service, "enqueue_job", lambda *_args, **_kwargs: None)

    def fake_stream_events(job_id: int, *, from_seq: int = 0, **_kwargs):
        yield {"type": "stage", "stage": "rewrite", "job_id": job_id, "seq": 1}
        yield {
            "type": "error",
            "stage": "failed",
            "job_id": job_id,
            "seq": 2,
            "error_code": "E_WORKFLOW_JOB_FAILED",
            "message": "上游模型超时",
        }

    monkeypatch.setattr(reviews_api.workflow_job_service, "stream_events", fake_stream_events)

    created = client.post(
        "/api/reviews/workflow/jobs",
        json={
            "source_article": "failure flow",
            "style_id": style_id,
            "target_words": 200,
            "enable_rag": False,
            "max_retries": 1,
            "idempotency_key": f"failed-{uuid.uuid4().hex}",
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    with client.stream("GET", f"/api/reviews/workflow/jobs/{job_id}/stream", params={"from_seq": 0}) as resp:
        assert resp.status_code == 200
        events = _collect_sse_events(resp)

    assert events[-1]["type"] == "error"
    assert events[-1]["error_code"] == "E_WORKFLOW_JOB_FAILED"
    assert events[-1]["message"] == "上游模型超时"


def test_acceptance_manual_intervention_cancel_and_resume(monkeypatch):
    """人工介入流：cancel 后不可 resume，错误契约可观测字段完整。"""
    from write_agent.api import reviews as reviews_api

    client = TestClient(app)
    style_id = _create_style()
    monkeypatch.setattr(reviews_api.workflow_job_service, "enqueue_job", lambda *_args, **_kwargs: None)

    created = client.post(
        "/api/reviews/workflow/jobs",
        json={
            "source_article": "manual intervention",
            "style_id": style_id,
            "target_words": 200,
            "enable_rag": False,
            "max_retries": 1,
            "idempotency_key": f"manual-{uuid.uuid4().hex}",
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    cancelled = client.post(f"/api/reviews/workflow/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    blocked = client.post(f"/api/reviews/workflow/jobs/{job_id}/resume")
    assert blocked.status_code == 404
    blocked_data = blocked.json()
    assert "无法恢复" in blocked_data["detail"]
    assert blocked_data.get("trace_id")
    assert blocked_data.get("node_id")
    assert blocked_data.get("behavior_id")
