"""
文章改写 API 路由
"""
import json
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from write_agent.observability import (
    attach_obs_meta,
    bind_entities,
    emit_obs_event,
    obs_scope,
)
from write_agent.services.rewrite_service import get_rewrite_service
from write_agent.services.material_service import get_material_service

router = APIRouter(prefix="/rewrites", tags=["文章改写"])

# 服务实例
rewrite_service = get_rewrite_service()
material_service = get_material_service()


# ============ 请求/响应模型 ============

class CreateRewriteRequest(BaseModel):
    """创建改写请求"""
    source_article: str
    style_id: int
    target_words: int = 1000
    enable_rag: bool = False
    rag_top_k: int = 3


class RewriteResponse(BaseModel):
    """改写响应"""
    id: int
    source_article: str
    final_content: str
    style_id: int
    target_words: int
    actual_words: int
    enable_rag: bool
    rag_retrieved: Optional[str]
    status: str
    created_at: str


class RewriteListResponse(BaseModel):
    """改写历史响应"""
    items: list[dict]
    total: int
    page: int
    limit: int


# ============ API 接口 ============


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _rewrite_sse_with_obs(raw_chunk: str, *, rewrite_id: int) -> str:
    try:
        payload = json.loads(raw_chunk)
    except Exception:
        payload = {"type": "content", "delta": raw_chunk}
    payload.setdefault("rewrite_id", rewrite_id)
    enriched = attach_obs_meta(
        payload,
        node_key="API.REWRITES.SSE_EVENT",
        behavior_key="HTTP_SSE_STREAM",
        entities={"rewrite_id": rewrite_id},
    )
    return _sse_event(enriched)

@router.post("")
async def create_rewrite(request: CreateRewriteRequest):
    """
    发起改写（SSE 流式输出）

    使用流式响应，逐块返回改写内容
    """
    with obs_scope("API.REWRITES.CREATE", "HTTP_SYNC"):
        try:
            if not request.source_article:
                raise HTTPException(status_code=400, detail="请输入文章内容")

            if request.target_words < 100 or request.target_words > 10000:
                raise HTTPException(status_code=400, detail="目标字数应在 100-10000 之间")

            record = rewrite_service.create_rewrite(
                source_article=request.source_article,
                style_id=request.style_id,
                target_words=request.target_words,
                enable_rag=request.enable_rag,
                rag_top_k=request.rag_top_k,
            )
            bind_entities({"rewrite_id": record.id})
            emit_obs_event(
                level="INFO",
                message="api.rewrites.create",
                entities={"rewrite_id": record.id},
                payload={
                    "style_id": request.style_id,
                    "target_words": request.target_words,
                    "enable_rag": request.enable_rag,
                    "rag_top_k": request.rag_top_k,
                },
            )

            def generate():
                yield _sse_event(
                    attach_obs_meta(
                        {"type": "start", "task_id": record.id, "rewrite_id": record.id},
                        node_key="API.REWRITES.SSE_EVENT",
                        behavior_key="HTTP_SSE_STREAM",
                        entities={"rewrite_id": record.id},
                    )
                )
                for chunk in rewrite_service.rewrite(record.id):
                    yield _rewrite_sse_with_obs(chunk, rewrite_id=record.id)

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
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=RewriteListResponse)
async def get_rewrites(
    style_id: Optional[int] = None,
    page: int = 1,
    limit: int = 20,
):
    """获取改写历史"""
    try:
        records, total = rewrite_service.get_rewrites(
            style_id=style_id,
            page=page,
            limit=limit,
        )

        # 获取风格名称
        from sqlmodel import Session
        from write_agent.models import WritingStyle
        from write_agent.core.database import engine

        items = []
        with Session(engine) as session:
            for r in records:
                style = session.get(WritingStyle, r.style_id)
                style_name = style.name if style else "未知"
                items.append({
                    "id": r.id,
                    "source_article": r.source_article,
                    "final_content": r.final_content,
                    "style_name": style_name,
                    "target_words": r.target_words,
                    "actual_words": r.actual_words,
                    "status": r.status,
                    "error_message": r.error_message,
                    "created_at": r.created_at.isoformat(),
                })

        return RewriteListResponse(
            items=items,
            total=total,
            page=page,
            limit=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream")
async def rewrite_stream(
    source_article: str,
    style_id: int = 0,
    target_words: int = 1000,
    enable_rag: bool = False,
    rag_top_k: int = 3,
):
    """
    SSE 流式改写（GET 方法）

    使用流式响应，逐块返回改写内容
    """
    with obs_scope("API.REWRITES.STREAM", "HTTP_SSE_STREAM"):
        try:
            if not source_article:
                raise HTTPException(status_code=400, detail="请输入文章内容")

            if target_words < 100 or target_words > 10000:
                raise HTTPException(status_code=400, detail="目标字数应在 100-10000 之间")

            record = rewrite_service.create_rewrite(
                source_article=source_article,
                style_id=style_id,
                target_words=target_words,
                enable_rag=enable_rag,
                rag_top_k=rag_top_k,
            )
            bind_entities({"rewrite_id": record.id})
            emit_obs_event(
                level="INFO",
                message="api.rewrites.stream",
                entities={"rewrite_id": record.id},
                payload={
                    "style_id": style_id,
                    "target_words": target_words,
                    "enable_rag": enable_rag,
                    "rag_top_k": rag_top_k,
                },
            )

            def generate():
                yield _sse_event(
                    attach_obs_meta(
                        {"type": "start", "task_id": record.id, "rewrite_id": record.id},
                        node_key="API.REWRITES.SSE_EVENT",
                        behavior_key="HTTP_SSE_STREAM",
                        entities={"rewrite_id": record.id},
                    )
                )
                for chunk in rewrite_service.rewrite(record.id):
                    yield _rewrite_sse_with_obs(chunk, rewrite_id=record.id)

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
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/{rewrite_id:int}", response_model=RewriteResponse)
async def get_rewrite(rewrite_id: int):
    """获取改写详情"""
    record = rewrite_service.get_rewrite(rewrite_id)
    if not record:
        raise HTTPException(status_code=404, detail="改写记录不存在")

    return RewriteResponse(
        id=record.id,
        source_article=record.source_article,
        final_content=record.final_content,
        style_id=record.style_id,
        target_words=record.target_words,
        actual_words=record.actual_words,
        enable_rag=record.enable_rag,
        rag_retrieved=record.rag_retrieved,
        status=record.status,
        created_at=record.created_at.isoformat(),
    )
