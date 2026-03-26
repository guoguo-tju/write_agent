"""
工作流任务事件模型
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class WorkflowJobEvent(SQLModel, table=True):
    """异步任务事件日志，用于SSE重放与排障。"""

    __tablename__ = "workflow_job_events"

    id: Optional[int] = Field(default=None, primary_key=True)

    job_id: int = Field(foreign_key="workflow_jobs.id", index=True, description="任务ID")
    seq: int = Field(index=True, description="任务内递增序号")

    event_type: str = Field(description="stage/progress/content/review_done/done/error 等")
    stage: Optional[str] = Field(default=None, description="rewrite/review/...")
    round: Optional[int] = Field(default=None, description="第几轮")

    rewrite_id: Optional[int] = Field(default=None, description="关联改写ID")
    review_id: Optional[int] = Field(default=None, description="关联审核ID")

    effect_key: Optional[str] = Field(
        default=None,
        unique=True,
        index=True,
        description="阶段副作用幂等键",
    )
    payload_json: Optional[str] = Field(default=None, description="事件payload序列化")
    created_at: datetime = Field(default_factory=datetime.now, index=True)

