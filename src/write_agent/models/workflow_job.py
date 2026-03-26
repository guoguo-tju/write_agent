"""
工作流任务模型
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class WorkflowJob(SQLModel, table=True):
    """异步工作流任务主表。"""

    __tablename__ = "workflow_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)

    # 幂等相关
    idempotency_key: str = Field(index=True, description="客户端幂等键")
    request_key: str = Field(
        unique=True,
        index=True,
        description="服务端实际请求键（force_new 时带随机后缀）",
    )

    # 请求参数快照
    source_article: str = Field(description="原文")
    style_id: int = Field(foreign_key="writing_styles.id", description="风格ID")
    target_words: int = Field(default=1000, description="目标字数")
    enable_rag: bool = Field(default=False, description="是否启用RAG")
    rag_top_k: int = Field(default=3, description="RAG检索条数")
    max_retries: int = Field(default=1, description="最大重试次数")

    # 执行状态
    status: str = Field(
        default="queued",
        index=True,
        description="queued/running/completed/failed/cancelled",
    )
    current_stage: str = Field(default="queued", description="当前阶段")
    checkpoint_stage: str = Field(default="queued", description="最近checkpoint阶段")
    checkpoint_seq: int = Field(default=0, description="最近checkpoint事件序号")
    resume_count: int = Field(default=0, description="恢复次数")

    # 关联实体
    rewrite_id: Optional[int] = Field(default=None, foreign_key="rewrite_records.id")
    review_id: Optional[int] = Field(default=None, foreign_key="review_records.id")

    # 终态信息
    error_code: Optional[str] = Field(default=None, description="错误码")
    error_message: Optional[str] = Field(default=None, description="错误描述")

    # 时间戳
    last_heartbeat_at: datetime = Field(default_factory=datetime.now, description="心跳时间")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

