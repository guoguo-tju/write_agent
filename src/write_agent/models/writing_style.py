"""
写作风格数据模型 - 类似 Java 的 Entity
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class WritingStyle(SQLModel, table=True):
    """
    写作风格模型

    类似于 Java 的 @Entity
    """
    __tablename__ = "writing_styles"

    # 主键
    id: Optional[int] = Field(default=None, primary_key=True)

    # 风格名称
    name: str = Field(index=True, description="风格名称")

    # 风格描述（JSON 格式存储）
    style_description: str = Field(description="风格描述（结构化）")

    # 示例文本
    example_text: Optional[str] = Field(default=None, description="示例文本")

    # 标签
    tags: Optional[str] = Field(default=None, description="标签，逗号分隔")

    # 创建时间
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    # 更新时间
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        """Pydantic 配置"""
        from_attributes = True

    def to_summary(self) -> str:
        """转换为简洁的风格描述（供 LLM 使用）"""
        return f"""风格名称: {self.name}
标签: {self.tags or '无'}
风格描述: {self.style_description[:500]}"""
