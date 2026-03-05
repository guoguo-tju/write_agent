"""
素材服务 - RAG 素材库管理
"""
import re
from typing import Optional
from urllib.parse import urlparse
from sqlmodel import Session, create_engine, select
from datetime import datetime
from sqlalchemy import or_

import requests
from bs4 import BeautifulSoup

from write_agent.core import get_settings, get_logger
from write_agent.models.material import Material

logger = get_logger(__name__)
settings = get_settings()
MAX_FETCH_CONTENT_LENGTH = 50000
TWEET_ID_PATTERN = re.compile(r"/status/(\d+)")

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

    def _clean_extracted_text(self, raw_text: str) -> Optional[str]:
        """清洗抓取文本，统一空白并限制长度。"""
        if not raw_text:
            return None

        lines = [line.strip() for line in raw_text.split("\n")]
        text = "\n".join(line for line in lines if line)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            return None

        if len(text) > MAX_FETCH_CONTENT_LENGTH:
            text = text[:MAX_FETCH_CONTENT_LENGTH]
        return text

    def _infer_title_from_content(self, content: str) -> Optional[str]:
        """从正文推断标题（首行优先）。"""
        if not content:
            return None
        for line in content.split("\n"):
            candidate = line.strip()
            if candidate:
                return candidate[:100]
        return None

    def _extract_wechat_content(self, soup: BeautifulSoup) -> Optional[str]:
        """提取微信公众号正文。"""
        title_node = soup.select_one("#activity-name")
        content_node = soup.select_one("#js_content")
        if not content_node:
            return None

        for node in content_node(["script", "style"]):
            node.decompose()
        title = title_node.get_text(" ", strip=True) if title_node else ""
        content_text = content_node.get_text("\n", strip=True)
        merged = f"{title}\n\n{content_text}".strip()
        return self._clean_extracted_text(merged)

    def _extract_generic_title(self, soup: BeautifulSoup) -> Optional[str]:
        """提取通用网页标题。"""
        selectors = [
            ('meta[property="og:title"]', "content"),
            ('meta[name="twitter:title"]', "content"),
            ("title", None),
            ("h1", None),
        ]
        for selector, attr in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            value = node.get(attr, "") if attr else node.get_text(" ", strip=True)
            value = (value or "").strip()
            if value:
                return value[:100]
        return None

    def _fetch_twitter_content(self, url: str, headers: dict) -> Optional[str]:
        """抓取 Twitter/X 单条推文内容（best-effort，无官方 API）。"""
        parsed = urlparse(url)
        match = TWEET_ID_PATTERN.search(parsed.path or "")
        if not match:
            return None

        tweet_id = match.group(1)
        endpoint = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=zh-cn"
        response = requests.get(endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        payload = response.json()

        text = (
            payload.get("text")
            or payload.get("full_text")
            or payload.get("note_tweet", {}).get("text")
            or ""
        ).strip()
        if not text:
            return None

        user_name = (
            payload.get("user", {}).get("name")
            or payload.get("user", {}).get("screen_name")
            or ""
        ).strip()
        snippet = re.sub(r"\s+", " ", text).strip()[:60]
        title = f"{user_name}: {snippet}" if user_name else snippet
        return self._clean_extracted_text(f"{title}\n\n{text}")

    def _fetch_generic_html_content(self, html: str) -> Optional[str]:
        """通用 HTML 文本提取。"""
        soup = BeautifulSoup(html, "html.parser")
        page_title = self._extract_generic_title(soup)
        for node in soup(["script", "style", "nav", "footer", "header"]):
            node.decompose()
        text = soup.get_text(separator="\n")
        cleaned = self._clean_extracted_text(text)
        if not cleaned:
            return None
        if page_title and not cleaned.startswith(page_title):
            return self._clean_extracted_text(f"{page_title}\n\n{cleaned}")
        return cleaned

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
            parsed = urlparse(url)

            if parsed.netloc in {"twitter.com", "www.twitter.com", "x.com", "www.x.com"}:
                twitter_text = self._fetch_twitter_content(url, headers)
                if twitter_text:
                    logger.info(f"成功抓取 Twitter/X 内容: {url}, 长度: {len(twitter_text)} 字符")
                    return twitter_text

            response = requests.get(url, headers=headers, timeout=12)
            response.raise_for_status()

            # 公众号优先走专用提取器
            if parsed.netloc == "mp.weixin.qq.com":
                soup = BeautifulSoup(response.text, "html.parser")
                wechat_text = self._extract_wechat_content(soup)
                if wechat_text:
                    logger.info(f"成功抓取公众号内容: {url}, 长度: {len(wechat_text)} 字符")
                    return wechat_text

            text = self._fetch_generic_html_content(response.text)
            if text:
                logger.info(f"成功从 URL 抓取内容: {url}, 长度: {len(text)} 字符")
                return text

        except Exception as e:
            logger.error(f"从 URL 抓取内容失败: {url}, error: {e}")
            return None

        return None

    def create_material(
        self,
        title: Optional[str],
        content: Optional[str],
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
        normalized_title = (title or "").strip()
        normalized_content = (content or "").strip()
        normalized_url = (source_url or "").strip() or None
        normalized_tags = (tags or "").strip() or None

        if not normalized_content and not normalized_url:
            raise ValueError("素材内容和来源链接不能同时为空")

        # 如果提供了 source_url 但没有 content，自动抓取内容
        if normalized_url and not self._is_valid_url(normalized_url):
            if not normalized_content:
                raise ValueError("来源链接格式无效，请输入完整的 http(s) 链接")
            normalized_url = None

        if normalized_url and not normalized_content:
            logger.info(f"检测到 URL，将自动抓取内容: {normalized_url}")
            fetched_content = self._fetch_url_content(normalized_url)
            if fetched_content:
                normalized_content = fetched_content
                logger.info(f"自动抓取内容成功，长度: {len(normalized_content)} 字符")
            else:
                raise ValueError("无法从 URL 抓取内容，请手动提供 content")

        if not normalized_content:
            raise ValueError("素材内容不能为空")

        if not normalized_title:
            normalized_title = self._infer_title_from_content(normalized_content) or ""
        if not normalized_title and normalized_url:
            normalized_title = normalized_url[:100]
        if not normalized_title:
            normalized_title = "未命名素材"

        logger.info(f"添加素材: {normalized_title}")

        # 先创建素材记录
        with Session(engine) as session:
            material = Material(
                title=normalized_title,
                content=normalized_content,
                tags=normalized_tags,
                source_url=normalized_url,
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
                content=f"{normalized_title}\n\n{normalized_content}",
                metadata={
                    "title": normalized_title,
                    "tags": normalized_tags,
                    "source_url": normalized_url,
                },
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

    def update_material(
        self,
        material_id: int,
        title: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> Optional[Material]:
        """
        更新素材并重建向量索引。

        Returns:
            Material 对象；不存在时返回 None
        """
        with Session(engine) as session:
            material = session.get(Material, material_id)
            if not material:
                return None

            next_title = material.title if title is None else title.strip()
            next_content = material.content if content is None else content.strip()
            next_tags = material.tags if tags is None else (tags.strip() or None)
            next_url = material.source_url if source_url is None else (source_url.strip() or None)

            if not next_title:
                raise ValueError("素材标题不能为空")

            if next_url and not self._is_valid_url(next_url):
                raise ValueError("来源链接格式无效，请输入完整的 http(s) 链接")

            # 允许“仅链接”提交编辑：如果正文为空则尝试抓取
            if not next_content and next_url:
                fetched_content = self._fetch_url_content(next_url)
                if fetched_content:
                    next_content = fetched_content
                else:
                    raise ValueError("无法从 URL 抓取内容，请手动补充正文")

            if not next_content:
                raise ValueError("素材内容不能为空")

            material.title = next_title
            material.content = next_content
            material.tags = next_tags
            material.source_url = next_url
            material.embedding_status = "pending"
            material.embedding_error = None
            material.updated_at = datetime.now()
            session.commit()

        embedding_status = "completed"
        embedding_error = None
        try:
            try:
                self.rag_service.delete_material(material_id)
            except Exception as e:
                logger.warning(f"素材更新时删除旧向量失败: material_id={material_id}, error={e}")

            self.rag_service.add_material(
                material_id=material_id,
                content=f"{next_title}\n\n{next_content}",
                metadata={
                    "title": next_title,
                    "tags": next_tags,
                    "source_url": next_url,
                },
            )
        except Exception as e:
            embedding_status = "failed"
            embedding_error = str(e)
            logger.error(f"素材更新后重建向量失败: material_id={material_id}, error={e}", exc_info=True)

        with Session(engine) as session:
            material = session.get(Material, material_id)
            if not material:
                return None
            material.embedding_status = embedding_status
            material.embedding_error = embedding_error
            material.updated_at = datetime.now()
            session.commit()
            session.refresh(material)
            return material

    def get_all_materials(
        self,
        tags: Optional[str] = None,
        keyword: Optional[str] = None,
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
            count_statement = select(Material)

            # 按标签筛选
            if tags:
                normalized_tag = tags.split(",")[0].strip()
                statement = statement.where(Material.tags.contains(normalized_tag))
                count_statement = count_statement.where(Material.tags.contains(normalized_tag))

            # 按关键词筛选（标题/正文/来源/标签）
            if keyword and keyword.strip():
                normalized_keyword = keyword.strip()
                keyword_filter = or_(
                    Material.title.contains(normalized_keyword),
                    Material.content.contains(normalized_keyword),
                    Material.source_url.contains(normalized_keyword),
                    Material.tags.contains(normalized_keyword),
                )
                statement = statement.where(keyword_filter)
                count_statement = count_statement.where(keyword_filter)

            # 统计总数
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
            [{"material_id": 1, "title": "...", "source_url": "...", "tags": "...", "content": "...", "score": 0.95}]
        """
        try:
            # 使用 RAG 服务进行向量检索
            results = self.rag_service.search(query=query, top_k=top_k)
            if not results:
                return []

            material_ids = []
            for item in results:
                material_id = int(item.get("material_id") or 0)
                if material_id > 0:
                    material_ids.append(material_id)

            material_map: dict[int, Material] = {}
            if material_ids:
                with Session(engine) as session:
                    statement = select(Material).where(Material.id.in_(list(set(material_ids))))
                    materials = session.exec(statement).all()
                    material_map = {material.id: material for material in materials if material.id}

            enriched: list[dict] = []
            for item in results:
                material_id = int(item.get("material_id") or 0)
                material = material_map.get(material_id)
                fallback_content = str(item.get("content") or "")

                enriched.append({
                    "material_id": material_id,
                    "title": material.title if material else (f"素材 #{material_id}" if material_id else "未知素材"),
                    "source_url": material.source_url if material else None,
                    "tags": material.tags if material else None,
                    "content": material.content if material and material.content else fallback_content,
                    "score": float(item.get("score") or 0),
                })

            return enriched
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
