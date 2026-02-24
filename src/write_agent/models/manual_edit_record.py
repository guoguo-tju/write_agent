"""
手动编辑记录数据模型
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, ForeignKey


class ManualEditRecord(SQLModel, table=True):
    """
    手动编辑记录模型

    存储用户手动编辑文章的内容
    """
    __tablename__ = "manual_edit_records"

    # 主键
    id: Optional[int] = Field(default=None, primary_key=True)

    # 关联审核记录
    review_id: int = Field(
        foreign_key="review_records.id",
        description="关联的审核记录ID"
    )

    # 关联改写记录
    rewrite_id: int = Field(
        foreign_key="rewrite_records.id",
        description="关联的改写记录ID"
    )

    # 原始内容（AI 改写后）
    original_content: str = Field(description="原始内容")

    # 用户编辑后的内容
    edited_content: str = Field(description="编辑后内容")

    # 编辑说明
    edit_note: Optional[str] = Field(
        default=None,
        description="编辑说明"
    )

    # 状态
    status: str = Field(
        default="pending",
        description="状态: pending(待审核)/approved(已确认)"
    )

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        from_attributes = True
