"""
素材数据模型 - RAG 素材库
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Material(SQLModel, table=True):
    """
    RAG 素材模型

    存储参考文章/素材，用于改写时检索增强
    """
    __tablename__ = "materials"

    # 主键
    id: Optional[int] = Field(default=None, primary_key=True)

    # 内容
    title: str = Field(index=True, description="素材标题")
    content: str = Field(description="素材内容")

    # 元信息
    tags: Optional[str] = Field(default=None, description="标签（逗号分隔）")
    source_url: Optional[str] = Field(default=None, description="来源URL")

    # 向量存储状态
    embedding_status: str = Field(
        default="pending",
        description="向量状态: pending/completed/failed"
    )
    embedding_error: Optional[str] = Field(default=None, description="向量化失败原因")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        """Pydantic 配置"""
        from_attributes = True
