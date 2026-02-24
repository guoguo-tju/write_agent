"""
数据库连接管理 - 统一管理数据库连接
"""
from sqlmodel import create_engine

from write_agent.core.config import get_settings

# 创建全局数据库引擎
_settings = get_settings()
engine = create_engine(_settings.database_url, echo=False)

__all__ = ["engine"]
