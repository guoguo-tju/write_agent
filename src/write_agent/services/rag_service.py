"""
RAG 服务 - 基于 Chroma + 硅基流动 Embedding
"""
import os
import httpx
from typing import Optional
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document

from write_agent.core import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()

# Chroma 持久化目录
CHROMA_DIR = "./data/chroma"


class SiliconFlowEmbeddings(Embeddings):
    """硅基流动 Embedding 实现"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入文档"""
        embeddings = []
        for text in texts:
            embedding = self._embed_single(text)
            embeddings.append(embedding)
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        """嵌入查询"""
        return self._embed_single(text)

    def _embed_single(self, text: str) -> list[float]:
        """单个文本嵌入"""
        url = f"{self.base_url}/v1/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": text,
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            return result["data"][0]["embedding"]


class EmbeddingService:
    """嵌入服务 - 使用硅基流动 API"""

    def __init__(self):
        self.embeddings = SiliconFlowEmbeddings(
            api_key=settings.siliconflow_api_key,
            base_url=settings.siliconflow_base_url,
            model=settings.siliconflow_embedding_model,
        )
        logger.info(f"Embedding 服务初始化完成，使用模型: {settings.siliconflow_embedding_model}")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """获取文本的嵌入向量"""
        return self.embeddings.embed_documents(texts)

    def embed_query(self, query: str) -> list[float]:
        """获取查询的嵌入向量"""
        return self.embeddings.embed_query(query)


class RAGService:
    """RAG 服务 - 使用 Chroma 向量数据库"""

    def __init__(self):
        self.embedding_service = EmbeddingService()

        # 初始化 Chroma 向量库
        self.vector_store = Chroma(
            collection_name="materials",
            embedding_function=self.embedding_service.embeddings,
            persist_directory=CHROMA_DIR,
        )
        logger.info(f"RAG 服务初始化完成，持久化目录: {CHROMA_DIR}")

    def add_material(self, material_id: int, content: str, metadata: dict = None):
        """
        添加素材到向量库

        Args:
            material_id: 素材 ID
            content: 素材内容
            metadata: 元数据
        """
        # 确保 material_id 一定在 metadata 中
        meta = metadata.copy() if metadata else {}
        meta["material_id"] = material_id

        doc = Document(
            page_content=content,
            metadata=meta,
        )
        self.vector_store.add_documents([doc])
        logger.info(f"素材已添加到向量库: material_id={material_id}")

    def search(
        self,
        query: str,
        top_k: int = 3,
    ) -> list[dict]:
        """
        检索相关素材

        Args:
            query: 查询文本
            top_k: 返回条数

        Returns:
            [{"material_id": 1, "content": "...", "score": 0.95}]
        """
        results = self.vector_store.similarity_search_with_score(
            query=query,
            k=top_k,
        )

        # 转换为统一格式
        retrieved = []
        for doc, score in results:
            material_id = doc.metadata.get("material_id", 0)
            # Chroma 的 score 越小越相似，转换为 0-1
            similarity = 1 / (1 + score)
            retrieved.append({
                "material_id": material_id,
                "content": doc.page_content,
                "score": round(similarity, 3),
            })

        logger.info(f"RAG 检索完成，返回 {len(retrieved)} 条结果")
        return retrieved

    def delete_material(self, material_id: int):
        """从向量库删除素材"""
        # 删除对应 metadata 的文档
        self.vector_store.delete(where={"material_id": material_id})
        logger.info(f"素材已从向量库删除: material_id={material_id}")


# 全局单例
_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    """获取 RAG 服务单例"""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service
