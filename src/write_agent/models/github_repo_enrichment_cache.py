"""
GitHub 仓库增强信息缓存模型。
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class GitHubRepoEnrichmentCache(SQLModel, table=True):
    """仓库增强信息缓存（按 repo_full_name 去重）。"""

    __tablename__ = "github_repo_enrichment_cache"
    __table_args__ = (
        UniqueConstraint("repo_full_name", name="uq_github_repo_enrichment_repo"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    repo_full_name: str = Field(index=True, max_length=255, description="owner/repo")
    payload_json: str = Field(description="增强信息 JSON 载荷")
    fetched_at: datetime = Field(default_factory=datetime.now, description="最近抓取时间")
    last_error: Optional[str] = Field(default=None, description="最近抓取错误")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
