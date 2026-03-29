"""
Linux.do 趋势条目模型。
"""
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class LinuxDoTrendingItem(SQLModel, table=True):
    """Linux.do 周期榜单条目。"""

    __tablename__ = "linuxdo_trending_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "topic_id", name="uq_linuxdo_trending_snapshot_topic"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: int = Field(
        foreign_key="linuxdo_trending_snapshots.id",
        index=True,
        description="关联快照 ID",
    )
    rank: int = Field(index=True, description="榜单排名")
    topic_id: int = Field(index=True, description="帖子 ID")
    title: str = Field(max_length=500, description="帖子标题")
    content_summary: str = Field(default="", description="摘要内容")
    author: Optional[str] = Field(default=None, max_length=255, description="作者")
    tags_json: str = Field(default="[]", description="标签列表 JSON")
    reply_count: int = Field(default=0, description="回复数")
    view_count: int = Field(default=0, description="浏览数")
    like_count: int = Field(default=0, description="点赞数")
    publish_time: Optional[str] = Field(default=None, max_length=64, description="发布时间")
    topic_url: str = Field(max_length=512, description="帖子链接")
