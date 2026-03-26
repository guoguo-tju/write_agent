"""
审核服务 - 基于 LangChain + 主编审稿 Skill
"""
import json
from datetime import datetime
from typing import Optional
from sqlmodel import Session, create_engine, select

from write_agent.core import get_settings, get_logger
from write_agent.models.review_record import ReviewRecord
from write_agent.observability import bind_entities, emit_obs_event, obs_scope

logger = get_logger(__name__)
settings = get_settings()

# 创建数据库引擎
engine = create_engine(settings.database_url, echo=False)


# 审核 System Prompt（基于主编审稿 Skill）
REVIEW_SYSTEM_PROMPT = """你是顶级写作主编，负责对文章进行主编级审稿。

## 核心职责
1. 诊断文章问题
2. 输出带优先级的可执行修改清单
3. 对改写后的文本进行质量评分

## 审核维度（按优先级排序）

### 1. AI味道检测（最高优先级！）
这是审稿的第一要务。如果文章一眼看上去就是AI写的，其他一切都没有意义。

**典型AI病症清单：**
- 小标题病：每隔两三段就来一个加粗小标题
- 格式洁癖：段落长度高度一致
- 排比上瘾："第一...第二...第三..."
- 加粗狂魔：关键词全加粗
- 开头套路："在当今社会..."、"随着...的发展..."
- 结尾升华：假大空总结
- 情感断层：情绪转折生硬
- 同义词强迫症：刻意避免重复反而暴露AI

**AI高频词（禁止使用）：**
"此外""然而""至关重要""赋能""抓手""深入探讨""关键性的"

### 2. 深度诊断维度
- 篇幅冗余：离题内容、重复论据
- 节奏律动：句式与段落长度变化
- 内容重复：同一观点反复出现
- 教科书味：抽象概念缺乏具象场景

### 3. 质量评分（5维度，各10分）

| 维度 | 评估标准 | 得分 |
|------|----------|------|
| 直接性 | 直接陈述事实还是绕圈宣告？10分：直截了当 | /10 |
| 节奏 | 句子长度是否变化？10分：长短交错 | /10 |
| 信任度 | 是否尊重读者智慧？10分：简洁明了 | /10 |
| 真实性 | 听起来像真人说话吗？10分：自然流畅 | /10 |
| 精炼度 | 还有可删减的内容吗？10分：无冗余 | /10 |

**评分标准：**
- 45-50 分：优秀，已去除 AI 痕迹
- 35-44 分：良好，仍有改进空间
- 低于 35 分：需要重新修订

## 输出格式要求

你必须以 JSON 格式输出审核结果，包含以下字段：

```json
{
  "ai_detection": {
    "has_ai_smell": true/false,
    "issues": ["具体问题描述..."],
    "examples": ["问题所在的具体句子..."]
  },
  "quality_scores": {
    "directness": 8,
    "rhythm": 7,
    "trust": 8,
    "authenticity": 6,
    "conciseness": 7,
    "total": 36
  },
  "issues": [
    {
      "type": "ai_smell/structure/logic/tyle",
      "severity": "critical/major/minor",
      "location": "具体位置，如：第2段",
      "description": "问题描述",
      "suggestion": "修改建议"
    }
  ],
  "passed": true/false,
  "reason": "通过或不通过的原因"
}
```

注意：
1. 必须严格输出 JSON 格式，不要有其他内容
2. 如果 AI 味道严重（总分<35 或 AI味道检测有严重问题），passed 应为 false
3. 每指出一个问题，必须给出具体的修改建议"""


