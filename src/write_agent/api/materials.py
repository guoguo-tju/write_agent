"""
素材管理 API 路由
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from write_agent.services.material_service import get_material_service
from write_agent.core import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/materials", tags=["素材管理"])

# 服务实例
material_service = get_material_service()


# ============ 请求/响应模型 ============

class CreateMaterialRequest(BaseModel):
    """创建素材请求"""
    title: Optional[str] = None
    content: str
    tags: Optional[str] = None
    source_url: Optional[str] = None
    source: Optional[str] = Field(default=None, description="兼容字段，等价于 source_url")


class MaterialResponse(BaseModel):
    """素材响应"""
    id: int
    title: str
    content: str
    tags: Optional[str]
    source_url: Optional[str]
    embedding_status: str
    embedding_error: Optional[str]
    created_at: str


class MaterialListResponse(BaseModel):
    """素材列表响应"""
    items: list[dict]
    total: int
    page: int
    limit: int


# ============ API 接口 ============

@router.post("", response_model=MaterialResponse)
async def create_material(request: CreateMaterialRequest):
    """添加素材"""
    try:
        source_url = request.source_url or request.source
        title = request.title
        if not title or not title.strip():
            if source_url:
                title = source_url[:100]
            else:
                title = (request.content or "").strip().split("\n")[0][:50] or "未命名素材"

        material = material_service.create_material(
            title=title,
            content=request.content,
            tags=request.tags,
            source_url=source_url,
        )

        return MaterialResponse(
            id=material.id,
            title=material.title,
            content=material.content,
            tags=material.tags,
            source_url=material.source_url,
            embedding_status=material.embedding_status,
            embedding_error=material.embedding_error,
            created_at=material.created_at.isoformat(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"添加素材失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"添加素材失败: {str(e)}")


@router.get("", response_model=MaterialListResponse)
async def get_materials(
    tags: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
):
    """获取素材列表"""
    try:
        materials, total = material_service.get_all_materials(
            tags=tags,
            page=page,
            limit=limit,
        )

        return MaterialListResponse(
            items=[
                {
                    "id": m.id,
                    "title": m.title,
                    "content": m.content,
                    "source_url": m.source_url,
                    "tags": m.tags,
                    "embedding_status": m.embedding_status,
                    "embedding_error": m.embedding_error,
                    "created_at": m.created_at.isoformat(),
                }
                for m in materials
            ],
            total=total,
            page=page,
            limit=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{material_id}", response_model=MaterialResponse)
async def get_material(material_id: int):
    """获取素材详情"""
    material = material_service.get_material(material_id)
    if not material:
        raise HTTPException(status_code=404, detail="素材不存在")

    return MaterialResponse(
        id=material.id,
        title=material.title,
        content=material.content,
        tags=material.tags,
        source_url=material.source_url,
        embedding_status=material.embedding_status,
        embedding_error=material.embedding_error,
        created_at=material.created_at.isoformat(),
    )


@router.delete("/{material_id}")
async def delete_material(material_id: int):
    """删除素材"""
    success = material_service.delete_material(material_id)
    if not success:
        raise HTTPException(status_code=404, detail="素材不存在")

    return {"status": "ok", "message": "删除成功"}
