"""
审核 API 路由
"""
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from write_agent.observability import (
    attach_obs_meta,
    bind_entities,
    emit_obs_event,
    obs_scope,
)
from write_agent.services.review_service import get_review_service
from write_agent.services.workflow_job_service import get_workflow_job_service
from write_agent.services.workflow_service import get_workflow_service

router = APIRouter(prefix="/reviews", tags=["文章审核"])
logger = logging.getLogger(__name__)

# 服务实例
review_service = get_review_service()
workflow_service = get_workflow_service()
workflow_job_service = get_workflow_job_service()


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
    rag_top_k: int = 3
    max_retries: int = 1
    idempotency_key: Optional[str] = None
    force_new: bool = False


class CreateWorkflowJobResponse(BaseModel):
    job_id: int
    status: str
    idempotent_hit: bool = False
    rewrite_id: Optional[int] = None
    checkpoint_seq: int = 0


class WorkflowJobStatusResponse(BaseModel):
    job_id: int
    status: str
    current_stage: str
    checkpoint_stage: str
    checkpoint_seq: int
    resume_count: int
    rewrite_id: Optional[int] = None
    review_id: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


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


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _review_sse_with_obs(
    raw_chunk: str | dict,
    *,
    rewrite_id: Optional[int] = None,
    review_id: Optional[int] = None,
) -> str:
    if isinstance(raw_chunk, dict):
        payload = dict(raw_chunk)
    else:
        try:
            payload = json.loads(raw_chunk)
        except Exception:
            payload = {"type": "content", "delta": str(raw_chunk)}
    if rewrite_id is not None and "rewrite_id" not in payload:
        payload["rewrite_id"] = rewrite_id
    if review_id is not None and "review_id" not in payload:
        payload["review_id"] = review_id
    enriched = attach_obs_meta(
        payload,
        node_key="API.REVIEWS.SSE_EVENT",
        behavior_key="HTTP_SSE_STREAM",
        entities={
            "rewrite_id": rewrite_id,
            "review_id": review_id,
            "round": payload.get("round"),
            "stage": payload.get("stage"),
        },
    )
    return _sse_event(enriched)


def _workflow_job_to_status(job) -> WorkflowJobStatusResponse:
    return WorkflowJobStatusResponse(
        job_id=job.id,
        status=job.status,
        current_stage=job.current_stage,
        checkpoint_stage=job.checkpoint_stage,
        checkpoint_seq=job.checkpoint_seq,
        resume_count=job.resume_count,
        rewrite_id=job.rewrite_id,
        review_id=job.review_id,
        error_code=job.error_code,
        error_message=job.error_message,
    )

@router.post("")
async def create_review(request: CreateReviewRequest):
    """
    发起审核（SSE 流式输出）
    """
    with obs_scope("API.REVIEWS.CREATE", "HTTP_SYNC"):
        try:
            from write_agent.services.rewrite_service import get_rewrite_service

            rewrite_service = get_rewrite_service()
            rewrite_record = rewrite_service.get_rewrite(request.rewrite_id)
            if not rewrite_record:
                raise HTTPException(status_code=404, detail="改写记录不存在")
            if not rewrite_record.final_content:
                raise HTTPException(status_code=400, detail="改写内容为空")

            record = review_service.create_review(
                rewrite_id=request.rewrite_id,
                content=rewrite_record.final_content,
            )
            bind_entities({"rewrite_id": request.rewrite_id, "review_id": record.id})
            emit_obs_event(
                level="INFO",
                message="api.reviews.create",
                entities={"rewrite_id": request.rewrite_id, "review_id": record.id},
            )

            from sqlmodel import Session
            from write_agent.models import WritingStyle
            from write_agent.core.database import engine

            style_context = ""
            with Session(engine) as session:
                style = session.get(WritingStyle, rewrite_record.style_id)
                if style:
                    style_context = style.to_summary()

            def generate():
                yield _review_sse_with_obs(
                    {"type": "start", "review_id": record.id, "rewrite_id": request.rewrite_id},
                    rewrite_id=request.rewrite_id,
                    review_id=record.id,
                )
                for chunk in review_service.review(record.id, style_context):
                    yield _review_sse_with_obs(
                        chunk,
                        rewrite_id=request.rewrite_id,
                        review_id=record.id,
                    )

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
    with obs_scope("API.REVIEWS.WORKFLOW", "HTTP_SSE_STREAM"):
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

            emit_obs_event(
                level="INFO",
                message="api.reviews.workflow",
                payload={
                    "style_id": request.style_id,
                    "target_words": request.target_words,
                    "enable_rag": request.enable_rag,
                    "rag_top_k": request.rag_top_k,
                    "max_retries": request.max_retries,
                },
            )

            def generate():
                try:
                    # 旧接口桥接到任务引擎：每次调用默认创建新任务（兼容旧语义）
                    job, _ = workflow_job_service.create_job(
                        source_article=request.source_article,
                        style_id=request.style_id,
                        target_words=request.target_words,
                        enable_rag=request.enable_rag,
                        rag_top_k=request.rag_top_k,
                        max_retries=1,
                        idempotency_key=request.idempotency_key,
                        force_new=True if not request.force_new else request.force_new,
                    )
                    for event in workflow_job_service.stream_events(job.id, from_seq=0):
                        rewrite_id = event.get("rewrite_id")
                        review_id = event.get("review_id")
                        if rewrite_id or review_id:
                            bind_entities(
                                {"rewrite_id": rewrite_id, "review_id": review_id}
                            )
                        yield _review_sse_with_obs(
                            event,
                            rewrite_id=rewrite_id,
                            review_id=review_id,
                        )
                        if event.get("type") in {"done", "error"}:
                            break
                except Exception as e:
                    logger.error("工作流流式执行失败: %s", e, exc_info=True)
                    yield _review_sse_with_obs({"type": "error", "message": str(e)})

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


