"""
FastAPI 应用入口 - 类似 Java Spring Boot 的 Application.java
"""
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from write_agent.core import setup_logging, get_settings, get_logger
from write_agent.api import api_router
from write_agent.services.github_trending_service import (
    RefreshInProgressError,
    get_github_trending_service,
)

# 初始化日志
settings = get_settings()
setup_logging(settings.log_level)

logger = get_logger(__name__)
cover_storage_dir = Path(settings.cover_storage_dir).resolve()
cover_media_url_prefix = settings.cover_media_url_prefix
if not cover_media_url_prefix.startswith("/"):
    cover_media_url_prefix = f"/{cover_media_url_prefix}"
cover_storage_dir.mkdir(parents=True, exist_ok=True)


async def _github_trending_scheduler_loop():
    """每日定时抓取 GitHub 趋势。"""
    tz = ZoneInfo(settings.github_trending_timezone)
    service = get_github_trending_service()

    while True:
        now = datetime.now(tz)
        next_run = now.replace(
            hour=settings.github_trending_daily_hour,
            minute=settings.github_trending_daily_minute,
            second=0,
            microsecond=0,
        )
        if next_run <= now:
            next_run += timedelta(days=1)

        wait_seconds = max((next_run - now).total_seconds(), 1.0)
        logger.info(
            "GitHub 趋势调度已就绪，下一次执行时间：%s",
            next_run.isoformat(),
        )
        await asyncio.sleep(wait_seconds)

        try:
            await service.refresh_current_week_snapshot()
            logger.info("GitHub 趋势定时抓取成功")
        except RefreshInProgressError:
            logger.info("GitHub 趋势抓取已在执行中，跳过本轮定时任务")
        except Exception as error:
            logger.error("GitHub 趋势定时抓取失败: %s", error, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("🚀 写作智能体 API 启动中...")
    scheduler_task: asyncio.Task | None = asyncio.create_task(
        _github_trending_scheduler_loop()
    )
    try:
        yield
    finally:
        # 关闭时执行
        if scheduler_task:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
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
