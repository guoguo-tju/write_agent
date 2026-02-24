"""
审核记录数据模型
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, ForeignKey


class ReviewRecord(SQLModel, table=True):
    """
    审核记录模型

    存储每次文章审核的结果
    """
    __tablename__ = "review_records"

    # 主键
    id: Optional[int] = Field(default=None, primary_key=True)

    # 关联改写记录
    rewrite_id: int = Field(
        foreign_key="rewrite_records.id",
        description="关联的改写记录ID"
    )

    # 审核内容（引用改写的内容）
    content: str = Field(description="被审核的文章内容")

    # 审核结果
    result: str = Field(
        default="pending",
        description="审核结果: pending(待审核)/passed(通过)/failed(不通过)"
    )

    # 审核意见（JSON格式存储）
    # 包含: ai_detection, issues, suggestions, scores
    feedback: Optional[str] = Field(
        default=None,
        description="审核反馈JSON"
    )

    # AI 味道评分（1-10分）
    ai_score: Optional[int] = Field(
        default=None,
        description="AI味道评分(1-10)"
    )

    # 综合评分（1-50分，5维度各10分）
    total_score: Optional[int] = Field(
        default=None,
        description="综合评分(1-50)"
    )

    # 审核轮次
    round: int = Field(
        default=1,
        description="审核轮次"
    )

    # 重试次数
    retry_count: int = Field(
        default=0,
        description="重试次数"
    )

    # 状态
    status: str = Field(
        default="running",
        description="状态: running/completed/failed"
    )
    error_message: Optional[str] = Field(default=None, description="错误信息")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        from_attributes = True
