"""
LangGraph 工作流测试
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import json
from types import SimpleNamespace
import sys
import os

# 添加 venv 的 site-packages 到 Python 路径
venv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".venv", "lib", "python3.10", "site-packages")
if os.path.exists(venv_path):
    sys.path.insert(0, venv_path)

# 添加 src 目录到 Python 路径
src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
sys.path.insert(0, src_path)

from sqlmodel import Session, create_engine

# 设置环境变量（必须在导入前）
import os
os.environ["DATABASE_URL"] = "sqlite:///./data/test_write_agent.db"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["SILICONFLOW_API_KEY"] = "test-key"

from write_agent.models.writing_style import WritingStyle


class TestWritingState:
    """WritingState 类型测试"""

    def test_state_definition(self):
        """测试状态定义"""
        from write_agent.services.workflow_service import WritingState

        # 创建初始状态
        state: WritingState = {
            "source_article": "原文内容",
            "style_id": 1,
            "target_words": 1000,
            "enable_rag": False,
            "rewritten_content": "",
            "review_result": "",
            "review_feedback": "",
            "review_score": 0,
            "retry_count": 0,
            "max_retries": 3,
            "current_step": "",
        }

        assert state["source_article"] == "原文内容"
        assert state["style_id"] == 1
        assert state["max_retries"] == 3


class TestShouldContinue:
    """should_continue 边函数测试"""

    def test_passed_goes_to_decision(self):
        """测试审核通过时跳转到决策节点（让用户选择人工编辑或跳过）"""
        from write_agent.services.workflow_service import should_continue

        state = {
            "review_result": "passed",
            "retry_count": 0,
            "max_retries": 3,
        }

        result = should_continue(state)
        # 审核通过后去决策节点，让用户选择
        assert result == "decision"

    def test_failed_increments_retry(self):
        """测试审核不通过时返回改写"""
        from write_agent.services.workflow_service import should_continue

        state = {
            "review_result": "failed",
            "retry_count": 0,
            "max_retries": 3,
        }

        result = should_continue(state)
        assert result == "rewrite"

    def test_max_retries_reached(self):
        """测试达到最大重试次数时结束"""
        from write_agent.services.workflow_service import should_continue

        state = {
            "review_result": "failed",
            "retry_count": 3,
            "max_retries": 3,
        }

        result = should_continue(state)
        assert result == "end"


class TestWorkflowGraph:
    """工作流图结构测试"""

    def test_workflow_graph_creation(self):
        """测试工作流图创建"""
        from write_agent.services.workflow_service import create_workflow

        workflow = create_workflow()

        # 验证图已创建
        assert workflow is not None

    def test_workflow_nodes(self):
        """测试工作流节点"""
        from write_agent.services.workflow_service import create_workflow

        workflow = create_workflow()

        # 检查节点
        nodes = list(workflow.nodes.keys())
        assert "rewrite" in nodes
        assert "review" in nodes
        assert "cover" in nodes


class TestWorkflowService:
    """WorkflowService 测试"""

    def test_workflow_initialization(self):
        """测试工作流服务初始化"""
        from write_agent.services.workflow_service import WorkflowService

        service = WorkflowService()
        assert service.graph is not None

    def test_workflow_run_stream(self):
        """测试工作流流式执行（模拟）"""
        from write_agent.services.workflow_service import WorkflowService

        service = WorkflowService()

        # 验证方法存在
        assert hasattr(service, "run_stream")
        assert callable(service.run_stream)


class _DummySession:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def get(self, model, key):
        return None


class _FakeRewriteService:
    def __init__(self):
        self.calls = []
        self.round_outputs = {
            1: {
                "final_content": "首稿内容",
                "actual_words": 120,
            },
            2: {
                "final_content": "二次改写内容",
                "actual_words": 118,
            },
        }

    def create_rewrite(self, **kwargs):
        return SimpleNamespace(id=1001)

    def rewrite(self, rewrite_id, revision_base_content=None, review_feedback=None):
        round_num = 1 if not revision_base_content else 2
        self.calls.append(
            {
                "rewrite_id": rewrite_id,
                "round": round_num,
                "revision_base_content": revision_base_content,
                "review_feedback": review_feedback,
            }
        )

        yield json.dumps({"type": "progress", "step": "rewrite", "message": "正在改写..."})
        yield json.dumps({"type": "content", "delta": f"round-{round_num}"})
        yield json.dumps({"type": "done", **self.round_outputs[round_num]})


class _FakeReviewService:
    def __init__(self, passed_sequence):
        self.passed_sequence = list(passed_sequence)
        self.create_calls = []
        self.review_calls = []
        self.review_id = 2000

    def create_review(self, rewrite_id, content):
        self.review_id += 1
        self.create_calls.append(
            {
                "rewrite_id": rewrite_id,
                "content": content,
                "review_id": self.review_id,
            }
        )
        return SimpleNamespace(id=self.review_id)

    def review(self, review_id, style_context=""):
        self.review_calls.append({"review_id": review_id, "style_context": style_context})
        idx = len(self.review_calls) - 1
        passed = bool(self.passed_sequence[idx])
        score = 45 if passed else 30
        reason = "通过" if passed else "未通过"
        yield json.dumps({"type": "done", "passed": passed, "total_score": score, "result": reason})


class TestWorkflowLoopStream:
    def _mock_dependencies(self, monkeypatch, review_passed_sequence):
        import write_agent.services.workflow_service as ws
        import write_agent.services.rewrite_service as rewrite_module
        import write_agent.services.review_service as review_module

        fake_rewrite = _FakeRewriteService()
        fake_review = _FakeReviewService(review_passed_sequence)

        monkeypatch.setattr(ws, "Session", _DummySession)
        monkeypatch.setattr(rewrite_module, "get_rewrite_service", lambda: fake_rewrite)
        monkeypatch.setattr(review_module, "get_review_service", lambda: fake_review)

        return ws, fake_rewrite, fake_review

    def test_stream_passed_on_first_round(self, monkeypatch):
        ws, fake_rewrite, fake_review = self._mock_dependencies(monkeypatch, [True])
        service = ws.WorkflowService()

        events = list(
            service.run_stream(
                source_article="原文",
                style_id=1,
                target_words=200,
                enable_rag=False,
                max_retries=1,
            )
        )

        stage_events = [e for e in events if e.get("type") == "stage"]
        assert ("rewrite", 1) in {(e.get("stage"), e.get("round")) for e in stage_events}
        assert ("review", 1) in {(e.get("stage"), e.get("round")) for e in stage_events}
        assert ("rewrite", 2) not in {(e.get("stage"), e.get("round")) for e in stage_events}

        done_event = next(e for e in events if e.get("type") == "done")
        assert done_event["status"] == "passed"
        assert done_event["round"] == 1
        assert len(fake_rewrite.calls) == 1
        assert len(fake_review.create_calls) == 1

    def test_stream_retry_once_then_passed(self, monkeypatch):
        ws, fake_rewrite, fake_review = self._mock_dependencies(monkeypatch, [False, True])
        service = ws.WorkflowService()

        events = list(
            service.run_stream(
                source_article="原文",
                style_id=1,
                target_words=200,
                enable_rag=False,
                max_retries=1,
            )
        )

        stage_pairs = [(e.get("stage"), e.get("round")) for e in events if e.get("type") == "stage"]
        assert ("rewrite", 2) in stage_pairs
        assert ("review", 2) in stage_pairs

        review_done_rounds = [e.get("round") for e in events if e.get("type") == "review_done"]
        assert review_done_rounds == [1, 2]

        second_rewrite_call = fake_rewrite.calls[1]
        assert second_rewrite_call["revision_base_content"] == "首稿内容"
        assert second_rewrite_call["review_feedback"]

        done_event = next(e for e in events if e.get("type") == "done")
        assert done_event["status"] == "passed"
        assert done_event["round"] == 2

    def test_stream_reached_max_loops(self, monkeypatch):
        ws, _, _ = self._mock_dependencies(monkeypatch, [False, False])
        service = ws.WorkflowService()

        events = list(
            service.run_stream(
                source_article="原文",
                style_id=1,
                target_words=200,
                enable_rag=False,
                max_retries=1,
            )
        )

        done_event = next(e for e in events if e.get("type") == "done")
        assert done_event["status"] == "reached_max_loops"
        assert done_event["passed"] is False
        assert done_event["round"] == 2

    def test_stream_retry_count_is_capped(self, monkeypatch):
        ws, fake_rewrite, fake_review = self._mock_dependencies(monkeypatch, [False, False, True])
        service = ws.WorkflowService()

        events = list(
            service.run_stream(
                source_article="原文",
                style_id=1,
                target_words=200,
                enable_rag=False,
                max_retries=99,
            )
        )

        done_event = next(e for e in events if e.get("type") == "done")
        assert done_event["status"] == "reached_max_loops"
        assert done_event["round"] == 2
        assert done_event["max_retries"] == 1
        assert len(fake_rewrite.calls) == 2
        assert len(fake_review.create_calls) == 2
