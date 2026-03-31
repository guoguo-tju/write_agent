"""
GitHub 趋势快照模型。
"""
from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class GitHubTrendingSnapshot(SQLModel, table=True):
    """GitHub 周榜抓取快照。"""

    __tablename__ = "github_trending_snapshots"
    __table_args__ = (
        UniqueConstraint("week_key", "snapshot_date", name="uq_github_trending_week_day"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    week_key: str = Field(index=True, max_length=16, description="周标识（YYYY-Www）")
    period_type: str = Field(
        default="weekly",
        index=True,
        max_length=16,
        description="周期类型（weekly/daily）",
    )
    period_key: str = Field(
        default="",
        index=True,
        max_length=16,
        description="周期标识（weekly: YYYY-Www / daily: YYYY-MM-DD）",
    )
    snapshot_date: date = Field(index=True, description="快照日期（本地时区）")
    captured_at: datetime = Field(default_factory=datetime.now, description="抓取时间")
    is_weekly_archive: bool = Field(default=False, description="是否周归档快照")
    fetch_status: str = Field(default="success", description="抓取状态 success/failed")
    fetch_error: Optional[str] = Field(default=None, description="抓取失败原因")
