"""
创建数据库表
"""
from sqlmodel import SQLModel, create_engine
from write_agent.models import WritingStyle, Material, RewriteRecord, ReviewRecord, ManualEditRecord
from write_agent.core import get_settings

settings = get_settings()

if __name__ == "__main__":
    # 创建引擎
    engine = create_engine(settings.database_url, echo=True)

    # 创建所有表
    SQLModel.metadata.create_all(engine)

    print("✅ 数据库表创建完成")
