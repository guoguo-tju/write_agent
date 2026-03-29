"""
Linux.do 趋势快照模型。
"""
from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel, UniqueConstraint


class LinuxDoTrendingSnapshot(SQLModel, table=True):
    """Linux.do 趋势抓取快照。"""

    __tablename__ = "linuxdo_trending_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "period_type",
            "period_key",
            "snapshot_date",
            name="uq_linuxdo_trending_period_day",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    period_type: str = Field(index=True, max_length=16, description="周期类型 weekly/monthly")
    period_key: str = Field(index=True, max_length=16, description="周期标识")
    snapshot_date: date = Field(index=True, description="快照日期（本地时区）")
    captured_at: datetime = Field(default_factory=datetime.now, description="抓取时间")
    fetch_status: str = Field(default="success", description="抓取状态 success/failed")
    fetch_error: Optional[str] = Field(default=None, description="抓取失败原因")
