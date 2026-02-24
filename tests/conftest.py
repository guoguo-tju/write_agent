"""
测试配置
"""
import os
import sys
import pytest

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# 设置测试环境变量
os.environ["DATABASE_URL"] = "sqlite:///./data/test_write_agent.db"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["SILICONFLOW_API_KEY"] = "test-key"


@pytest.fixture
def test_db():
    """测试数据库 fixture"""
    from sqlmodel import create_engine, SQLModel
    from write_agent.models import WritingStyle, Material, RewriteRecord, ReviewRecord

    engine = create_engine("sqlite:///:memory:", echo=False)
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)
