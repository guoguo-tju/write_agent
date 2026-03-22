"""
GitHub 趋势条目模型。
"""
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class GitHubTrendingItem(SQLModel, table=True):
    """GitHub 周榜单条目。"""

    __tablename__ = "github_trending_items"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "rank", name="uq_github_trending_snapshot_rank"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: int = Field(
        foreign_key="github_trending_snapshots.id",
        index=True,
        description="关联快照 ID",
    )
    rank: int = Field(index=True, description="榜单排名（1-10）")
    repo_full_name: str = Field(index=True, max_length=255, description="owner/repo")
    repo_name: str = Field(max_length=255, description="项目名")
    owner: str = Field(max_length=255, description="作者/组织")
    description: Optional[str] = Field(default=None, description="项目简介")
    description_zh: Optional[str] = Field(default=None, description="中文简介（翻译缓存）")
    repo_url: str = Field(max_length=512, description="项目链接")
    stars_this_week: int = Field(default=0, description="本周新增 Star")
    language: Optional[str] = Field(default=None, description="主要语言")
    total_stars: Optional[int] = Field(default=None, description="累计 Star")
