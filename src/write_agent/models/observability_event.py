"""
可观测事件索引模型。
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class ObservabilityEvent(SQLModel, table=True):
    """可观测事件索引（用于按 trace/node 快速检索）。"""

    __tablename__ = "observability_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_observability_event_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: str = Field(index=True, max_length=64)
    ts: datetime = Field(default_factory=datetime.now, index=True)
    level: str = Field(default="INFO", index=True, max_length=16)

    trace_id: str = Field(default="", index=True, max_length=64)
    request_id: str = Field(default="", index=True, max_length=64)

    node_id: str = Field(default="", index=True, max_length=16)
    node_key: str = Field(default="", index=True, max_length=128)
    behavior_id: str = Field(default="", index=True, max_length=16)
    behavior_key: str = Field(default="", index=True, max_length=64)

    service: str = Field(default="write-agent", max_length=64)

    api_path: Optional[str] = Field(default=None, index=True, max_length=255)
    http_method: Optional[str] = Field(default=None, max_length=16)
    http_status: Optional[int] = Field(default=None)

    rewrite_id: Optional[int] = Field(default=None, index=True)
    review_id: Optional[int] = Field(default=None, index=True)
    material_id: Optional[int] = Field(default=None, index=True)
    cover_id: Optional[int] = Field(default=None, index=True)
    week_key: Optional[str] = Field(default=None, index=True, max_length=16)

    stage: Optional[str] = Field(default=None, index=True, max_length=32)
    round: Optional[int] = Field(default=None, index=True)

    error_code: Optional[str] = Field(default=None, index=True, max_length=64)
    message: str = Field(default="", max_length=500)
    payload_json: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.now)
