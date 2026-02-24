"""
素材服务 - RAG 素材库管理
"""
import re
from typing import Optional
from urllib.parse import urlparse
from sqlmodel import Session, create_engine, select
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from write_agent.core import get_settings, get_logger
from write_agent.models.material import Material

logger = get_logger(__name__)
settings = get_settings()

# 创建数据库引擎
engine = create_engine(settings.database_url, echo=False)


class MaterialService:
    """
    素材服务

    管理 RAG 素材库，支持添加、查询、删除素材
    同时维护向量数据库
    """

    def __init__(self):
        """初始化素材服务"""
        # 延迟导入，避免循环依赖
        from write_agent.services.rag_service import get_rag_service
        self.rag_service = get_rag_service()

    def _is_valid_url(self, url: str) -> bool:
        """检查是否是有效的 URL"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
        except Exception:
            return False

    def _fetch_url_content(self, url: str) -> Optional[str]:
        """
        从 URL 抓取网页内容

        Args:
            url: 网页 URL

        Returns:
            抓取的文本内容，如果失败返回 None
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            # 解析 HTML
            soup = BeautifulSoup(response.content, 'html.parser')

            # 移除脚本和样式
            for script in soup(['script', 'style', 'nav', 'footer', 'header']):
                script.decompose()

            # 获取文本内容
            text = soup.get_text(separator='\n')

            # 清理空白字符
            lines = [line.strip() for line in text.split('\n')]
            text = '\n'.join(line for line in lines if line)

            # 限制内容长度，避免过长
            if len(text) > 50000:
                text = text[:50000] + '...'

            logger.info(f"成功从 URL 抓取内容: {url}, 长度: {len(text)} 字符")
            return text if text else None

        except Exception as e:
            logger.error(f"从 URL 抓取内容失败: {url}, error: {e}")
            return None

    def create_material(
        self,
        title: str,
        content: str,
        tags: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> Material:
        """
        添加素材

        Args:
            title: 素材标题
            content: 素材内容
            tags: 标签
            source_url: 来源URL

        Returns:
            Material 对象

        Raises:
            ValueError: 如果素材内容为空
            Exception: 如果添加到向量库失败
        """
        # 参数验证
        if not title or not title.strip():
            raise ValueError("素材标题不能为空")

        # 如果提供了 source_url 但没有 content，自动抓取内容
        if source_url and self._is_valid_url(source_url) and (not content or not content.strip()):
            logger.info(f"检测到 URL，将自动抓取内容: {source_url}")
            fetched_content = self._fetch_url_content(source_url)
            if fetched_content:
                content = fetched_content
                logger.info(f"自动抓取内容成功，长度: {len(content)} 字符")
            else:
                raise ValueError("无法从 URL 抓取内容，请手动提供 content")

        if not content or not content.strip():
            raise ValueError("素材内容不能为空")

        logger.info(f"添加素材: {title}")

        # 先创建素材记录
        with Session(engine) as session:
            material = Material(
                title=title.strip(),
                content=content,
                tags=tags,
                source_url=source_url,
                embedding_status="pending",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            session.add(material)
            session.commit()
            session.refresh(material)
            material_id = material.id

        # 添加到向量库
        embedding_status = "pending"
        embedding_error = None
        try:
            self.rag_service.add_material(
                material_id=material_id,
                content=f"{title}\n\n{content}",
                metadata={"title": title, "tags": tags},
            )
            embedding_status = "completed"
        except Exception as e:
            logger.error(f"添加到向量库失败: {e}", exc_info=True)
            embedding_status = "failed"
            embedding_error = str(e)
            # 注意：即使向量库添加失败，素材记录仍然保留

        # 更新状态
        with Session(engine) as session:
            material = session.get(Material, material_id)
            material.embedding_status = embedding_status
            material.embedding_error = embedding_error
            session.commit()

        # 如果向量库添加失败，返回警告但仍返回素材对象
        if embedding_status == "failed":
            logger.warning(f"素材创建成功但向量库添加失败: material_id={material_id}, error={embedding_error}")

        # 返回完整对象
        with Session(engine) as session:
            return session.get(Material, material_id)

    def get_material(self, material_id: int) -> Optional[Material]:
        """获取素材详情"""
        with Session(engine) as session:
            return session.get(Material, material_id)

    def get_all_materials(
        self,
        tags: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Material], int]:
        """
        获取素材列表

        Returns:
            (素材列表, 总数)
        """
        with Session(engine) as session:
            # 构建查询
            statement = select(Material).order_by(Material.created_at.desc())

            # 按标签筛选
            if tags:
                statement = statement.where(Material.tags.contains(tags.split(",")[0].strip()))

            # 统计总数
            count_statement = select(Material)
            if tags:
                count_statement = count_statement.where(
                    Material.tags.contains(tags.split(",")[0].strip())
                )
            total = len(session.exec(count_statement).all())

            # 分页
            statement = statement.offset((page - 1) * limit).limit(limit)
            materials = session.exec(statement).all()

            return materials, total

    def delete_material(self, material_id: int) -> bool:
        """删除素材"""
        with Session(engine) as session:
            material = session.get(Material, material_id)
            if material:
                # 从向量库删除
                try:
                    self.rag_service.delete_material(material_id)
                except Exception as e:
                    logger.error(f"从向量库删除失败: {e}")

                session.delete(material)
                session.commit()
                return True
            return False

    def update_embedding_status(
        self,
        material_id: int,
        status: str,
        error: Optional[str] = None,
    ) -> bool:
        """更新向量化状态"""
        with Session(engine) as session:
            material = session.get(Material, material_id)
            if material:
                material.embedding_status = status
                material.embedding_error = error
                material.updated_at = datetime.now()
                session.commit()
                return True
            return False

    def search_by_keywords(
        self,
        query: str,
        top_k: int = 3,
    ) -> list[dict]:
        """
        向量检索 - 基于 Chroma + 硅基流动 Embedding

        Args:
            query: 查询文本
            top_k: 返回条数

        Returns:
            [{"material_id": 1, "content": "...", "score": 0.95}]
        """
        try:
            # 使用 RAG 服务进行向量检索
            results = self.rag_service.search(query=query, top_k=top_k)
            return results
        except Exception as e:
            logger.error(f"RAG 检索失败: {e}")
            return []


# 全局单例
_material_service: Optional[MaterialService] = None


def get_material_service() -> MaterialService:
    """获取素材服务单例"""
    global _material_service
    if _material_service is None:
        _material_service = MaterialService()
    return _material_service
