"""
API 路由模块
"""
from fastapi import APIRouter
from .styles import router as styles_router
from .materials import router as materials_router
from .rewrites import router as rewrites_router
from .reviews import router as reviews_router
from .covers import router as covers_router
from .cover_styles import router as cover_styles_router

# 创建主路由
api_router = APIRouter(prefix="/api")

# 注册子路由（注意：更具体的路由需要放在前面）
api_router.include_router(styles_router)
api_router.include_router(materials_router)
api_router.include_router(rewrites_router)
api_router.include_router(reviews_router)
# cover_styles_router 需要放在 covers_router 之前，避免 /covers/styles 被 /covers/{cover_id} 匹配
api_router.include_router(cover_styles_router)
api_router.include_router(covers_router)

__all__ = ["api_router"]
