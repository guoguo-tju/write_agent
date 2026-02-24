"""
改写记录数据模型
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, ForeignKey


class RewriteRecord(SQLModel, table=True):
    """
    改写记录模型

    存储每次改写的完整历史
    """
    __tablename__ = "rewrite_records"

    # 主键
    id: Optional[int] = Field(default=None, primary_key=True)

    # 改写内容
    source_article: str = Field(description="原文")
    final_content: str = Field(default="", description="改写后内容")

    # 关联
    style_id: int = Field(
        foreign_key="writing_styles.id",
        description="使用的写作风格ID"
    )

    # 参数
    target_words: int = Field(default=1000, description="目标字数")
    actual_words: int = Field(default=0, description="实际字数")
    enable_rag: bool = Field(default=False, description="是否启用RAG")
    rag_top_k: int = Field(default=3, description="RAG检索条数")

    # RAG 检索结果（JSON格式存储）
    rag_retrieved: Optional[str] = Field(
        default=None,
        description="RAG检索结果JSON"
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
