"""
封面记录模型
"""
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class CoverRecord(SQLModel, table=True):
    """封面记录表"""

    __tablename__ = "cover_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    rewrite_id: int = Field(foreign_key="rewrite_records.id", description="关联的改写记录ID")

    # 封面信息
    prompt: str = Field(description="图片生成Prompt")
    image_url: Optional[str] = Field(default=None, description="生成的图片URL")
    size: str = Field(default="2k", description="图片尺寸")

    # 状态
    status: str = Field(default="pending", description="状态: pending/generating/completed/failed")
    error_message: Optional[str] = Field(default=None, description="错误信息")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
