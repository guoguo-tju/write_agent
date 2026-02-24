"""
审核 API 路由
"""
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from write_agent.services.review_service import get_review_service
from write_agent.services.workflow_service import get_workflow_service

router = APIRouter(prefix="/reviews", tags=["文章审核"])
logger = logging.getLogger(__name__)

# 服务实例
review_service = get_review_service()
workflow_service = get_workflow_service()


# ============ 请求/响应模型 ============

class CreateReviewRequest(BaseModel):
    """创建审核请求"""
    rewrite_id: int


class CreateWorkflowRequest(BaseModel):
    """创建完整工作流请求"""
    source_article: str
    style_id: int
    target_words: int = 1000
    enable_rag: bool = False
    max_retries: int = 3


class ReviewResponse(BaseModel):
    """审核响应"""
    id: int
    rewrite_id: int
    content: str
    result: str
    feedback: Optional[str]
    ai_score: Optional[int]
    total_score: Optional[int]
    round: int
    status: str
    created_at: str


class WorkflowResponse(BaseModel):
    """工作流响应"""
    rewritten_content: str
    review_result: str
    review_score: int
    review_feedback: str
    retry_count: int
    status: str


class ManualEditRequest(BaseModel):
    """手动编辑请求"""
    review_id: int
    edited_content: str
    edit_note: Optional[str] = None


class ManualEditResponse(BaseModel):
    """手动编辑响应"""
    id: int
    review_id: int
    rewrite_id: int
    original_content: str
    edited_content: str
    status: str
    created_at: str


# ============ API 接口 ============

@router.post("")
async def create_review(request: CreateReviewRequest):
    """
    发起审核（SSE 流式输出）
    """
    try:
        # 获取改写内容
        from write_agent.services.rewrite_service import get_rewrite_service
        rewrite_service = get_rewrite_service()
        rewrite_record = rewrite_service.get_rewrite(request.rewrite_id)

        if not rewrite_record:
            raise HTTPException(status_code=404, detail="改写记录不存在")

        if not rewrite_record.final_content:
            raise HTTPException(status_code=400, detail="改写内容为空")

        # 创建审核记录
        record = review_service.create_review(
            rewrite_id=request.rewrite_id,
            content=rewrite_record.final_content,
        )

        # 获取风格上下文
        from sqlmodel import Session
        from write_agent.models import WritingStyle
        from write_agent.core.database import engine

        style_context = ""
        with Session(engine) as session:
            style = session.get(WritingStyle, rewrite_record.style_id)
            if style:
                style_context = style.to_summary()

        # 流式输出
        def generate():
            yield f"data: {json.dumps({'type': 'start', 'review_id': record.id})}\n\n"

            for chunk in review_service.review(record.id, style_context):
                yield f"data: {chunk}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workflow")