@router.post("/workflow/jobs", response_model=CreateWorkflowJobResponse)
async def create_workflow_job(request: CreateWorkflowRequest):
    """创建异步工作流任务。"""
    with obs_scope("API.REVIEWS.WORKFLOW_JOBS_CREATE", "HTTP_SYNC"):
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

            job, idempotent_hit = workflow_job_service.create_job(
                source_article=request.source_article,
                style_id=request.style_id,
                target_words=request.target_words,
                enable_rag=request.enable_rag,
                rag_top_k=request.rag_top_k,
                max_retries=1,
                idempotency_key=request.idempotency_key,
                force_new=request.force_new,
            )
            bind_entities({"rewrite_id": job.rewrite_id, "review_id": job.review_id})
            emit_obs_event(
                level="INFO",
                message="api.reviews.workflow.jobs.create",
                payload={"job_id": job.id, "status": job.status, "idempotent_hit": idempotent_hit},
            )
            return CreateWorkflowJobResponse(
                job_id=job.id,
                status=job.status,
                idempotent_hit=idempotent_hit,
                rewrite_id=job.rewrite_id,
                checkpoint_seq=job.checkpoint_seq,
            )
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            raise HTTPException(status_code=500, detail=str(error))


@router.get("/workflow/jobs/{job_id:int}", response_model=WorkflowJobStatusResponse)
async def get_workflow_job_status(job_id: int):
    with obs_scope("API.REVIEWS.WORKFLOW_JOB_STATUS", "HTTP_SYNC"):
        job = workflow_job_service.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return _workflow_job_to_status(job)


@router.get("/workflow/jobs/by-rewrite/{rewrite_id:int}", response_model=WorkflowJobStatusResponse)
async def get_latest_workflow_job_by_rewrite(rewrite_id: int):
    with obs_scope("API.REVIEWS.WORKFLOW_JOB_STATUS", "HTTP_SYNC"):
        job = workflow_job_service.get_latest_job_by_rewrite(rewrite_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return _workflow_job_to_status(job)


@router.get("/workflow/jobs/{job_id:int}/stream")
async def stream_workflow_job_events(
    job_id: int,
    from_seq: int = Query(default=0, ge=0),
):
    """SSE: 回放 + 实时推送任务事件。"""
    with obs_scope("API.REVIEWS.WORKFLOW_JOB_STREAM", "HTTP_SSE_STREAM"):
        job = workflow_job_service.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")

        def generate():
            try:
                for event in workflow_job_service.stream_events(job_id, from_seq=from_seq):
                    rewrite_id = event.get("rewrite_id")
                    review_id = event.get("review_id")
                    if rewrite_id or review_id:
                        bind_entities({"rewrite_id": rewrite_id, "review_id": review_id})
                    yield _review_sse_with_obs(
                        event,
                        rewrite_id=rewrite_id,
                        review_id=review_id,
                    )
                    if event.get("type") in {"done", "error"}:
                        break
            except Exception as error:
                logger.error("任务流输出失败: %s", error, exc_info=True)
                yield _review_sse_with_obs({"type": "error", "message": str(error)})

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


@router.post("/workflow/jobs/{job_id:int}/resume", response_model=WorkflowJobStatusResponse)
async def resume_workflow_job(job_id: int):
    with obs_scope("API.REVIEWS.WORKFLOW_JOB_RESUME", "HTTP_SYNC"):
        try:
            job = workflow_job_service.resume_job(job_id)
            emit_obs_event(
                level="INFO",
                message="api.reviews.workflow.jobs.resume",
                payload={"job_id": job.id, "status": job.status, "resume_count": job.resume_count},
            )
            return _workflow_job_to_status(job)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error))


@router.post("/workflow/jobs/{job_id:int}/cancel", response_model=WorkflowJobStatusResponse)
async def cancel_workflow_job(job_id: int):
    with obs_scope("API.REVIEWS.WORKFLOW_JOB_CANCEL", "HTTP_SYNC"):
        try:
            job = workflow_job_service.cancel_job(job_id)
            emit_obs_event(
                level="INFO",
                message="api.reviews.workflow.jobs.cancel",
                payload={"job_id": job.id, "status": job.status},
            )
            return _workflow_job_to_status(job)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error))


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
    with obs_scope("API.REVIEWS.CREATE", "HTTP_SSE_STREAM"):
        try:
            from write_agent.services.rewrite_service import get_rewrite_service

            rewrite_service = get_rewrite_service()
            rewrite_record = rewrite_service.get_rewrite(rewrite_id)
            if not rewrite_record:
                raise HTTPException(status_code=404, detail="改写记录不存在")
            if not rewrite_record.final_content:
                raise HTTPException(status_code=400, detail="改写内容为空")

            record = review_service.create_review(
                rewrite_id=rewrite_id,
                content=rewrite_record.final_content,
            )
            bind_entities({"rewrite_id": rewrite_id, "review_id": record.id})

            from sqlmodel import Session
            from write_agent.models import WritingStyle
            from write_agent.core.database import engine

            style_context = ""
            with Session(engine) as session:
                style = session.get(WritingStyle, rewrite_record.style_id)
                if style:
                    style_context = style.to_summary()

            def generate():
                yield _review_sse_with_obs(
                    {"type": "start", "review_id": record.id, "rewrite_id": rewrite_id},
                    rewrite_id=rewrite_id,
                    review_id=record.id,
                )
                for chunk in review_service.review(record.id, style_context):
                    yield _review_sse_with_obs(
                        chunk,
                        rewrite_id=rewrite_id,
                        review_id=record.id,
                    )

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
