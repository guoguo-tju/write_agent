"""
可观测事件发射器。
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import delete
from sqlmodel import SQLModel, Session, select

from write_agent.core import get_logger, get_settings
from write_agent.core.database import engine
from write_agent.models import ObservabilityEvent
from write_agent.observability.context import current_context
from write_agent.observability.redaction import redact_payload
from write_agent.observability.registry import resolve_behavior, resolve_node

logger = get_logger(__name__)
settings = get_settings()


class ObservabilityEmitter:
    """统一写入 JSON 日志 + SQLite 索引。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_cleanup_at: Optional[datetime] = None
        SQLModel.metadata.create_all(engine, tables=[ObservabilityEvent.__table__])

    def _log_file(self, ts: datetime) -> Path:
        root = Path(settings.obs_log_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root / f"events-{ts.strftime('%Y-%m-%d')}.log"

    def _append_json_line(self, line: dict[str, Any]) -> None:
        ts = line.get("ts")
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts)
            except Exception:
                dt = datetime.now()
        else:
            dt = datetime.now()
        file_path = self._log_file(dt)
        with file_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(line, ensure_ascii=False))
            fp.write("\n")

    def _cleanup_if_needed(self) -> None:
        if not settings.obs_enabled:
            return
        now = datetime.now()
        if self._last_cleanup_at and (now - self._last_cleanup_at) < timedelta(hours=1):
            return
        self._last_cleanup_at = now
        cutoff = now - timedelta(days=max(1, int(settings.obs_retention_days)))

        # 清理索引表
        try:
            with Session(engine) as session:
                session.exec(delete(ObservabilityEvent).where(ObservabilityEvent.ts < cutoff))
                session.commit()
        except Exception as error:
            logger.warning("可观测索引清理失败: %s", error)

        # 清理日志文件
        try:
            log_dir = Path(settings.obs_log_dir).resolve()
            if not log_dir.exists():
                return
            for item in log_dir.glob("events-*.log"):
                try:
                    stem = item.stem.replace("events-", "")
                    day = datetime.strptime(stem, "%Y-%m-%d")
                    if day < cutoff:
                        item.unlink(missing_ok=True)
                except Exception:
                    continue
        except Exception as error:
            logger.warning("可观测日志清理失败: %s", error)

    def emit(
        self,
        *,
        level: str,
        message: str,
        node_key: Optional[str] = None,
        behavior_key: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        error_code: Optional[str] = None,
        api_path: Optional[str] = None,
        http_method: Optional[str] = None,
        http_status: Optional[int] = None,
        extra_entities: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        发射事件（失败自动降级，不抛业务异常）。
        """
        if not settings.obs_enabled:
            return {}

        ctx = current_context()
        node = resolve_node(node_key or ctx.node_key or None)
        behavior = resolve_behavior(behavior_key or ctx.behavior_key or None)

        ts = datetime.now()
        event_id = uuid.uuid4().hex
        merged_entities = {**ctx.entities, **(extra_entities or {})}
        redacted_payload = redact_payload(payload or {})

        event = {
            "event_id": event_id,
            "ts": ts.isoformat(),
            "level": (level or "INFO").upper(),
            "trace_id": ctx.trace_id,
            "request_id": ctx.request_id,
            "node_id": node.node_id,
            "node_key": node.node_key,
            "behavior_id": behavior.behavior_id,
            "behavior_key": behavior.behavior_key,
            "service": "write-agent",
            "api_path": api_path,
            "http_method": http_method,
            "http_status": http_status,
            "rewrite_id": merged_entities.get("rewrite_id"),
            "review_id": merged_entities.get("review_id"),
            "material_id": merged_entities.get("material_id"),
            "cover_id": merged_entities.get("cover_id"),
            "week_key": merged_entities.get("week_key"),
            "stage": merged_entities.get("stage"),
            "round": merged_entities.get("round"),
            "error_code": error_code,
            "message": (message or "")[:500],
            "payload": redacted_payload,
        }

        with self._lock:
            try:
                self._append_json_line(event)
            except Exception as error:
                logger.warning("写可观测日志失败: %s", error)

            try:
                with Session(engine) as session:
                    session.add(
                        ObservabilityEvent(
                            event_id=event_id,
                            ts=ts,
                            level=event["level"],
                            trace_id=ctx.trace_id,
                            request_id=ctx.request_id,
                            node_id=node.node_id,
                            node_key=node.node_key,
                            behavior_id=behavior.behavior_id,
                            behavior_key=behavior.behavior_key,
                            service="write-agent",
                            api_path=api_path,
                            http_method=http_method,
                            http_status=http_status,
                            rewrite_id=merged_entities.get("rewrite_id"),
                            review_id=merged_entities.get("review_id"),
                            material_id=merged_entities.get("material_id"),
                            cover_id=merged_entities.get("cover_id"),
                            week_key=merged_entities.get("week_key"),
                            stage=merged_entities.get("stage"),
                            round=merged_entities.get("round"),
                            error_code=error_code,
                            message=(message or "")[:500],
                            payload_json=json.dumps(redacted_payload, ensure_ascii=False),
                        )
                    )
                    session.commit()
            except Exception as error:
                logger.warning("写可观测索引失败: %s", error)

            self._cleanup_if_needed()

        return event

    def query_events(
        self,
        *,
        trace_id: Optional[str] = None,
        node_id: Optional[str] = None,
        behavior_id: Optional[str] = None,
        rewrite_id: Optional[int] = None,
        review_id: Optional[int] = None,
        material_id: Optional[int] = None,
        cover_id: Optional[int] = None,
        week_key: Optional[str] = None,
        level: Optional[str] = None,
        from_ts: Optional[datetime] = None,
        to_ts: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ObservabilityEvent], int]:
        with Session(engine) as session:
            statement = select(ObservabilityEvent).order_by(ObservabilityEvent.ts.desc())

            if trace_id:
                statement = statement.where(ObservabilityEvent.trace_id == trace_id)
            if node_id:
                statement = statement.where(ObservabilityEvent.node_id == node_id)
            if behavior_id:
                statement = statement.where(ObservabilityEvent.behavior_id == behavior_id)
            if rewrite_id is not None:
                statement = statement.where(ObservabilityEvent.rewrite_id == rewrite_id)
            if review_id is not None:
                statement = statement.where(ObservabilityEvent.review_id == review_id)
            if material_id is not None:
                statement = statement.where(ObservabilityEvent.material_id == material_id)
            if cover_id is not None:
                statement = statement.where(ObservabilityEvent.cover_id == cover_id)
            if week_key:
                statement = statement.where(ObservabilityEvent.week_key == week_key)
            if level:
                statement = statement.where(ObservabilityEvent.level == level.upper())
            if from_ts:
                statement = statement.where(ObservabilityEvent.ts >= from_ts)
            if to_ts:
                statement = statement.where(ObservabilityEvent.ts <= to_ts)

            all_rows = session.exec(statement).all()
            total = len(all_rows)
            rows = all_rows[offset : offset + limit]
            return rows, total

    def trace_timeline(self, trace_id: str) -> list[ObservabilityEvent]:
        with Session(engine) as session:
            return session.exec(
                select(ObservabilityEvent)
                .where(ObservabilityEvent.trace_id == trace_id)
                .order_by(ObservabilityEvent.ts.asc())
            ).all()


_emitter: Optional[ObservabilityEmitter] = None


def get_observability_emitter() -> ObservabilityEmitter:
    global _emitter
    if _emitter is None:
        _emitter = ObservabilityEmitter()
    return _emitter
