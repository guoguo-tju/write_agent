"""
封面生成服务
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional
from sqlmodel import Session, create_engine, select

from write_agent.core import get_settings
from write_agent.models.cover_record import CoverRecord
from write_agent.models.rewrite_record import RewriteRecord
from write_agent.models.writing_style import WritingStyle
from write_agent.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)
settings = get_settings()

# 创建数据库引擎
engine = create_engine(settings.database_url, echo=False)


class CoverService:
    """封面生成服务"""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.volcengine_base_url
        self.model = settings.volcengine_model
        self.api_key = settings.volcengine_api_key

    async def generate_prompt(
        self,
        content: str,
        style: Optional[WritingStyle] = None
    ) -> str:
        """
        基于文章内容和风格生成图片Prompt

        Args:
            content: 文章内容
            style: 写作风格（可选）

        Returns:
            生成的图片Prompt
        """
        llm = get_llm_service()

        # 构建风格描述
        style_description = ""
        if style:
            style_attrs = []
            # 使用 WritingStyle 模型实际存在的属性
            if style.name:
                style_attrs.append(f"风格名称: {style.name}")
            if style.style_description:
                style_attrs.append(f"风格描述: {style.style_description}")
            if style.tags:
                style_attrs.append(f"标签: {style.tags}")
            if style_attrs:
                style_description = "，".join(style_attrs)

        # 内容验证
        if not content or len(content.strip()) < 10:
            raise ValueError("文章内容过短，无法生成封面")

        # 提取文章主题关键词
        extract_prompt = f"""请从以下文章中提取3-5个核心主题关键词，这些关键词将用于生成封面图片。

文章内容：
{content[:2000]}

请直接输出关键词，用逗号分隔，不要包含其他内容。
"""

        # 先提取关键词（使用 to_thread 调用同步方法）
        keywords_response: str = await asyncio.to_thread(
            llm.chat,
            messages=[{"role": "user", "content": extract_prompt}]
        )
        keywords = keywords_response.strip()

        # 生成封面Prompt
        cover_prompt = f"""请为文章生成一个适合的封面图片描述词（英文）。

文章主题关键词：{keywords}
{style_description}

要求：
1. 描述一个具体的视觉画面
2. 包含艺术风格（如：油画、水彩、摄影、电影感、3D渲染等）
3. 包含色调和氛围（如：暖色调、冷色调、赛博朋克、梦幻等）
4. 包含构图元素
5. 添加高质量修饰词（如：超高清、8K、景深、光线追踪、OC渲染等）
6. 输出纯英文描述，不要包含任何解释

直接输出Prompt，不要包含任何前缀或后缀。
"""

        # 生成封面Prompt（使用 to_thread 调用同步方法）
        prompt_response: str = await asyncio.to_thread(
            llm.chat,
            messages=[{"role": "user", "content": cover_prompt}]
        )

        generated_prompt = prompt_response.strip()
        logger.debug(f"封面Prompt已生成，长度: {len(generated_prompt)} 字符")

        return generated_prompt

    async def generate_image(
        self,
        prompt: str,
        size: str = "2k",
        rewrite_id: int = 0
    ) -> dict:
        """
        调用即梦API生成图片

        Args:
            prompt: 图片生成Prompt
            size: 图片尺寸
            rewrite_id: 改写记录ID

        Returns:
            包含image_url和size的字典
        """
        import requests

        url = f"{self.base_url}/api/v3/images/generations"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": size,
            "response_format": "url",
            "stream": False,
            "watermark": False,
            "sequential_image_generation": "disabled"
        }

        logger.info(f"调用即梦API生成图片，rewrite_id={rewrite_id}")

        try:
            response = await asyncio.to_thread(
                requests.post,
                url,
                headers=headers,
                json=payload,
                timeout=120,
            )
            response.raise_for_status()

            data = response.json()

            if "error" in data:
                raise Exception(f"API错误: {data['error']['message']}")

            image_url = data["data"][0]["url"]
            image_size = data["data"][0]["size"]

            logger.info(f"图片生成成功: {image_url}")

            return {
                "image_url": image_url,
                "size": image_size
            }

        except Exception as e:
            logger.error(f"图片生成失败: {e}")
            raise

    def save_cover(
        self,
        rewrite_id: int,
        prompt: str,
        image_url: Optional[str] = None,
        size: str = "2k",
        status: str = "pending",
        error_message: Optional[str] = None
    ) -> CoverRecord:
        """保存封面记录"""
        with Session(engine) as session:
            cover = CoverRecord(
                rewrite_id=rewrite_id,
                prompt=prompt,
                image_url=image_url,
                size=size,
                status=status,
                error_message=error_message,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            session.add(cover)
            session.commit()
            session.refresh(cover)
            return cover

    def update_cover(
        self,
        cover_id: int,
        image_url: Optional[str] = None,
        size: Optional[str] = None,
        status: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> Optional[CoverRecord]:
        """更新封面记录"""
        with Session(engine) as session:
            cover = session.get(CoverRecord, cover_id)
            if cover:
                if image_url is not None:
                    cover.image_url = image_url
                if size is not None:
                    cover.size = size
                if status is not None:
                    cover.status = status
                if error_message is not None:
                    cover.error_message = error_message
                cover.updated_at = datetime.now()
                session.commit()
                session.refresh(cover)
            return cover

    def get_cover(self, cover_id: int) -> Optional[CoverRecord]:
        """获取封面记录"""
        with Session(engine) as session:
            return session.get(CoverRecord, cover_id)

    def get_cover_by_rewrite(self, rewrite_id: int) -> Optional[CoverRecord]:
        """获取某次改写的封面"""
        with Session(engine) as session:
            statement = select(CoverRecord).where(
                CoverRecord.rewrite_id == rewrite_id
            ).order_by(CoverRecord.created_at.desc())
            return session.exec(statement).first()

    def get_covers_by_rewrite_ids(self, rewrite_ids: list[int]) -> list[CoverRecord]:
        """批量获取改写对应的最新封面。"""
        if not rewrite_ids:
            return []

        with Session(engine) as session:
            statement = (
                select(CoverRecord)
                .where(CoverRecord.rewrite_id.in_(rewrite_ids))
                .order_by(CoverRecord.rewrite_id.asc(), CoverRecord.created_at.desc())
            )
            rows = session.exec(statement).all()

        latest_by_rewrite: dict[int, CoverRecord] = {}
        for cover in rows:
            latest_by_rewrite.setdefault(cover.rewrite_id, cover)

        order_map = {rewrite_id: idx for idx, rewrite_id in enumerate(rewrite_ids)}
        return sorted(
            latest_by_rewrite.values(),
            key=lambda cover: order_map.get(cover.rewrite_id, len(order_map)),
        )


# 全局单例
_cover_service: Optional[CoverService] = None


def get_cover_service() -> CoverService:
    """获取封面服务单例"""
    global _cover_service
    if _cover_service is None:
        _cover_service = CoverService()
    return _cover_service
