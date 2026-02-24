"""
LangGraph 工作流测试
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
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
os.environ["MINIMAX_API_KEY"] = "test-key"
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