async def create_workflow(request: CreateWorkflowRequest):
    """
    执行完整工作流：改写 → 审核 → [通过] 封面 / [不通过] 重写

    使用流式输出，每一步完成后立即返回
    """
    try:
        if not request.source_article or not request.source_article.strip():
            raise HTTPException(status_code=400, detail="请输入文章内容")
        if request.target_words < 100 or request.target_words > 10000:
            raise HTTPException(status_code=400, detail="目标字数应在 100-10000 之间")

        from sqlmodel import Session
        from write_agent.models import WritingStyle
        from write_agent.core.database import engine

        with Session(engine) as session:
            style = session.get(WritingStyle, request.style_id)
            if not style:
                raise HTTPException(status_code=404, detail="风格不存在")

        def generate():
            try:
                # 流式执行工作流
                for event in workflow_service.run_stream(
                    source_article=request.source_article,
                    style_id=request.style_id,
                    target_words=request.target_words,
                    enable_rag=request.enable_rag,
                    max_retries=request.max_retries,
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error("工作流流式执行失败: %s", e, exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{review_id:int}", response_model=ReviewResponse)
async def get_review(review_id: int):
    """获取审核详情"""
    record = review_service.get_review(review_id)
    if not record:
        raise HTTPException(status_code=404, detail="审核记录不存在")

    return ReviewResponse(
        id=record.id,
        rewrite_id=record.rewrite_id,
        content=record.content,
        result=record.result,
        feedback=record.feedback,
        ai_score=record.ai_score,
        total_score=record.total_score,
        round=record.round,
        status=record.status,
        created_at=record.created_at.isoformat(),
    )


@router.get("/rewrite/{rewrite_id:int}")
async def get_reviews_by_rewrite(rewrite_id: int):
    """获取某次改写的所有审核记录"""
    records = review_service.get_reviews_by_rewrite(rewrite_id)

    return {
        "items": [
            {
                "id": r.id,
                "result": r.result,
                "ai_score": r.ai_score,
                "total_score": r.total_score,
                "round": r.round,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ],
        "total": len(records),
    }


@router.get("/stream")
async def review_stream(rewrite_id: int):
    """
    SSE 流式审核（GET 方法）
    """
    try:
        # 获取改写内容
        from write_agent.services.rewrite_service import get_rewrite_service
        rewrite_service = get_rewrite_service()
        rewrite_record = rewrite_service.get_rewrite(rewrite_id)

        if not rewrite_record:
            raise HTTPException(status_code=404, detail="改写记录不存在")

        if not rewrite_record.final_content:
            raise HTTPException(status_code=400, detail="改写内容为空")

        # 创建审核记录
        record = review_service.create_review(
            rewrite_id=rewrite_id,
            content=rewrite_record.final_content,
        )

        # 获取风格上下文
        from sqlmodel import Session
        from write_agent.models import WritingStyle
        from write_agent.core.database import engine

        style_context = ""
        with Session(engine) as session:
            style = session.get(WritingStyle, rewrite_record.style_id)
            if style:
                style_context = style.to_summary()

        # 流式输出
        def generate():
            yield f"data: {json.dumps({'type': 'start', 'review_id': record.id})}\n\n"

            for chunk in review_service.review(record.id, style_context):
                yield f"data: {chunk}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/manual-edit", response_model=ManualEditResponse)
async def manual_edit(request: ManualEditRequest):
    """
    手动编辑接口

    用户手动编辑文章后，直接进入封面生成阶段（不再审核）
    """
    from datetime import datetime
    from sqlmodel import Session
    from write_agent.models import ManualEditRecord, RewriteRecord, ReviewRecord
    from write_agent.core.database import engine

    # 获取审核记录和改写记录
    with Session(engine) as session:
        review_record = session.get(ReviewRecord, request.review_id)
        if not review_record:
            raise HTTPException(status_code=404, detail="审核记录不存在")

        rewrite_record = session.get(RewriteRecord, review_record.rewrite_id)
        if not rewrite_record:
            raise HTTPException(status_code=404, detail="改写记录不存在")

        # 创建手动编辑记录
        edit_record = ManualEditRecord(
            review_id=request.review_id,
            rewrite_id=review_record.rewrite_id,
            original_content=review_record.content,
            edited_content=request.edited_content,
            edit_note=request.edit_note,
            status="approved",  # 直接标记为已确认
        )
        session.add(edit_record)

        # 更新改写记录的内容为用户编辑后的内容
        rewrite_record.final_content = request.edited_content
        rewrite_record.updated_at = datetime.now()

        session.commit()
        session.refresh(edit_record)

    return ManualEditResponse(
        id=edit_record.id,
        review_id=edit_record.review_id,
        rewrite_id=edit_record.rewrite_id,
        original_content=edit_record.original_content,
        edited_content=edit_record.edited_content,
        status=edit_record.status,
        created_at=edit_record.created_at.isoformat(),
    )


@router.get("/manual-edit/{review_id}")
async def get_manual_edit(review_id: int):
    """获取手动编辑记录"""
    from sqlmodel import Session, select
    from write_agent.models import ManualEditRecord
    from write_agent.core.database import engine

    with Session(engine) as session:
        statement = select(ManualEditRecord).where(
            ManualEditRecord.review_id == review_id
        )
        record = session.exec(statement).first()

        if not record:
            raise HTTPException(status_code=404, detail="手动编辑记录不存在")

        return ManualEditResponse(
            id=record.id,
            review_id=record.review_id,
            rewrite_id=record.rewrite_id,
            original_content=record.original_content,
            edited_content=record.edited_content,
            status=record.status,
            created_at=record.created_at.isoformat(),
        )


# ============ 工作流继续接口 ============

class WorkflowResumeRequest(BaseModel):
    """工作流继续请求"""
    rewrite_id: int
    edited_content: Optional[str] = None  # 人工编辑时使用


@router.post("/workflow/resume")
async def resume_workflow(request: WorkflowResumeRequest):
    """
    继续工作流

    用户在决策节点做出选择后调用：
    - 选择人工编辑：传入 edited_content
    - 选择跳过：不需要 edited_content
    """
    try:
        workflow_service = get_workflow_service()

        if request.edited_content:
            # 用户选择人工编辑
            result = workflow_service.resume_with_manual_edit(
                rewrite_id=request.rewrite_id,
                edited_content=request.edited_content,
            )
        else:
            # 用户选择跳过
            result = workflow_service.resume_skip_to_cover(
                rewrite_id=request.rewrite_id,
            )

        return {
            "status": "completed",
            "current_step": result.get("current_step"),
            "cover_image_url": result.get("cover_image_url", ""),
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
