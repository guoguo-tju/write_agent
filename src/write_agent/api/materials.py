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
    content: Optional[str] = None
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


class UpdateMaterialRequest(BaseModel):
    """更新素材请求"""
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[str] = None
    source_url: Optional[str] = None
    source: Optional[str] = Field(default=None, description="兼容字段，等价于 source_url")


class MaterialListResponse(BaseModel):
    """素材列表响应"""
    items: list[dict]
    total: int
    page: int
    limit: int


class MaterialRetrieveRequest(BaseModel):
    """素材检索测试请求"""
    query: str = Field(min_length=1, description="检索查询")
    top_k: int = Field(default=5, ge=1, le=20, description="返回条数")


class MaterialRetrieveResponse(BaseModel):
    """素材检索测试响应"""
    items: list[dict]
    total: int


# ============ API 接口 ============

@router.post("", response_model=MaterialResponse)
async def create_material(request: CreateMaterialRequest):
    """添加素材"""
    try:
        source_url = request.source_url or request.source

        material = material_service.create_material(
            title=request.title,
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
    keyword: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
):
    """获取素材列表"""
    try:
        if page < 1:
            raise HTTPException(status_code=400, detail="page 必须大于等于 1")
        if limit < 1:
            raise HTTPException(status_code=400, detail="limit 必须大于等于 1")

        materials, total = material_service.get_all_materials(
            tags=tags,
            keyword=keyword,
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retrieve", response_model=MaterialRetrieveResponse)
async def retrieve_materials(request: MaterialRetrieveRequest):
    """RAG 检索测试接口"""
    try:
        query = request.query.strip()
        if not query:
            raise HTTPException(status_code=400, detail="query 不能为空")

        items = material_service.search_by_keywords(
            query=query,
            top_k=request.top_k,
        )
        return MaterialRetrieveResponse(items=items, total=len(items))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"素材检索失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"素材检索失败: {str(e)}")


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


@router.patch("/{material_id}", response_model=MaterialResponse)
async def update_material(material_id: int, request: UpdateMaterialRequest):
    """更新素材"""
    try:
        updated = material_service.update_material(
            material_id=material_id,
            title=request.title,
            content=request.content,
            tags=request.tags,
            source_url=request.source_url if request.source_url is not None else request.source,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="素材不存在")

        return MaterialResponse(
            id=updated.id,
            title=updated.title,
            content=updated.content,
            tags=updated.tags,
            source_url=updated.source_url,
            embedding_status=updated.embedding_status,
            embedding_error=updated.embedding_error,
            created_at=updated.created_at.isoformat(),
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"更新素材失败: material_id={material_id}, error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新素材失败: {str(e)}")


@router.delete("/{material_id}")
async def delete_material(material_id: int):
    """删除素材"""
    success = material_service.delete_material(material_id)
    if not success:
        raise HTTPException(status_code=404, detail="素材不存在")

    return {"status": "ok", "message": "删除成功"}
