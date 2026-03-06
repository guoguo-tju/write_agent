"""
FastAPI 应用入口 - 类似 Java Spring Boot 的 Application.java
"""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from write_agent.core import setup_logging, get_settings, get_logger
from write_agent.api import api_router

# 初始化日志
settings = get_settings()
setup_logging(settings.log_level)

logger = get_logger(__name__)
cover_storage_dir = Path(settings.cover_storage_dir).resolve()
cover_media_url_prefix = settings.cover_media_url_prefix
if not cover_media_url_prefix.startswith("/"):
    cover_media_url_prefix = f"/{cover_media_url_prefix}"
cover_storage_dir.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("🚀 写作智能体 API 启动中...")
    yield
    # 关闭时执行
    logger.info("👋 写作智能体 API 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="写作智能体 API",
    description="基于 LangChain + LangGraph 的写作智能体后端服务",
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

# CORS 中间件
# 限制允许的来源，生产环境应配置具体域名
cors_origins = settings.cors_origins if hasattr(settings, 'cors_origins') else [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(api_router)
app.mount(
    cover_media_url_prefix,
    StaticFiles(directory=str(cover_storage_dir)),
    name="cover-media",
)


@app.get("/")
async def root():
    """健康检查"""
    return {"status": "ok", "message": "写作智能体 API 运行中"}


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    logger.info(f"启动服务: http://{settings.api_host}:{settings.api_port}")
    uvicorn.run(
        "write_agent.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
