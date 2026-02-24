"""
写作风格 API 路由
"""
import json
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from write_agent.services.style_service import get_style_service
from write_agent.core import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/styles", tags=["写作风格"])

# 服务实例
style_service = get_style_service()


# ============ 请求/响应模型 ============

class ExtractStyleRequest(BaseModel):
    """提取风格请求"""
    articles: list[str]  # 参考文章列表
    style_name: str     # 风格名称
    tags: Optional[str] = None  # 标签


class StyleResponse(BaseModel):
    """风格响应"""
    id: int
    name: str
    style_description: str
    tags: Optional[str]
    created_at: str


# ============ API 接口 ============

def _normalize_articles(articles: list[str]) -> list[str]:
    """过滤空文章并去除前后空白。"""
    return [article.strip() for article in articles if article and article.strip()]


@router.post("/extract", response_model=StyleResponse)
async def extract_style(request: ExtractStyleRequest):
    """
    从参考文章中提取写作风格

    用户输入多篇文章 → LLM 分析 → 提取风格 → 存储
    """
    try:
        articles = _normalize_articles(request.articles)
        style_name = request.style_name.strip()

        logger.info(f"提取风格: {style_name}, 文章数: {len(articles)}")

        # 参数验证
        if not articles:
            raise HTTPException(status_code=400, detail="请提供至少一篇参考文章")

        if not style_name:
            raise HTTPException(status_code=400, detail="请提供风格名称")

        # 提取风格
        style = style_service.extract_style(
            articles=articles,
            style_name=style_name,
            tags=request.tags,
        )

        return StyleResponse(
            id=style.id,
            name=style.name,
            style_description=style.style_description,
            tags=style.tags,
            created_at=style.created_at.isoformat(),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"提取风格失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract/stream")
async def extract_style_stream(request: ExtractStyleRequest):
    """流式提取风格，实时返回分析进度。"""
    articles = _normalize_articles(request.articles)
    style_name = request.style_name.strip()

    if not articles:
        raise HTTPException(status_code=400, detail="请提供至少一篇参考文章")

    if not style_name:
        raise HTTPException(status_code=400, detail="请提供风格名称")

    def generate():
        for event in style_service.extract_style_stream(
            articles=articles,
            style_name=style_name,
            tags=request.tags,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=list[StyleResponse])
async def get_all_styles():
    """获取所有写作风格"""
    try:
        styles = style_service.get_all_styles()
        return [
            StyleResponse(
                id=s.id,
                name=s.name,
                style_description=s.style_description,
                tags=s.tags,
                created_at=s.created_at.isoformat(),
            )
            for s in styles
        ]
    except Exception as e:
        logger.error(f"获取风格列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{style_id}", response_model=StyleResponse)
async def get_style(style_id: int):
    """根据ID获取写作风格"""
    style = style_service.get_style_by_id(style_id)
    if not style:
        raise HTTPException(status_code=404, detail="风格不存在")

    return StyleResponse(
        id=style.id,
        name=style.name,
        style_description=style.style_description,
        tags=style.tags,
        created_at=style.created_at.isoformat(),
    )


@router.delete("/{style_id}")
async def delete_style(style_id: int):
    """删除写作风格"""
    success = style_service.delete_style(style_id)
    if not success:
        raise HTTPException(status_code=404, detail="风格不存在")

    return {"status": "ok", "message": "删除成功"}