class ReviewService:
    """审核服务"""

    def __init__(self):
        # 延迟导入，避免循环依赖
        from write_agent.services.llm_service import get_llm_service
        self.llm_service = get_llm_service()

    def create_review(
        self,
        rewrite_id: int,
        content: str,
    ) -> ReviewRecord:
        """
        创建审核记录

        Args:
            rewrite_id: 关联的改写记录ID
            content: 被审核的文章内容

        Returns:
            ReviewRecord 对象
        """
        with obs_scope("SVC.REVIEW.CREATE", "WORKFLOW_NODE", entities={"rewrite_id": rewrite_id}):
            logger.info(f"创建审核记录: rewrite_id={rewrite_id}")

            with Session(engine) as session:
                statement = select(ReviewRecord).where(
                    ReviewRecord.rewrite_id == rewrite_id
                ).order_by(ReviewRecord.round.desc())
                existing = session.exec(statement).first()

                round_num = 1
                if existing:
                    round_num = existing.round + 1

                record = ReviewRecord(
                    rewrite_id=rewrite_id,
                    content=content,
                    result="pending",
                    round=round_num,
                    retry_count=0,
                    status="running",
                )
                session.add(record)
                session.commit()
                session.refresh(record)
                bind_entities({"rewrite_id": rewrite_id, "review_id": record.id, "round": round_num})
                emit_obs_event(
                    level="INFO",
                    message="svc.review.create.done",
                    entities={"rewrite_id": rewrite_id, "review_id": record.id, "round": round_num},
                )
                return record

    def review(
        self,
        review_id: int,
        style_context: str = "",
    ):
        """
        执行审核（流式输出）

        Args:
            review_id: 审核记录ID
            style_context: 写作风格上下文

        Yields:
            JSON 格式的流式输出
        """
        with obs_scope("SVC.REVIEW.STREAM", "WORKFLOW_NODE", entities={"review_id": review_id}):
            from write_agent.services.llm_service import get_llm_service

            llm_service = get_llm_service()

            with Session(engine) as session:
                record = session.get(ReviewRecord, review_id)
                if not record:
                    yield json.dumps({"type": "error", "message": "审核记录不存在"})
                    return
                rewrite_id = record.rewrite_id
                review_content = record.content
            bind_entities({"review_id": review_id, "rewrite_id": rewrite_id})
            emit_obs_event(
                level="INFO",
                message="svc.review.stream.start",
                entities={"review_id": review_id, "rewrite_id": rewrite_id},
            )

            completed = False
            try:
            # 构造 Prompt
                user_prompt = f"""请审核以下文章：

## 写作风格要求
{style_context}

## 待审核文章
{review_content}

请输出审核结果（JSON格式）："""

                full_response = ""
                for chunk in llm_service.stream(
                    system_prompt=REVIEW_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                ):
                    cleaned_chunk = chunk.replace("<think>", "").replace("</think>", "").strip()
                    if cleaned_chunk:
                        full_response += cleaned_chunk
                        yield json.dumps({"type": "content", "delta": cleaned_chunk})

                try:
                    import re

                    json_match = re.search(r'\{[\s\S]*\}', full_response)
                    if json_match:
                        feedback = json.loads(json_match.group())
                    else:
                        feedback = {"error": "无法解析响应", "raw": full_response}
                except json.JSONDecodeError as e:
                    logger.error(f"JSON 解析失败: {e}, 原始响应: {full_response}")
                    feedback = {"error": f"JSON解析失败: {str(e)}", "raw": full_response}

                ai_score = 10
                total_score = 50
                if "quality_scores" in feedback:
                    scores = feedback["quality_scores"]
                    total_score = scores.get("total", 50)
                    ai_score = scores.get("authenticity", 10)

                passed = feedback.get("passed", True)
                if total_score < 35:
                    passed = False

                with Session(engine) as session:
                    record = session.get(ReviewRecord, review_id)
                    record.feedback = json.dumps(feedback, ensure_ascii=False)
                    record.ai_score = ai_score
                    record.total_score = total_score
                    record.result = "passed" if passed else "failed"
                    record.status = "completed"
                    record.updated_at = datetime.now()
                    session.commit()

                emit_obs_event(
                    level="INFO",
                    message="svc.review.stream.done",
                    entities={"review_id": review_id, "rewrite_id": rewrite_id},
                    payload={"passed": passed, "total_score": total_score},
                )
                completed = True
                yield json.dumps({
                    "type": "done",
                    "passed": passed,
                    "total_score": total_score,
                    "ai_score": ai_score,
                    "result": feedback.get("reason", "审核完成"),
                })

            except Exception as e:
                logger.error(f"审核失败: {e}")
                emit_obs_event(
                    level="ERROR",
                    message="svc.review.stream.failed",
                    entities={"review_id": review_id},
                    error_code="E_REVIEW_FAILED",
                    payload={"error": str(e)},
                )
                with Session(engine) as session:
                    record = session.get(ReviewRecord, review_id)
                    if record:
                        record.status = "failed"
                        record.error_message = str(e)
                        record.updated_at = datetime.now()
                        session.commit()

                yield json.dumps({"type": "error", "message": str(e)})
            finally:
                if completed:
                    return
                with Session(engine) as session:
                    record = session.get(ReviewRecord, review_id)
                    if not record:
                        return
                    if record.status == "running":
                        record.status = "failed"
                        if not record.error_message:
                            record.error_message = (
                                "E_WORKFLOW_STREAM_ABORTED: stream ended without done/error"
                            )
                        record.updated_at = datetime.now()
                        session.commit()

    def get_review(self, review_id: int) -> Optional[ReviewRecord]:
        """获取审核记录"""
        with Session(engine) as session:
            return session.get(ReviewRecord, review_id)

    def get_reviews_by_rewrite(
        self,
        rewrite_id: int,
    ) -> list[ReviewRecord]:
        """获取某次改写的所有审核记录"""
        with Session(engine) as session:
            statement = select(ReviewRecord).where(
                ReviewRecord.rewrite_id == rewrite_id
            ).order_by(ReviewRecord.round.desc())
            return session.exec(statement).all()


# 全局单例
_review_service: Optional[ReviewService] = None


def get_review_service() -> ReviewService:
    """获取审核服务单例"""
    global _review_service
    if _review_service is None:
        _review_service = ReviewService()
    return _review_service
