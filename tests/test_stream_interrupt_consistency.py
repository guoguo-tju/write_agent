"""
流式接口并发中断一致性测试。
"""
import os
import sys
import threading
import time
from datetime import datetime

# 添加 venv 的 site-packages 到 Python 路径
venv_path = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    ".venv",
    "lib",
    "python3.10",
    "site-packages",
)
if os.path.exists(venv_path):
    sys.path.insert(0, venv_path)

# 添加 src 目录到 Python 路径
src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
sys.path.insert(0, src_path)

# 设置环境变量（必须在导入前）
os.environ["DATABASE_URL"] = "sqlite:///./data/test_write_agent.db"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["SILICONFLOW_API_KEY"] = "test-key"

from sqlmodel import Session, select
from sqlmodel import SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from write_agent.models.writing_style import WritingStyle
from write_agent.models.workflow_job_event import WorkflowJobEvent


class _NoopRewriteService:
    def create_rewrite(self, **kwargs):
        raise RuntimeError("not used in this test")

    def rewrite(self, *args, **kwargs):
        if False:
            yield ""


class _NoopReviewService:
    def create_review(self, *args, **kwargs):
        raise RuntimeError("not used in this test")

    def review(self, *args, **kwargs):
        if False:
            yield ""


def _build_service_and_job(monkeypatch):
    import write_agent.services.workflow_job_service as wjs

    db_engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(db_engine)

    monkeypatch.setattr(wjs, "engine", db_engine)
    monkeypatch.setattr(wjs, "get_rewrite_service", lambda: _NoopRewriteService())
    monkeypatch.setattr(wjs, "get_review_service", lambda: _NoopReviewService())

    service = wjs.WorkflowJobService()
    monkeypatch.setattr(service, "enqueue_job", lambda *_args, **_kwargs: None)

    with Session(db_engine) as session:
        style = WritingStyle(
            name=f"interrupt-style-{int(datetime.now().timestamp() * 1000)}",
            style_description="test",
            tags="interrupt",
        )
        session.add(style)
        session.commit()
        session.refresh(style)
        style_id = style.id

    job, _ = service.create_job(
        source_article="stream interrupt consistency",
        style_id=style_id,
        target_words=200,
        enable_rag=False,
        rag_top_k=3,
        max_retries=1,
        idempotency_key=f"interrupt-{datetime.now().timestamp()}",
    )
    return service, job, db_engine


def test_stream_cancel_interrupt_keeps_terminal_state_consistent(monkeypatch):
    """流式订阅中途触发 cancel 后，任务应稳定收敛为 cancelled。"""
    service, job, db_engine = _build_service_and_job(monkeypatch)
    service._append_event(
        job_id=job.id,
        event_type="stage",
        stage="rewrite",
        payload={"type": "stage", "stage": "rewrite"},
        effect_key=f"{job.id}:stage:rewrite",
    )

    captured = []

    def _consume():
        for event in service.stream_events(
            job.id,
            from_seq=0,
            poll_interval=0.01,
            idle_timeout_seconds=1.0,
        ):
            captured.append(event)

    t = threading.Thread(target=_consume, daemon=True)
    t.start()
    time.sleep(0.05)

    cancelled = service.cancel_job(job.id)
    assert cancelled.status == "cancelled"

    t.join(timeout=1.5)
    assert t.is_alive() is False

    status = service.get_job(job.id)
    assert status.status == "cancelled"
    assert status.current_stage == "cancelled"

    seqs = [event["seq"] for event in captured]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))
    with Session(db_engine) as session:
        cancel_events = session.exec(
            select(WorkflowJobEvent).where(
                WorkflowJobEvent.job_id == job.id,
                WorkflowJobEvent.event_type == "error",
                WorkflowJobEvent.stage == "cancelled",
            )
        ).all()
    assert len(cancel_events) == 1


def test_stream_reconnect_from_seq_keeps_monotonic_no_dup(monkeypatch):
    """断线后按 from_seq 重连，事件序号应单调且不重复。"""
    service, job, db_engine = _build_service_and_job(monkeypatch)

    service._append_event(
        job_id=job.id,
        event_type="stage",
        stage="rewrite",
        payload={"type": "stage", "stage": "rewrite"},
        effect_key=f"{job.id}:stage:1",
    )
    service._append_event(
        job_id=job.id,
        event_type="progress",
        stage="rewrite",
        payload={"type": "progress", "stage": "rewrite", "message": "10%"},
        effect_key=f"{job.id}:progress:1",
    )

    stream1 = service.stream_events(
        job.id,
        from_seq=0,
        poll_interval=0.01,
        idle_timeout_seconds=1.0,
    )
    first = next(stream1)
    second = next(stream1)
    stream1.close()  # 模拟客户端中断

    assert [first["seq"], second["seq"]] == [1, 2]

    service._append_event(
        job_id=job.id,
        event_type="content",
        stage="rewrite",
        payload={"type": "content", "stage": "rewrite", "delta": "hello"},
        effect_key=f"{job.id}:content:1",
    )
    service._append_event(
        job_id=job.id,
        event_type="done",
        stage="finalize",
        payload={"type": "done", "status": "passed", "passed": True},
        effect_key=f"{job.id}:done:1",
    )

    with Session(db_engine) as session:
        db_job = session.get(type(job), job.id)
        db_job.status = "completed"
        db_job.current_stage = "completed"
        db_job.checkpoint_stage = "finalize"
        db_job.updated_at = datetime.now()
        session.add(db_job)
        session.commit()

    reconnect_events = list(
        service.stream_events(
            job.id,
            from_seq=2,
            poll_interval=0.01,
            idle_timeout_seconds=0.1,
        )
    )

    reconnect_seqs = [event["seq"] for event in reconnect_events]
    assert reconnect_seqs == [3, 4]
    assert reconnect_seqs == sorted(reconnect_seqs)
    assert len(reconnect_seqs) == len(set(reconnect_seqs))
