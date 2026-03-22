"""
LangGraph 工作流编排 - 改写 → 审核 → 用户选择 → 封面生成
"""
import json
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END
from sqlmodel import Session, create_engine, select

from write_agent.core import get_settings, get_logger
from write_agent.models import RewriteRecord, ReviewRecord
from write_agent.observability import bind_entities, emit_obs_event, obs_scope

logger = get_logger(__name__)
settings = get_settings()

# 创建数据库引擎
engine = create_engine(settings.database_url, echo=False)
AUTO_REVIEW_MAX_RETRIES = 1


# ============ 状态定义 ============

class WritingState(TypedDict):
    """写作工作流状态"""

    # 输入
    source_article: str          # 原文
    style_id: int               # 写作风格ID
    target_words: int           # 目标字数
    enable_rag: bool            # 是否启用RAG

    # 中间状态
    rewritten_content: str       # 改写后内容
    review_result: str          # 审核结果 (pending/passed/failed)
    review_feedback: str        # 审核意见（JSON）
    review_score: int           # 审核评分
    rewrite_id: int            # 改写记录ID
    review_id: int              # 审核记录ID

    # 用户决策（审核通过后）
    user_decision: str          # 用户决策 (pending/manual_edit/skip_to_cover)
    manual_edit_content: str    # 用户手动编辑的内容

    # 控制
    retry_count: int            # 重试次数
    max_retries: int           # 最大重试次数
    current_step: str           # 当前步骤


# ============ 节点函数 ============

def node_rewrite(state: WritingState) -> WritingState:
    """
    改写节点：调用改写服务生成文章
    """
    from write_agent.services.rewrite_service import get_rewrite_service

    logger.info(f"[LangGraph] 执行改写节点，retry_count={state['retry_count']}")

    rewrite_service = get_rewrite_service()

    # 获取风格信息
    with Session(engine) as session:
        from write_agent.models import WritingStyle
        style = session.get(WritingStyle, state["style_id"])
        style_context = style.to_summary() if style else ""

    # 创建改写记录
    record = rewrite_service.create_rewrite(
        source_article=state["source_article"],
        style_id=state["style_id"],
        target_words=state["target_words"],
        enable_rag=state["enable_rag"],
    )

    # 执行改写（收集完整内容）
    full_content = ""
    for chunk in rewrite_service.rewrite(record.id):
        data = json.loads(chunk)
        if data.get("type") == "content":
            full_content += data.get("delta", "")
        elif data.get("type") == "done":
            full_content = data.get("final_content", full_content)

    state["rewritten_content"] = full_content
    state["rewrite_id"] = record.id
    state["current_step"] = "rewrite"

    return state


def node_review(state: WritingState) -> WritingState:
    """
    审核节点：调用审核服务
    """
    from write_agent.services.review_service import get_review_service

    logger.info(f"[LangGraph] 执行审核节点")

    review_service = get_review_service()

    # 获取风格上下文
    with Session(engine) as session:
        from write_agent.models import WritingStyle
        style = session.get(WritingStyle, state["style_id"])
        style_context = style.to_summary() if style else ""

    # 创建审核记录
    review_record = review_service.create_review(
        rewrite_id=state["rewrite_id"],
        content=state["rewritten_content"],
    )

    # 执行审核
    passed = False
    score = 0
    feedback = {}

    for chunk in review_service.review(review_record.id, style_context):
        data = json.loads(chunk)
        if data.get("type") == "done":
            passed = data.get("passed", False)
            score = data.get("total_score", 0)
            feedback = data

    state["review_result"] = "passed" if passed else "failed"
    state["review_feedback"] = json.dumps(feedback, ensure_ascii=False)
    state["review_score"] = score
    state["review_id"] = review_record.id

    # 如果不通过，增加重试计数
    if not passed:
        state["retry_count"] = state.get("retry_count", 0) + 1

    state["current_step"] = "review"

    return state


def node_decision(state: WritingState) -> WritingState:
    """
    决策节点：审核通过后，等待用户选择

    注意：这个节点会设置状态为 "waiting_decision"
    前端需要轮询或等待此状态，然后询问用户选择
    """
    logger.info(f"[LangGraph] 执行决策节点，等待用户选择")

    # 设置为等待决策状态
    state["user_decision"] = "pending"
    state["current_step"] = "decision"

    return state


