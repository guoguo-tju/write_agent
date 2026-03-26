"""
审核服务测试
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os
import json

# 添加 venv 的 site-packages 到 Python 路径
venv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".venv", "lib", "python3.10", "site-packages")
if os.path.exists(venv_path):
    sys.path.insert(0, venv_path)

# 添加 src 目录到 Python 路径
src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
sys.path.insert(0, src_path)

from sqlmodel import Session, create_engine, select

# 设置环境变量（必须在导入前）
os.environ["DATABASE_URL"] = "sqlite:///./data/test_write_agent.db"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["SILICONFLOW_API_KEY"] = "test-key"

from write_agent.models.review_record import ReviewRecord
from write_agent.models.writing_style import WritingStyle


class TestReviewRecord:
    """ReviewRecord 模型测试"""

    def test_create_review_record(self, test_db):
        """测试创建审核记录"""
        with Session(test_db) as session:
            # 创建测试用的写作风格
            style = WritingStyle(
                name="测试风格",
                style_description="测试风格描述",
                tags="test",
            )
            session.add(style)
            session.commit()

            # 创建审核记录
            record = ReviewRecord(
                rewrite_id=1,
                content="这是一篇测试文章",
                result="pending",
                round=1,
                retry_count=0,
                status="running",
            )
            session.add(record)
            session.commit()
            session.refresh(record)

            # 验证
            assert record.id is not None
            assert record.rewrite_id == 1
            assert record.content == "这是一篇测试文章"
            assert record.result == "pending"
            assert record.round == 1
            assert record.status == "running"

    def test_review_record_status_change(self, test_db):
        """测试审核状态变更"""
        with Session(test_db) as session:
            record = ReviewRecord(
                rewrite_id=1,
                content="测试内容",
                result="pending",
                status="running",
            )
            session.add(record)
            session.commit()

            # 模拟审核通过
            record.result = "passed"
            record.status = "completed"
            record.ai_score = 8
            record.total_score = 42
            session.commit()
            session.refresh(record)

            assert record.result == "passed"
            assert record.status == "completed"
            assert record.ai_score == 8
            assert record.total_score == 42


class TestReviewService:
    """ReviewService 服务测试"""

    @patch("write_agent.services.llm_service.get_llm_service")
    def test_create_review(self, mock_llm, test_db):
        """测试创建审核记录"""
        # Mock LLM 服务
        mock_llm_instance = Mock()
        mock_llm.return_value = mock_llm_instance
        mock_llm_instance.stream_chat = Mock(return_value=iter([]))

        from write_agent.services.review_service import ReviewService
        from write_agent.models import ReviewRecord

        # 重新设置 engine
        import write_agent.services.review_service as rs
        rs.engine = test_db

        service = ReviewService()

        # 创建审核记录
        record = service.create_review(
            rewrite_id=1,
            content="这是一篇需要审核的文章",
        )

        assert record.id is not None
        assert record.rewrite_id == 1
        assert record.content == "这是一篇需要审核的文章"
        assert record.result == "pending"
        assert record.round == 1
        assert record.status == "running"

    @patch("write_agent.services.llm_service.get_llm_service")
    def test_review_increments_round(self, mock_llm, test_db):
        """测试审核轮次递增"""
        mock_llm_instance = Mock()
        mock_llm.return_value = mock_llm_instance
        mock_llm_instance.stream_chat = Mock(return_value=iter([]))

        import write_agent.services.review_service as rs
        rs.engine = test_db

        from write_agent.services.review_service import ReviewService
        service = ReviewService()

        # 创建第一次审核
        record1 = service.create_review(rewrite_id=1, content="内容1")
        assert record1.round == 1

        # 创建第二次审核（同一 rewrite_id）
        record2 = service.create_review(rewrite_id=1, content="内容2")
        assert record2.round == 2

    @patch("write_agent.services.llm_service.get_llm_service")
    def test_review_stream_returns_done_without_detached_error(self, mock_get_llm, test_db):
        """review 流在完成后不应因 detached 实体访问抛异常。"""
        class _FakeLLM:
            def stream(self, *args, **kwargs):
                yield (
                    '{"quality_scores":{"total":42,"authenticity":8},'
                    '"passed":true,"reason":"通过"}'
                )

        fake_llm = _FakeLLM()
        mock_get_llm.return_value = fake_llm

        import write_agent.services.review_service as rs
        rs.engine = test_db

        service = rs.ReviewService()

        record = service.create_review(
            rewrite_id=1,
            content="这是一篇测试文章",
        )
        events = [json.loads(chunk) for chunk in service.review(record.id, style_context="test-style")]

        assert events[-1]["type"] == "done"
        assert events[-1]["passed"] is True

    @patch("write_agent.services.llm_service.get_llm_service")
    def test_review_total_score_below_threshold_forces_failed(self, mock_get_llm, test_db):
        """即使模型 returned passed=true，总分低于 35 也应强制失败。"""

        class _FakeLLM:
            def stream(self, *args, **kwargs):
                yield (
                    '{"quality_scores":{"total":34,"authenticity":8},'
                    '"passed":true,"reason":"模型误判为通过"}'
                )

        fake_llm = _FakeLLM()
        mock_get_llm.return_value = fake_llm

        import write_agent.services.review_service as rs
        rs.engine = test_db
        service = rs.ReviewService()

        record = service.create_review(rewrite_id=1, content="阈值测试文本")
        events = [json.loads(chunk) for chunk in service.review(record.id, style_context="test-style")]
        done = events[-1]

        assert done["type"] == "done"
        assert done["total_score"] == 34
        assert done["passed"] is False

        with Session(test_db) as session:
            saved = session.get(ReviewRecord, record.id)
            assert saved is not None
            assert saved.result == "failed"
            assert saved.status == "completed"

    @patch("write_agent.services.llm_service.get_llm_service")
    def test_review_total_score_at_threshold_can_pass(self, mock_get_llm, test_db):
        """总分达到阈值且 passed=true 时，结果应通过。"""

        class _FakeLLM:
            def stream(self, *args, **kwargs):
                yield (
                    '{"quality_scores":{"total":35,"authenticity":8},'
                    '"passed":true,"reason":"达到门槛"}'
                )

        fake_llm = _FakeLLM()
        mock_get_llm.return_value = fake_llm

        import write_agent.services.review_service as rs
        rs.engine = test_db
        service = rs.ReviewService()

        record = service.create_review(rewrite_id=1, content="阈值边界测试文本")
        events = [json.loads(chunk) for chunk in service.review(record.id, style_context="test-style")]
        done = events[-1]

        assert done["type"] == "done"
        assert done["total_score"] == 35
        assert done["passed"] is True

        with Session(test_db) as session:
            saved = session.get(ReviewRecord, record.id)
            assert saved is not None
            assert saved.result == "passed"
            assert saved.status == "completed"

class TestWritingStyleModel:
    """WritingStyle 模型测试"""

    def test_to_summary(self, test_db):
        """测试 to_summary 方法"""
        with Session(test_db) as session:
            style = WritingStyle(
                name="简洁风格",
                style_description="短句为主，避免冗余",
                tags="简洁,清晰",
            )
            session.add(style)
            session.commit()
            session.refresh(style)

            summary = style.to_summary()

            assert "简洁风格" in summary
            assert "简洁,清晰" in summary
            assert "短句为主" in summary
