"""
封面风格数据模型
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class CoverStyle(SQLModel, table=True):
    """封面风格模板"""

    __tablename__ = "cover_styles"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, description="风格名称")
    prompt_template: str = Field(description="提示词模板，生成时会替换占位符")
    description: Optional[str] = Field(default=None, max_length=500, description="风格描述")
    is_active: bool = Field(default=True, description="是否启用")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