def node_manual_edit(state: WritingState) -> WritingState:
    """
    人工编辑节点：用户手动编辑内容
    """
    logger.info(f"[LangGraph] 执行人工编辑节点")

    # 用户手动编辑的内容已经在 state["manual_edit_content"] 中
    # 更新 RewriteRecord 的 final_content
    with Session(engine) as session:
        rewrite_record = session.get(RewriteRecord, state["rewrite_id"])
        if rewrite_record:
            rewrite_record.final_content = state["manual_edit_content"]
            session.commit()

    state["rewritten_content"] = state["manual_edit_content"]
    state["current_step"] = "manual_edit"

    return state


def node_cover(state: WritingState) -> WritingState:
    """
    封面生成节点
    """
    # TODO: Phase 6 实现
    logger.info(f"[LangGraph] 执行封面生成节点")

    state["current_step"] = "cover"
    # 暂时返回空，等 Phase 6 实现
    state["cover_image_url"] = ""

    return state


# ============ 边函数 ============

def should_continue(state: WritingState) -> str:
    """
    判断是否继续：
    - 审核通过 → 决策节点（让用户选择）
    - 审核不通过 → 返回改写
    """
    max_retries = state.get("max_retries", 3)

    # 检查审核结果
    if state.get("review_result") == "passed":
        return "decision"  # 去决策节点

    # 检查重试次数
    retry_count = state.get("retry_count", 0)
    if retry_count >= max_retries:
        logger.warning(f"达到最大重试次数 {max_retries}，结束工作流")
        return "end"

    # 审核不通过，返回改写节点重试
    return "rewrite"


def after_decision(state: WritingState) -> str:
    """
    决策节点后的分支：
    - 用户选择人工编辑 → 人工编辑节点
    - 用户选择跳过 → 封面节点
    """
    decision = state.get("user_decision", "pending")

    if decision == "manual_edit":
        return "manual_edit"
    elif decision == "skip_to_cover":
        return "cover"
    else:
        # 默认跳过（不应该走到这里）
        logger.warning(f"用户决策未知: {decision}，默认跳过到封面")
        return "cover"


# ============ 构建图 ============

def create_workflow() -> StateGraph:
    """
    创建工作流图
    """
    workflow = StateGraph(WritingState)

    # 添加节点
    workflow.add_node("rewrite", node_rewrite)
    workflow.add_node("review", node_review)
    workflow.add_node("decision", node_decision)
    workflow.add_node("manual_edit", node_manual_edit)
    workflow.add_node("cover", node_cover)

    # 设置入口
    workflow.set_entry_point("rewrite")

    # 添加边
    workflow.add_edge("rewrite", "review")

    # 审核后的条件边
    workflow.add_conditional_edges(
        "review",
        should_continue,
        {
            "decision": "decision",  # 通过 → 决策
            "rewrite": "rewrite",   # 不通过 → 重写
            "end": END,            # 超限 → 结束
        }
    )

    # 决策后的条件边
    workflow.add_conditional_edges(
        "decision",
        after_decision,
        {
            "manual_edit": "manual_edit",  # 用户选择编辑
            "cover": "cover",              # 用户选择跳过
        }
    )

    # 人工编辑后 → 封面
    workflow.add_edge("manual_edit", "cover")

    # 封面 → 结束
    workflow.add_edge("cover", END)

    return workflow


# ============ 执行入口 ============

