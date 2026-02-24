"""
封面生成 API
"""
import json
import logging
import re
from typing import Optional, Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from write_agent.services.cover_service import get_cover_service
from write_agent.services.rewrite_service import get_rewrite_service
from write_agent.services.style_service import get_style_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/covers", tags=["covers"])


class GenerateCoverRequest(BaseModel):
    """封面生成请求"""
    rewrite_id: int
    style_id: int | None = None  # 封面风格ID
    custom_prompt: str | None = None  # 自定义提示词（优先级最高）
    size: Literal["2.35:1", "1:1", "9:16", "3:4", "1k", "2k", "4k"] = "2.35:1"


class CoverResponse(BaseModel):
    """封面响应"""
    id: int
    rewrite_id: int
    prompt: str
    image_url: Optional[str]
    size: str
    status: str
    error_message: Optional[str]
    created_at: str
    updated_at: str


class _SafePromptVars(dict):
    """模板变量安全映射：未知占位符保持原样，避免 KeyError。"""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _sse_event(data: dict) -> str:
    """格式化 SSE 事件。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _resolve_generation_size(size: str) -> str:
    """将前端选择映射为生图接口可用尺寸档位。"""
    ratio_to_pixel_size = {
        "2.35:1": "3072x1308",
        "1:1": "2048x2048",
        "9:16": "1440x2560",
        "3:4": "1728x2304",
    }
    if size in ratio_to_pixel_size:
        return ratio_to_pixel_size[size]
    if size in {"1k", "2k", "4k"}:
        return size
    return "2048x2048"


def _apply_aspect_ratio_to_prompt(prompt: str, size: str) -> str:
    """
    保持提示词原样。

    比例由生图接口 size 参数控制，不再把比例文本写入提示词，
    避免模型把「2.35:1/公众号封面」这类控制信息渲染到画面里。
    """
    _ = size
    return prompt


def _render_style_prompt(template: str, content: str, title: str) -> str:
    """渲染封面风格模板并确保包含文章语义。"""
    prompt = template.format_map(
        _SafePromptVars(
            content=content,
            title=title,
        )
    )

    # 兼容历史模板：如果没有内容占位符，自动补充文章上下文，避免跑题。
    if "{content}" not in template and "{title}" not in template:
        prompt = (
            f"{prompt}\n\n"
            f"文章标题参考：{title}\n"
            f"文章核心内容摘要：{content}"
        ).strip()
    return prompt


_CONTROL_META_LINE_PATTERN = re.compile(
    r"(公众号|封面标准尺寸|尺寸版|比例为|2\.35:1|1:1|9:16|3:4)",
    re.IGNORECASE,
)


def _strip_prompt_control_meta(prompt: str) -> str:
    """移除提示词中的平台/比例控制行，避免泄漏到图片文字。"""
    if not prompt:
        return prompt

    kept_lines: list[str] = []
    for line in prompt.splitlines():
        if _CONTROL_META_LINE_PATTERN.search(line):
            continue
        kept_lines.append(line)
    cleaned = "\n".join(kept_lines).strip()
    return cleaned or prompt.strip()


def _append_non_render_meta_guard(prompt: str) -> str:
    """追加不可视元信息约束，避免模型把说明性文字画进图里。"""
    guard = (
        "Hard constraint: do not render instruction text, metadata labels, "
        "ratio values, or platform tags in the image. Keep corner areas clean."
    )
    if guard in prompt:
        return prompt
    return f"{prompt}\n\n{guard}".strip()


async def _generate_cover_events(request: GenerateCoverRequest):
    """封面生成的通用 SSE 事件流。"""
    cover_service = get_cover_service()
    rewrite_service = get_rewrite_service()
    style_service = get_style_service()

    cover_id: Optional[int] = None
    try:
        # 1. 获取改写内容
        yield _sse_event({"type": "start", "message": "正在获取文章内容..."})
        rewrite = rewrite_service.get_rewrite(request.rewrite_id)
        if not rewrite:
            raise ValueError(f"改写记录不存在: {request.rewrite_id}")
        if not rewrite.final_content or not rewrite.final_content.strip():
            raise ValueError("改写内容为空，无法生成封面")

        content = rewrite.final_content
        writing_style_id = rewrite.style_id

        # 2. 确定使用哪个 Prompt
        if request.custom_prompt:
            # 优先级1: 用户自定义 Prompt
            prompt = request.custom_prompt
            yield _sse_event(
                {"type": "prompt_done", "prompt": prompt, "source": "custom"}
            )
        elif request.style_id:
            # 优先级2: 使用封面风格模板
            yield _sse_event({"type": "prompt", "message": "正在加载封面风格..."})
            from write_agent.core.database import engine
            from sqlmodel import Session
            from write_agent.models.cover_style import CoverStyle

            with Session(engine) as session:
                cover_style = session.get(CoverStyle, request.style_id)
                if not cover_style:
                    raise ValueError(f"封面风格不存在: {request.style_id}")

                content_summary = content[:500] if content else ""
                title_summary = rewrite.source_article[:100] if rewrite.source_article else ""
                prompt = _render_style_prompt(
                    template=cover_style.prompt_template,
                    content=content_summary,
                    title=title_summary,
                )
                yield _sse_event(
                    {
                        "type": "prompt_done",
                        "prompt": prompt,
                        "source": "style",
                        "style_name": cover_style.name,
                    }
                )
        else:
            # 优先级3: 自动生成 Prompt
            yield _sse_event({"type": "style", "message": "正在分析写作风格..."})
            writing_style = None
            if writing_style_id:
                writing_style = style_service.get_style_by_id(writing_style_id)

            yield _sse_event({"type": "prompt", "message": "正在生成封面Prompt..."})
            prompt = await cover_service.generate_prompt(content, writing_style)
            yield _sse_event(
                {"type": "prompt_done", "prompt": prompt, "source": "auto"}
            )

        generation_size = _resolve_generation_size(request.size)
        prompt_for_generation = _apply_aspect_ratio_to_prompt(prompt, request.size)
        prompt_for_generation = _strip_prompt_control_meta(prompt_for_generation)
        prompt_for_generation = _append_non_render_meta_guard(prompt_for_generation)

        # 3. 保存记录（generating状态）
        yield _sse_event({"type": "saving", "message": "正在保存记录..."})
        cover = cover_service.save_cover(
            rewrite_id=request.rewrite_id,
            prompt=prompt_for_generation,
            size=request.size,
            status="generating",
        )
        cover_id = cover.id

        # 4. 调用即梦 API 生成图片
        yield _sse_event({"type": "generating", "message": "正在生成图片..."})
        result = await cover_service.generate_image(
            prompt=prompt_for_generation,
            size=generation_size,
            rewrite_id=request.rewrite_id,
        )

        # 5. 更新记录（completed状态）
        cover_service.update_cover(
            cover_id=cover_id,
            image_url=result["image_url"],
            size=result.get("size"),
            status="completed",
        )

        # 6. 返回完成结果
        yield _sse_event(
            {
                "type": "done",
                "id": cover_id,
                "rewrite_id": request.rewrite_id,
                "image_url": result["image_url"],
                "size": result.get("size", generation_size),
                "requested_size": request.size,
                "resolved_size": generation_size,
                "prompt": prompt_for_generation,
            }
        )

    except Exception as e:
        logger.error(f"封面生成失败: {e}", exc_info=True)
        if cover_id is not None:
            try:
                cover_service.update_cover(
                    cover_id=cover_id,
                    status="failed",
                    error_message=str(e),
                )
            except Exception:
                logger.error("更新封面失败状态时发生异常", exc_info=True)
        yield _sse_event({"type": "error", "message": str(e)})


@router.post("")
async def generate_cover(request: GenerateCoverRequest):
    """
    生成封面图片

    使用SSE流式返回生成进度
    """
    return StreamingResponse(
        _generate_cover_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stream")
async def generate_cover_stream(
    rewrite_id: int,
    style_id: int | None = None,
    custom_prompt: str | None = None,
    size: Literal["2.35:1", "1:1", "9:16", "3:4", "1k", "2k", "4k"] = "2.35:1",
):
    """封面生成 GET 兼容端点（SSE）。"""
    request = GenerateCoverRequest(
        rewrite_id=rewrite_id,
        style_id=style_id,
        custom_prompt=custom_prompt,
        size=size,
    )
    return StreamingResponse(
        _generate_cover_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/by-rewrites")
async def get_covers_by_rewrites(
    rewrite_ids: list[int] = Query(default=[]),
):
    """批量获取改写对应的封面（不存在则跳过）。"""
    cover_service = get_cover_service()
    covers = cover_service.get_covers_by_rewrite_ids(rewrite_ids)
    return {
        "items": [_cover_to_response(cover) for cover in covers],
        "total": len(covers),
    }


@router.get("/{cover_id:int}")
async def get_cover(cover_id: int):
    """获取封面详情"""
    cover_service = get_cover_service()
    cover = cover_service.get_cover(cover_id)

    if not cover:
        raise HTTPException(status_code=404, detail="封面记录不存在")

    return {
        "id": cover.id,
        "rewrite_id": cover.rewrite_id,
        "prompt": cover.prompt,
        "image_url": cover.image_url,
        "size": cover.size,
        "status": cover.status,
        "error_message": cover.error_message,
        "created_at": cover.created_at.isoformat(),
        "updated_at": cover.updated_at.isoformat()
    }


def _cover_to_response(cover) -> dict:
    """将 CoverRecord 转换为响应字典"""
    return {
        "id": cover.id,
        "rewrite_id": cover.rewrite_id,
        "prompt": cover.prompt,
        "image_url": cover.image_url,
        "size": cover.size,
        "status": cover.status,
        "error_message": cover.error_message,
        "created_at": cover.created_at.isoformat(),
        "updated_at": cover.updated_at.isoformat()
    }


@router.get("/rewrite/{rewrite_id:int}")
async def get_cover_by_rewrite(rewrite_id: int):
    """获取某次改写的封面"""
    cover_service = get_cover_service()
    cover = cover_service.get_cover_by_rewrite(rewrite_id)

    if not cover:
        raise HTTPException(status_code=404, detail="该改写还没有封面")

    return {
        "id": cover.id,
        "rewrite_id": cover.rewrite_id,
        "prompt": cover.prompt,
        "image_url": cover.image_url,
        "size": cover.size,
        "status": cover.status,
        "error_message": cover.error_message,
        "created_at": cover.created_at.isoformat(),
        "updated_at": cover.updated_at.isoformat()
    }
