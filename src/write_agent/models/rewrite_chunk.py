"""
改写分片模型
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class RewriteChunk(SQLModel, table=True):
    """改写阶段增量分片。"""

    __tablename__ = "rewrite_chunks"

    id: Optional[int] = Field(default=None, primary_key=True)

    job_id: int = Field(foreign_key="workflow_jobs.id", index=True, description="任务ID")
    rewrite_id: int = Field(foreign_key="rewrite_records.id", index=True, description="改写ID")
    seq: int = Field(index=True, description="任务内事件序号")
    delta: str = Field(description="增量文本")
    effect_key: str = Field(unique=True, index=True, description="分片幂等键")
    created_at: datetime = Field(default_factory=datetime.now, index=True)