class WorkflowService:
    """工作流服务"""

    def __init__(self):
        self.graph = create_workflow().compile()
        logger.info("LangGraph 工作流初始化完成")
        # 用于存储工作流状态（实际应该用 Redis 或数据库）
        self._states = {}

    def run(
        self,
        source_article: str,
        style_id: int,
        target_words: int = 1000,
        enable_rag: bool = False,
        max_retries: int = 3,
    ) -> WritingState:
        """
        执行完整工作流（直到决策节点暂停）
        """
        initial_state: WritingState = self._create_initial_state(
            source_article=source_article,
            style_id=style_id,
            target_words=target_words,
            enable_rag=enable_rag,
            max_retries=max_retries,
        )

        # 执行工作流
        final_state = self.graph.invoke(initial_state)

        # 如果到达决策节点，保存状态等待用户决策
        if final_state.get("current_step") == "decision":
            workflow_id = f"workflow_{final_state.get('rewrite_id')}"
            self._states[workflow_id] = final_state
            logger.info(f"工作流已暂停在决策节点，等待用户选择: {workflow_id}")

        logger.info(f"工作流完成，最终状态: {final_state.get('current_step')}")
        return final_state

    def run_stream(
        self,
        source_article: str,
        style_id: int,
        target_words: int = 1000,
        enable_rag: bool = False,
        rag_top_k: int = 3,
        max_retries: int = 1,
    ):
        """
        流式执行改写-审核闭环：
        首稿 -> 首审 -> (不通过) 二次修订 -> 二审 -> 结束
        """
        with obs_scope("SVC.WORKFLOW.RUN_STREAM", "WORKFLOW_NODE"):
            from write_agent.services.rewrite_service import get_rewrite_service
            from write_agent.services.review_service import get_review_service
            from write_agent.models import WritingStyle

            rewrite_service = get_rewrite_service()
            review_service = get_review_service()

            retries = min(max(0, max_retries), AUTO_REVIEW_MAX_RETRIES)
            total_rounds = retries + 1

            with Session(engine) as session:
                style = session.get(WritingStyle, style_id)
                style_context = style.to_summary() if style else ""

            rewrite_record = rewrite_service.create_rewrite(
                source_article=source_article,
                style_id=style_id,
                target_words=target_words,
                enable_rag=enable_rag,
                rag_top_k=rag_top_k,
            )
            rewrite_id = rewrite_record.id
            bind_entities({"rewrite_id": rewrite_id})
            emit_obs_event(
                level="INFO",
                message="svc.workflow.run_stream.start",
                entities={"rewrite_id": rewrite_id},
                payload={"total_rounds": total_rounds, "retries": retries},
            )

            current_content = ""
            latest_review_id = 0
            latest_review_feedback = ""

            for round_num in range(1, total_rounds + 1):
            # ========== 改写阶段 ==========
                yield {
                    "type": "stage",
                    "stage": "rewrite",
                    "round": round_num,
                    "rewrite_id": rewrite_id,
                    "retry_count": round_num - 1,
                    "max_retries": retries,
                    "message": "正在改写..." if round_num == 1 else "根据主编意见进行二次写稿...",
                }

                rewrite_kwargs = {}
                if round_num > 1:
                    rewrite_kwargs = {
                        "revision_base_content": current_content,
                        "review_feedback": latest_review_feedback,
                    }

                rewrite_done = False
                actual_words = 0

                for chunk in rewrite_service.rewrite(rewrite_id, **rewrite_kwargs):
                    data = json.loads(chunk)
                    event_type = data.get("type")

                    if event_type == "progress":
                        yield {
                            "type": "progress",
                            "stage": "rewrite",
                            "round": round_num,
                            "rewrite_id": rewrite_id,
                            "message": data.get("message", ""),
                        }
                        continue

                    if event_type == "content":
                        yield {
                            "type": "content",
                            "stage": "rewrite",
                            "round": round_num,
                            "rewrite_id": rewrite_id,
                            "delta": data.get("delta", ""),
                        }
                        continue

                    if event_type == "done":
                        rewrite_done = True
                        current_content = str(data.get("final_content", ""))
                        actual_words = int(data.get("actual_words", 0) or 0)
                        break

                    if event_type == "error":
                        yield {
                            "type": "error",
                            "stage": "rewrite",
                            "round": round_num,
                            "rewrite_id": rewrite_id,
                            "message": data.get("message", "改写失败"),
                        }
                        return

                if not rewrite_done:
                    yield {
                        "type": "error",
                        "stage": "rewrite",
                        "round": round_num,
                        "rewrite_id": rewrite_id,
                        "message": "改写流程未正常完成",
                    }
                    return

            # ========== 审核阶段 ==========
                yield {
                    "type": "stage",
                    "stage": "review",
                    "round": round_num,
                    "rewrite_id": rewrite_id,
                    "retry_count": round_num - 1,
                    "max_retries": retries,
                    "message": "主编审核中..." if round_num == 1 else "主编二次审核中...",
                    "actual_words": actual_words,
                }

                review_record = review_service.create_review(
                    rewrite_id=rewrite_id,
                    content=current_content,
                )
                latest_review_id = review_record.id
                bind_entities({"rewrite_id": rewrite_id, "review_id": latest_review_id, "round": round_num})

                review_done = False
                passed = False
                total_score = 0
                reason = ""
                review_payload: dict = {}

                for chunk in review_service.review(latest_review_id, style_context):
                    data = json.loads(chunk)
                    event_type = data.get("type")

                    if event_type == "done":
                        review_done = True
                        passed = bool(data.get("passed", False))
                        total_score = int(data.get("total_score", 0) or 0)
                        reason = str(data.get("result", "审核完成"))
                        review_payload = data
                        break

                    if event_type == "error":
                        yield {
                            "type": "error",
                            "stage": "review",
                            "round": round_num,
                            "rewrite_id": rewrite_id,
                            "review_id": latest_review_id,
                            "message": data.get("message", "审核失败"),
                        }
                        return

                if not review_done:
                    yield {
                        "type": "error",
                        "stage": "review",
                        "round": round_num,
                        "rewrite_id": rewrite_id,
                        "review_id": latest_review_id,
                        "message": "审核流程未正常完成",
                    }
                    return

                latest_review_feedback = json.dumps(review_payload, ensure_ascii=False)

                yield {
                    "type": "review_done",
                    "stage": "review",
                    "round": round_num,
                    "rewrite_id": rewrite_id,
                    "review_id": latest_review_id,
                    "passed": passed,
                    "score": total_score,
                    "reason": reason,
                    "retry_count": round_num - 1,
                    "max_retries": retries,
                }

                if passed:
                    emit_obs_event(
                        level="INFO",
                        message="svc.workflow.run_stream.passed",
                        entities={
                            "rewrite_id": rewrite_id,
                            "review_id": latest_review_id,
                            "round": round_num,
                        },
                    )
                    yield {
                        "type": "done",
                        "status": "passed",
                        "passed": True,
                        "rewrite_id": rewrite_id,
                        "review_id": latest_review_id,
                        "round": round_num,
                        "retry_count": round_num - 1,
                        "max_retries": retries,
                    }
                    return

            emit_obs_event(
                level="WARNING",
                message="svc.workflow.run_stream.max_loops",
                entities={"rewrite_id": rewrite_id, "review_id": latest_review_id},
                error_code="E_WORKFLOW_MAX_LOOPS",
            )
            yield {
                "type": "done",
                "status": "reached_max_loops",
                "passed": False,
                "rewrite_id": rewrite_id,
                "review_id": latest_review_id,
                "round": total_rounds,
                "retry_count": retries,
                "max_retries": retries,
            }

    def resume_with_manual_edit(
        self,
        rewrite_id: int,
        edited_content: str,
    ) -> WritingState:
        """
        用户选择人工编辑，继续工作流
        """
        workflow_id = f"workflow_{rewrite_id}"

        if workflow_id not in self._states:
            raise ValueError(f"找不到工作流状态: {workflow_id}")

        # 获取之前的状态
        state = self._states[workflow_id]
        state["user_decision"] = "manual_edit"
        state["manual_edit_content"] = edited_content

        # 继续执行
        final_state = self.graph.invoke(state, node_name="manual_edit")

        # 清理状态
        del self._states[workflow_id]

        return final_state

    def resume_skip_to_cover(
        self,
        rewrite_id: int,
    ) -> WritingState:
        """
        用户选择跳过人工编辑，直接进入封面
        """
        workflow_id = f"workflow_{rewrite_id}"

        if workflow_id not in self._states:
            raise ValueError(f"找不到工作流状态: {workflow_id}")

        # 获取之前的状态
        state = self._states[workflow_id]
        state["user_decision"] = "skip_to_cover"

        # 继续执行
        final_state = self.graph.invoke(state, node_name="cover")

        # 清理状态
        del self._states[workflow_id]

        return final_state

    def _create_initial_state(
        self,
        source_article: str,
        style_id: int,
        target_words: int,
        enable_rag: bool,
        max_retries: int,
    ) -> WritingState:
        """创建初始状态"""
        return {
            "source_article": source_article,
            "style_id": style_id,
            "target_words": target_words,
            "enable_rag": enable_rag,
            "rewritten_content": "",
            "review_result": "",
            "review_feedback": "",
            "review_score": 0,
            "rewrite_id": 0,
            "review_id": 0,
            "user_decision": "",
            "manual_edit_content": "",
            "retry_count": 0,
            "max_retries": max_retries,
            "current_step": "",
        }


# 全局单例
_workflow_service: Optional[WorkflowService] = None


def get_workflow_service() -> WorkflowService:
    """获取工作流服务单例"""
    global _workflow_service
    if _workflow_service is None:
        _workflow_service = WorkflowService()
    return _workflow_service
