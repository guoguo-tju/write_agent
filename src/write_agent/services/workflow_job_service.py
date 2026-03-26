"""
工作流任务服务（V2）

实现 checkpoint + 幂等键 + 异步任务执行。
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timedelta
from queue import Empty, Queue
from typing import Generator, Optional
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from write_agent.core import get_logger, get_settings
from write_agent.models import (
    ReviewRecord,
    RewriteChunk,
    RewriteRecord,
    WorkflowJob,
    WorkflowJobEvent,
    WritingStyle,
)
from write_agent.observability import bind_entities, emit_obs_event, obs_scope
from write_agent.services.review_service import get_review_service
from write_agent.services.rewrite_service import get_rewrite_service

logger = get_logger(__name__)
settings = get_settings()
engine = create_engine(settings.database_url, echo=False)

DEFAULT_HEARTBEAT_SECONDS = 3.0
DEFAULT_STALE_TIMEOUT_SECONDS = 90.0


def _utcnow() -> datetime:
    return datetime.now()


def _safe_json_dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


class WorkflowJobService:
    """异步工作流任务服务。"""

    def __init__(self) -> None:
        self.rewrite_service = get_rewrite_service()
        self.review_service = get_review_service()
        self.heartbeat_seconds = DEFAULT_HEARTBEAT_SECONDS
        self.stale_timeout_seconds = DEFAULT_STALE_TIMEOUT_SECONDS
        self._queue: Queue[int] = Queue()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._schema_lock = threading.Lock()
        self._ensure_schema_compat()

    # -------- schema --------
    def _ensure_schema_compat(self) -> None:
        with self._schema_lock:
            SQLModel.metadata.create_all(
                engine,
                tables=[
                    WorkflowJob.__table__,
                    WorkflowJobEvent.__table__,
                    RewriteChunk.__table__,
                ],
            )
            with engine.begin() as conn:
                db_inspector = inspect(conn)
                if db_inspector.has_table("rewrite_records"):
                    columns = {col["name"] for col in db_inspector.get_columns("rewrite_records")}
                    if "workflow_job_id" not in columns:
                        conn.execute(
                            text("ALTER TABLE rewrite_records ADD COLUMN workflow_job_id INTEGER")
                        )
                        logger.info("rewrite_records 已补齐 workflow_job_id 列")

    # -------- lifecycle --------
    def start(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="workflow-job-worker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("WorkflowJob worker 已启动")

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(-1)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)
        logger.info("WorkflowJob worker 已停止")

    # -------- idempotency --------
    @staticmethod
    def _normalize_source(source_article: str) -> str:
        return (source_article or "").strip()

    def _build_idempotency_key(
        self,
        *,
        source_article: str,
        style_id: int,
        target_words: int,
        enable_rag: bool,
        rag_top_k: int,
        max_retries: int,
    ) -> str:
        payload = {
            "source_article": self._normalize_source(source_article),
            "style_id": int(style_id),
            "target_words": int(target_words),
            "enable_rag": bool(enable_rag),
            "rag_top_k": int(rag_top_k),
            "max_retries": int(max_retries),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return f"wf_{digest}"

    # -------- CRUD --------
    def create_job(
        self,
        *,
        source_article: str,
        style_id: int,
        target_words: int = 1000,
        enable_rag: bool = False,
        rag_top_k: int = 3,
        max_retries: int = 1,
        idempotency_key: Optional[str] = None,
        force_new: bool = False,
    ) -> tuple[WorkflowJob, bool]:
        with obs_scope("SVC.WORKFLOW.JOB.CREATE", "WORKFLOW_NODE"):
            normalized_source = self._normalize_source(source_article)
            if not normalized_source:
                raise ValueError("请输入文章内容")
            idem_key = (
                (idempotency_key or "").strip()
                or self._build_idempotency_key(
                    source_article=normalized_source,
                    style_id=style_id,
                    target_words=target_words,
                    enable_rag=enable_rag,
                    rag_top_k=rag_top_k,
                    max_retries=max_retries,
                )
            )

            # 默认复用历史任务；force_new 才新建。
            if not force_new:
                with Session(engine) as session:
                    existing = session.exec(
                        select(WorkflowJob)
                        .where(WorkflowJob.idempotency_key == idem_key)
                        .order_by(WorkflowJob.id.desc())
                    ).first()
                    if existing:
                        emit_obs_event(
                            level="INFO",
                            message="svc.workflow.job.idempotent_hit",
                            entities={"rewrite_id": existing.rewrite_id, "review_id": existing.review_id},
                            error_code="E_WORKFLOW_IDEMPOTENT_HIT",
                            payload={"job_id": existing.id, "status": existing.status},
                        )
                        return existing, True

            request_key = idem_key if not force_new else f"{idem_key}:{uuid4().hex}"
            job = WorkflowJob(
                idempotency_key=idem_key,
                request_key=request_key,
                source_article=normalized_source,
                style_id=style_id,
                target_words=target_words,
                enable_rag=enable_rag,
                rag_top_k=rag_top_k,
                max_retries=max_retries,
                status="queued",
                current_stage="queued",
                checkpoint_stage="queued",
                checkpoint_seq=0,
                resume_count=0,
                last_heartbeat_at=_utcnow(),
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            with Session(engine) as session:
                session.add(job)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    existing = session.exec(
                        select(WorkflowJob).where(WorkflowJob.request_key == request_key)
                    ).first()
                    if existing:
                        return existing, True
                    raise
                session.refresh(job)
            emit_obs_event(
                level="INFO",
                message="svc.workflow.job.create.done",
                payload={"job_id": job.id, "status": job.status},
            )
            self.enqueue_job(job.id)
            return job, False

    def enqueue_job(self, job_id: int) -> None:
        with obs_scope("SVC.WORKFLOW.JOB.ENQUEUE", "WORKFLOW_NODE"):
            self._queue.put(job_id)
            emit_obs_event(
                level="INFO",
                message="svc.workflow.job.enqueued",
                payload={"job_id": job_id},
            )

    def get_job(self, job_id: int) -> Optional[WorkflowJob]:
        with Session(engine) as session:
            return session.get(WorkflowJob, job_id)

    def get_latest_job_by_rewrite(self, rewrite_id: int) -> Optional[WorkflowJob]:
        with Session(engine) as session:
            return session.exec(
                select(WorkflowJob)
                .where(WorkflowJob.rewrite_id == rewrite_id)
                .order_by(WorkflowJob.id.desc())
            ).first()

    def cancel_job(self, job_id: int) -> WorkflowJob:
        with obs_scope("SVC.WORKFLOW.JOB.CANCEL", "WORKFLOW_NODE"):
            with Session(engine) as session:
                job = session.get(WorkflowJob, job_id)
                if not job:
                    raise ValueError("任务不存在")
                if job.status in {"completed", "failed", "cancelled"}:
                    return job
                job.status = "cancelled"
                job.current_stage = "cancelled"
                job.updated_at = _utcnow()
                job.last_heartbeat_at = _utcnow()
                session.add(job)
                session.commit()
                session.refresh(job)
            self._append_event(
                job_id=job_id,
                event_type="error",
                stage="cancelled",
                payload={"type": "error", "message": "任务已取消", "job_id": job_id},
                effect_key=f"{job_id}:cancelled",
            )
            return job

    def resume_job(self, job_id: int) -> WorkflowJob:
        with obs_scope("SVC.WORKFLOW.JOB.RESUME", "WORKFLOW_NODE"):
            with Session(engine) as session:
                job = session.get(WorkflowJob, job_id)
                if not job:
                    raise ValueError("任务不存在")
                if job.status == "completed":
                    return job
                if job.status == "cancelled":
                    raise ValueError("任务已取消，无法恢复")
                job.status = "queued"
                job.resume_count += 1
                job.updated_at = _utcnow()
                job.last_heartbeat_at = _utcnow()
                session.add(job)
                session.commit()
                session.refresh(job)
            self.enqueue_job(job.id)
            return job

    def resume_stale_jobs(self, timeout_seconds: Optional[float] = None) -> int:
        with obs_scope("SVC.WORKFLOW.JOB.RECOVER", "WORKFLOW_NODE"):
            timeout = float(timeout_seconds or self.stale_timeout_seconds)
            stale_before = _utcnow() - timedelta(seconds=timeout)
            recovered = 0
            recovered_job_ids: list[int] = []
            with Session(engine) as session:
                stale_jobs = session.exec(
                    select(WorkflowJob).where(
                        WorkflowJob.status == "running",
                        WorkflowJob.last_heartbeat_at < stale_before,
                    )
                ).all()
                for job in stale_jobs:
                    job.status = "queued"
                    job.resume_count += 1
                    job.updated_at = _utcnow()
                    job.last_heartbeat_at = _utcnow()
                    session.add(job)
                    recovered_job_ids.append(int(job.id))
                    recovered += 1
                session.commit()
            for job_id in recovered_job_ids:
                self.enqueue_job(job_id)
            if recovered:
                emit_obs_event(
                    level="WARNING",
                    message="svc.workflow.job.recovered",
                    payload={"count": recovered},
                )
            return recovered

    # -------- streaming --------
    def stream_events(
        self,
        job_id: int,
        *,
        from_seq: int = 0,
        poll_interval: float = 0.25,
        idle_timeout_seconds: float = 300.0,
    ) -> Generator[dict, None, None]:
        current_seq = max(0, int(from_seq))
        replay_cutoff_seq = current_seq
        with Session(engine) as session:
            job = session.get(WorkflowJob, job_id)
            if job:
                replay_cutoff_seq = max(current_seq, int(job.checkpoint_seq or 0))

        idle_since = time.monotonic()
        while True:
            with Session(engine) as session:
                rows = session.exec(
                    select(WorkflowJobEvent)
                    .where(
                        WorkflowJobEvent.job_id == job_id,
                        WorkflowJobEvent.seq > current_seq,
                    )
                    .order_by(WorkflowJobEvent.seq.asc())
                ).all()
                for row in rows:
                    payload = json.loads(row.payload_json or "{}")
                    payload.setdefault("job_id", job_id)
                    payload.setdefault("seq", row.seq)
                    payload.setdefault("checkpoint_stage", row.stage or "")
                    payload["is_replay"] = row.seq <= replay_cutoff_seq
                    current_seq = row.seq
                    idle_since = time.monotonic()
                    yield payload

                job = session.get(WorkflowJob, job_id)
                if not job:
                    break
                if job.status in {"completed", "failed", "cancelled"} and not rows:
                    break

            if time.monotonic() - idle_since > idle_timeout_seconds:
                break
            time.sleep(poll_interval)

    # -------- worker --------
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = self._queue.get(timeout=0.5)
            except Empty:
                continue
            if job_id < 0:
                continue
            try:
                self.run_job(job_id)
            except Exception as error:
                logger.error("workflow job 执行异常: job_id=%s err=%s", job_id, error, exc_info=True)
            finally:
                self._queue.task_done()

    def _touch_job(self, session: Session, job: WorkflowJob, *, stage: Optional[str] = None) -> None:
        if stage:
            job.current_stage = stage
        job.last_heartbeat_at = _utcnow()
        job.updated_at = _utcnow()
        session.add(job)

    def _append_event(
        self,
        *,
        job_id: int,
        event_type: str,
        stage: str,
        payload: dict,
        rewrite_id: Optional[int] = None,
        review_id: Optional[int] = None,
        round_num: Optional[int] = None,
        effect_key: Optional[str] = None,
    ) -> int:
        with Session(engine) as session:
            job = session.get(WorkflowJob, job_id)
            if not job:
                raise ValueError("任务不存在")
            if effect_key:
                existing = session.exec(
                    select(WorkflowJobEvent).where(WorkflowJobEvent.effect_key == effect_key)
                ).first()
                if existing:
                    return existing.seq

            next_seq = int(job.checkpoint_seq or 0) + 1
            payload = dict(payload)
            payload.setdefault("type", event_type)
            payload.setdefault("job_id", job_id)
            payload.setdefault("seq", next_seq)
            if rewrite_id is not None:
                payload.setdefault("rewrite_id", rewrite_id)
            if review_id is not None:
                payload.setdefault("review_id", review_id)
            if round_num is not None:
                payload.setdefault("round", round_num)

            row = WorkflowJobEvent(
                job_id=job_id,
                seq=next_seq,
                event_type=event_type,
                stage=stage,
                round=round_num,
                rewrite_id=rewrite_id,
                review_id=review_id,
                effect_key=effect_key,
                payload_json=_safe_json_dumps(payload),
                created_at=_utcnow(),
            )
            session.add(row)
            job.checkpoint_seq = next_seq
            job.checkpoint_stage = stage
            self._touch_job(session, job, stage=stage)
            session.commit()
            return next_seq

    def _mark_job_failed(self, job_id: int, *, code: str, message: str) -> None:
        with Session(engine) as session:
            job = session.get(WorkflowJob, job_id)
            if not job:
                return
            job.status = "failed"
            job.error_code = code
            job.error_message = message
            self._touch_job(session, job, stage="failed")
            session.commit()
            rewrite_id = job.rewrite_id
        if rewrite_id:
            with Session(engine) as session:
                rewrite = session.get(RewriteRecord, rewrite_id)
                if rewrite and rewrite.status == "running":
                    rewrite.status = "failed"
                    rewrite.error_message = message
                    rewrite.updated_at = _utcnow()
                    session.add(rewrite)
                    session.commit()
        self._append_event(
            job_id=job_id,
            event_type="error",
            stage="failed",
            rewrite_id=rewrite_id,
            payload={"type": "error", "message": message, "error_code": code},
            effect_key=f"{job_id}:failed:{code}",
        )

    def _get_style_context(self, style_id: int) -> str:
        with Session(engine) as session:
            style = session.get(WritingStyle, style_id)
            return style.to_summary() if style else ""

    def _get_review_for_round(self, rewrite_id: int, round_num: int) -> Optional[ReviewRecord]:
        with Session(engine) as session:
            return session.exec(
                select(ReviewRecord)
                .where(ReviewRecord.rewrite_id == rewrite_id, ReviewRecord.round == round_num)
                .order_by(ReviewRecord.id.desc())
            ).first()

    def run_job(self, job_id: int) -> None:
        with obs_scope("SVC.WORKFLOW.JOB.RUN", "WORKFLOW_NODE"):
            with Session(engine) as session:
                job = session.get(WorkflowJob, job_id)
                if not job:
                    return
                if job.status in {"completed", "cancelled"}:
                    return
                job.status = "running"
                self._touch_job(session, job, stage=job.current_stage or "running")
                session.commit()
                session.refresh(job)

            bind_entities({"rewrite_id": job.rewrite_id, "review_id": job.review_id})
            emit_obs_event(
                level="INFO",
                message="svc.workflow.job.run.start",
                payload={"job_id": job_id, "resume_count": job.resume_count},
            )

            try:
                # 1) 初始化 rewrite 记录（幂等）
                rewrite_id = job.rewrite_id
                if not rewrite_id:
                    rewrite_record = self.rewrite_service.create_rewrite(
                        source_article=job.source_article,
                        style_id=job.style_id,
                        target_words=job.target_words,
                        enable_rag=job.enable_rag,
                        rag_top_k=job.rag_top_k,
                    )
                    rewrite_id = rewrite_record.id
                    with Session(engine) as session:
                        current_job = session.get(WorkflowJob, job_id)
                        if not current_job:
                            return
                        current_job.rewrite_id = rewrite_id
                        self._touch_job(session, current_job, stage="rewrite_r1")
                        session.add(current_job)
                        rewrite = session.get(RewriteRecord, rewrite_id)
                        if rewrite:
                            rewrite.workflow_job_id = job_id
                            rewrite.updated_at = _utcnow()
                            session.add(rewrite)
                        session.commit()
                    self._append_event(
                        job_id=job_id,
                        event_type="stage",
                        stage="rewrite",
                        rewrite_id=rewrite_id,
                        round_num=1,
                        payload={
                            "type": "stage",
                            "stage": "rewrite",
                            "round": 1,
                            "rewrite_id": rewrite_id,
                            "retry_count": 0,
                            "max_retries": job.max_retries,
                            "message": "正在改写...",
                        },
                        effect_key=f"{job_id}:stage:rewrite:1",
                    )
                else:
                    self._append_event(
                        job_id=job_id,
                        event_type="progress",
                        stage="rewrite",
                        rewrite_id=rewrite_id,
                        payload={
                            "type": "progress",
                            "stage": "rewrite",
                            "round": 1,
                            "rewrite_id": rewrite_id,
                            "message": "恢复任务：继续执行改写流程",
                        },
                        effect_key=f"{job_id}:resume:rewrite",
                    )

                retries = min(max(0, int(job.max_retries or 0)), 1)
                total_rounds = retries + 1
                current_content = ""
                latest_review_feedback = ""
                last_review_id: Optional[int] = None

                for round_num in range(1, total_rounds + 1):
                    if round_num > 1:
                        self._append_event(
                            job_id=job_id,
                            event_type="stage",
                            stage="rewrite",
                            rewrite_id=rewrite_id,
                            review_id=last_review_id,
                            round_num=round_num,
                            payload={
                                "type": "stage",
                                "stage": "rewrite",
                                "round": round_num,
                                "rewrite_id": rewrite_id,
                                "retry_count": round_num - 1,
                                "max_retries": retries,
                                "message": "根据主编意见进行二次写稿...",
                            },
                            effect_key=f"{job_id}:stage:rewrite:{round_num}",
                        )

                    rewrite_kwargs: dict = {}
                    if round_num > 1:
                        rewrite_kwargs = {
                            "revision_base_content": current_content,
                            "review_feedback": latest_review_feedback,
                        }
                    rewrite_done = False
                    chunk_idx = 0
                    actual_words = 0
                    for raw in self.rewrite_service.rewrite(rewrite_id, **rewrite_kwargs):
                        data = json.loads(raw)
                        event_type = data.get("type")
                        if event_type == "progress":
                            self._append_event(
                                job_id=job_id,
                                event_type="progress",
                                stage="rewrite",
                                rewrite_id=rewrite_id,
                                round_num=round_num,
                                payload={
                                    "type": "progress",
                                    "stage": "rewrite",
                                    "round": round_num,
                                    "rewrite_id": rewrite_id,
                                    "message": data.get("message", ""),
                                },
                            )
                            continue
                        if event_type == "content":
                            delta = str(data.get("delta", ""))
                            chunk_idx += 1
                            effect_key = f"{job_id}:rewrite:{round_num}:{chunk_idx}"
                            chunk_persisted = False
                            with Session(engine) as session:
                                existing = session.exec(
                                    select(RewriteChunk).where(RewriteChunk.effect_key == effect_key)
                                ).first()
                                if not existing:
                                    chunk_persisted = True
                                    session.add(
                                        RewriteChunk(
                                            job_id=job_id,
                                            rewrite_id=rewrite_id,
                                            seq=chunk_idx,
                                            delta=delta,
                                            effect_key=effect_key,
                                            created_at=_utcnow(),
                                        )
                                    )
                                    session.commit()
                            if not chunk_persisted:
                                continue
                            current_content += delta
                            self._append_event(
                                job_id=job_id,
                                event_type="content",
                                stage="rewrite",
                                rewrite_id=rewrite_id,
                                round_num=round_num,
                                payload={
                                    "type": "content",
                                    "stage": "rewrite",
                                    "round": round_num,
                                    "rewrite_id": rewrite_id,
                                    "delta": delta,
                                },
                                effect_key=effect_key,
                            )
                            continue
                        if event_type == "done":
                            rewrite_done = True
                            current_content = str(data.get("final_content", current_content))
                            actual_words = int(data.get("actual_words", 0) or 0)
                            break
                        if event_type == "error":
                            self._mark_job_failed(
                                job_id,
                                code="E_REWRITE_FAILED",
                                message=str(data.get("message", "改写失败")),
                            )
                            return

                    if not rewrite_done:
                        self._mark_job_failed(
                            job_id,
                            code="E_WORKFLOW_REWRITE_INCOMPLETE",
                            message="改写流程未正常完成",
                        )
                        return

                    self._append_event(
                        job_id=job_id,
                        event_type="stage",
                        stage="review",
                        rewrite_id=rewrite_id,
                        round_num=round_num,
                        payload={
                            "type": "stage",
                            "stage": "review",
                            "round": round_num,
                            "rewrite_id": rewrite_id,
                            "retry_count": round_num - 1,
                            "max_retries": retries,
                            "message": "主编审核中..." if round_num == 1 else "主编二次审核中...",
                            "actual_words": actual_words,
                        },
                        effect_key=f"{job_id}:stage:review:{round_num}",
                    )

                    existing_round_review = self._get_review_for_round(rewrite_id, round_num)
                    review_done = False
                    passed = False
                    total_score = 0
                    reason = ""
                    review_payload: dict = {}
                    review_id: Optional[int] = None

                    if existing_round_review and existing_round_review.status == "completed":
                        review_done = True
                        review_id = existing_round_review.id
                        passed = existing_round_review.result == "passed"
                        total_score = int(existing_round_review.total_score or 0)
                        reason = "通过" if passed else "未通过"
                        review_payload = {}
                    else:
                        review_record = self.review_service.create_review(
                            rewrite_id=rewrite_id,
                            content=current_content,
                        )
                        review_id = review_record.id
                        style_context = self._get_style_context(job.style_id)
                        for raw in self.review_service.review(review_id, style_context):
                            data = json.loads(raw)
                            event_type = data.get("type")
                            if event_type == "done":
                                review_done = True
                                passed = bool(data.get("passed", False))
                                total_score = int(data.get("total_score", 0) or 0)
                                reason = str(data.get("result", "审核完成"))
                                review_payload = data
                                break
                            if event_type == "error":
                                self._mark_job_failed(
                                    job_id,
                                    code="E_REVIEW_FAILED",
                                    message=str(data.get("message", "审核失败")),
                                )
                                return

                    if not review_done:
                        self._mark_job_failed(
                            job_id,
                            code="E_WORKFLOW_REVIEW_INCOMPLETE",
                            message="审核流程未正常完成",
                        )
                        return

                    last_review_id = review_id
                    latest_review_feedback = (
                        _safe_json_dumps(review_payload)
                        if review_payload
                        else latest_review_feedback
                    )

                    with Session(engine) as session:
                        current_job = session.get(WorkflowJob, job_id)
                        if current_job:
                            current_job.review_id = review_id
                            self._touch_job(session, current_job, stage=f"review_r{round_num}")
                            session.commit()

                    self._append_event(
                        job_id=job_id,
                        event_type="review_done",
                        stage="review",
                        rewrite_id=rewrite_id,
                        review_id=review_id,
                        round_num=round_num,
                        payload={
                            "type": "review_done",
                            "stage": "review",
                            "round": round_num,
                            "rewrite_id": rewrite_id,
                            "review_id": review_id,
                            "passed": passed,
                            "score": total_score,
                            "reason": reason,
                            "retry_count": round_num - 1,
                            "max_retries": retries,
                        },
                        effect_key=f"{job_id}:review_done:{round_num}",
                    )

                    if passed:
                        self._append_event(
                            job_id=job_id,
                            event_type="done",
                            stage="finalize",
                            rewrite_id=rewrite_id,
                            review_id=review_id,
                            round_num=round_num,
                            payload={
                                "type": "done",
                                "status": "passed",
                                "passed": True,
                                "rewrite_id": rewrite_id,
                                "review_id": review_id,
                                "round": round_num,
                                "retry_count": round_num - 1,
                                "max_retries": retries,
                            },
                            effect_key=f"{job_id}:done:passed",
                        )
                        with Session(engine) as session:
                            current_job = session.get(WorkflowJob, job_id)
                            if current_job:
                                current_job.status = "completed"
                                self._touch_job(session, current_job, stage="completed")
                                session.commit()
                        return

                self._append_event(
                    job_id=job_id,
                    event_type="done",
                    stage="finalize",
                    rewrite_id=rewrite_id,
                    review_id=last_review_id,
                    round_num=total_rounds,
                    payload={
                        "type": "done",
                        "status": "reached_max_loops",
                        "passed": False,
                        "rewrite_id": rewrite_id,
                        "review_id": last_review_id,
                        "round": total_rounds,
                        "retry_count": retries,
                        "max_retries": retries,
                    },
                    effect_key=f"{job_id}:done:max_loops",
                )
                with Session(engine) as session:
                    current_job = session.get(WorkflowJob, job_id)
                    if current_job:
                        current_job.status = "completed"
                        self._touch_job(session, current_job, stage="completed")
                        session.commit()

            except Exception as error:
                self._mark_job_failed(
                    job_id,
                    code="E_WORKFLOW_JOB_FAILED",
                    message=str(error),
                )
                emit_obs_event(
                    level="ERROR",
                    message="svc.workflow.job.run.failed",
                    error_code="E_WORKFLOW_JOB_FAILED",
                    payload={"job_id": job_id, "error": str(error)},
                )


_workflow_job_service: Optional[WorkflowJobService] = None


def get_workflow_job_service() -> WorkflowJobService:
    global _workflow_job_service
    if _workflow_job_service is None:
        _workflow_job_service = WorkflowJobService()
    return _workflow_job_service
