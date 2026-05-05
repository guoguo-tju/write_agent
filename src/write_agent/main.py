"""
FastAPI 应用入口 - 类似 Java Spring Boot 的 Application.java
"""
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from write_agent.core import setup_logging, get_settings, get_logger
from write_agent.api import api_router
from write_agent.observability import (
    TraceContextMiddleware,
    current_context,
    emit_obs_event,
    obs_scope,
    validate_registry,
)
from write_agent.observability.errors import build_error_response, error_code_from_status
from write_agent.services.github_trending_service import (
    RefreshInProgressError,
    get_github_trending_service,
)
from write_agent.services.linuxdo_trending_service import (
    RefreshCoolingDownError as LinuxDoRefreshCoolingDownError,
    RefreshInProgressError as LinuxDoRefreshInProgressError,
    RefreshRateLimitedError as LinuxDoRefreshRateLimitedError,
    get_linuxdo_trending_service,
)
from write_agent.services.workflow_job_service import get_workflow_job_service
from write_agent.services.default_style_seed_service import bootstrap_default_styles

# 初始化日志
settings = get_settings()
setup_logging(settings.log_level)

logger = get_logger(__name__)
cover_storage_dir = Path(settings.cover_storage_dir).resolve()
cover_media_url_prefix = settings.cover_media_url_prefix
if not cover_media_url_prefix.startswith("/"):
    cover_media_url_prefix = f"/{cover_media_url_prefix}"
cover_storage_dir.mkdir(parents=True, exist_ok=True)
WORKFLOW_STALE_RECOVERY_INTERVAL_SECONDS = 15.0


async def _github_trending_scheduler_loop():
    """每日定时抓取 GitHub 趋势（daily + weekly）。"""
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
            with obs_scope("JOB.GITHUB_TRENDS.SCHEDULER", "SCHEDULER_JOB"):
                emit_obs_event(
                    level="INFO",
                    message="github_trending.scheduler.tick",
                    payload={"next_run": next_run.isoformat()},
                )
                for period_type in ("daily", "weekly"):
                    try:
                        emit_obs_event(
                            level="INFO",
                            message="github_trending.scheduler.period_start",
                            payload={"period_type": period_type},
                        )
                        await service.refresh_snapshot(period_type=period_type)
                        logger.info("GitHub 趋势定时抓取成功: %s", period_type)
                        emit_obs_event(
                            level="INFO",
                            message="github_trending.scheduler.period_success",
                            payload={"period_type": period_type},
                        )
                    except RefreshInProgressError:
                        logger.info("GitHub 趋势抓取已在执行中，跳过本轮定时任务: %s", period_type)
                        emit_obs_event(
                            level="WARNING",
                            message="github_trending.scheduler.period_skipped",
                            error_code="E_TREND_REFRESH_RUNNING",
                            payload={"period_type": period_type},
                        )
                    except Exception as error:
                        logger.error(
                            "GitHub 趋势定时抓取失败(%s): %s",
                            period_type,
                            error,
                            exc_info=True,
                        )
                        emit_obs_event(
                            level="ERROR",
                            message="github_trending.scheduler.period_failed",
                            error_code="E_TREND_SCHEDULER_FAILED",
                            payload={"period_type": period_type, "error": str(error)},
                        )
                emit_obs_event(
                    level="INFO",
                    message="github_trending.scheduler.success",
                )
        except RefreshInProgressError:
            logger.info("GitHub 趋势抓取已在执行中，跳过本轮定时任务")
            emit_obs_event(
                level="WARNING",
                message="github_trending.scheduler.skipped",
                error_code="E_TREND_REFRESH_RUNNING",
            )
        except Exception as error:
            logger.error("GitHub 趋势定时抓取失败: %s", error, exc_info=True)
            emit_obs_event(
                level="ERROR",
                message="github_trending.scheduler.failed",
                error_code="E_TREND_SCHEDULER_FAILED",
                payload={"error": str(error)},
            )


async def _linuxdo_trending_scheduler_loop():
    """每日定时抓取 Linux.do 趋势（weekly + monthly）。"""
    tz = ZoneInfo(settings.linuxdo_trending_timezone)
    service = get_linuxdo_trending_service()

    while True:
        now = datetime.now(tz)
        next_run = now.replace(
            hour=settings.linuxdo_trending_daily_hour,
            minute=settings.linuxdo_trending_daily_minute,
            second=0,
            microsecond=0,
        )
        if next_run <= now:
            next_run += timedelta(days=1)

        wait_seconds = max((next_run - now).total_seconds(), 1.0)
        logger.info(
            "Linux.do 趋势调度已就绪，下一次执行时间：%s",
            next_run.isoformat(),
        )
        await asyncio.sleep(wait_seconds)

        try:
            with obs_scope("JOB.LINUXDO_TRENDS.SCHEDULER", "SCHEDULER_JOB"):
                emit_obs_event(
                    level="INFO",
                    message="linuxdo_trending.scheduler.tick",
                    payload={"next_run": next_run.isoformat()},
                )
                await service.refresh_snapshot("weekly")
                await service.refresh_snapshot("monthly")
                logger.info("Linux.do 趋势定时抓取成功")
                emit_obs_event(
                    level="INFO",
                    message="linuxdo_trending.scheduler.success",
                )
        except (
            LinuxDoRefreshInProgressError,
            LinuxDoRefreshCoolingDownError,
            LinuxDoRefreshRateLimitedError,
        ):
            logger.info("Linux.do 趋势抓取已在执行中，跳过本轮定时任务")
            emit_obs_event(
                level="WARNING",
                message="linuxdo_trending.scheduler.skipped",
                error_code="E_LINUXDO_TREND_REFRESH_RUNNING",
            )
        except Exception as error:
            logger.error("Linux.do 趋势定时抓取失败: %s", error, exc_info=True)
            emit_obs_event(
                level="ERROR",
                message="linuxdo_trending.scheduler.failed",
                error_code="E_LINUXDO_TREND_SCHEDULER_FAILED",
                payload={"error": str(error)},
            )


async def _workflow_stale_recovery_loop():
    """运行期定时恢复长时间无心跳的 workflow job。"""
    workflow_job_service = get_workflow_job_service()
    while True:
        await asyncio.sleep(WORKFLOW_STALE_RECOVERY_INTERVAL_SECONDS)
        try:
            recovered = workflow_job_service.resume_stale_jobs()
            if recovered:
                logger.warning("运行期恢复中断工作流任务: %s", recovered)
        except Exception as error:
            logger.error("运行期 workflow 恢复任务失败: %s", error, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    validate_registry()
    logger.info("🚀 写作智能体 API 启动中...")
    seed_result = bootstrap_default_styles()
    logger.info(
        "默认风格初始化完成: writing=%s, cover=%s",
        seed_result["inserted_writing_styles"],
        seed_result["inserted_cover_styles"],
    )
    workflow_job_service = get_workflow_job_service()
    workflow_job_service.start()
    recovered_jobs = workflow_job_service.resume_stale_jobs()
    if recovered_jobs:
        logger.warning("检测并恢复中断工作流任务: %s", recovered_jobs)
    scheduler_task: asyncio.Task | None = asyncio.create_task(
        _github_trending_scheduler_loop()
    )
    linuxdo_scheduler_task: asyncio.Task | None = asyncio.create_task(
        _linuxdo_trending_scheduler_loop()
    )
    workflow_recovery_task: asyncio.Task | None = asyncio.create_task(
        _workflow_stale_recovery_loop()
    )
    try:
        yield
    finally:
        # 关闭时执行
        if scheduler_task:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
        if linuxdo_scheduler_task:
            linuxdo_scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await linuxdo_scheduler_task
        if workflow_recovery_task:
            workflow_recovery_task.cancel()
            with suppress(asyncio.CancelledError):
                await workflow_recovery_task
        workflow_job_service.stop()
        logger.info("👋 写作智能体 API 关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="写作智能体 API",
    description="基于 LangChain + LangGraph 的写作智能体后端服务",
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)
app.add_middleware(TraceContextMiddleware)

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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    ctx = current_context()
    status_code = int(exc.status_code)
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    payload = build_error_response(
        detail=detail,
        error_code=error_code_from_status(status_code),
        trace_id=ctx.trace_id,
        request_id=ctx.request_id,
        node_id=ctx.node_id,
        node_key=ctx.node_key,
        behavior_id=ctx.behavior_id,
        behavior_key=ctx.behavior_key,
    )
    emit_obs_event(
        level="ERROR" if status_code >= 500 else "WARNING",
        message="http.exception",
        error_code=payload["error_code"],
        api_path=request.url.path,
        http_method=request.method,
        http_status=status_code,
        payload={"detail": detail},
    )
    response = JSONResponse(status_code=status_code, content=payload)
    if exc.headers:
        for key, value in exc.headers.items():
            response.headers[key] = value
    if ctx.trace_id:
        response.headers["X-Trace-Id"] = ctx.trace_id
    if ctx.request_id:
        response.headers["X-Request-Id"] = ctx.request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    ctx = current_context()
    payload = build_error_response(
        detail="Internal Server Error",
        error_code="E_UNHANDLED_EXCEPTION",
        trace_id=ctx.trace_id,
        request_id=ctx.request_id,
        node_id=ctx.node_id,
        node_key=ctx.node_key,
        behavior_id=ctx.behavior_id,
        behavior_key=ctx.behavior_key,
    )
    logger.error("未处理异常: %s", exc, exc_info=True)
    emit_obs_event(
        level="ERROR",
        message="http.unhandled_exception",
        error_code="E_UNHANDLED_EXCEPTION",
        api_path=request.url.path,
        http_method=request.method,
        http_status=500,
        payload={"error": str(exc)},
    )
    response = JSONResponse(status_code=500, content=payload)
    if ctx.trace_id:
        response.headers["X-Trace-Id"] = ctx.trace_id
    if ctx.request_id:
        response.headers["X-Request-Id"] = ctx.request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    ctx = current_context()
    payload = build_error_response(
        detail="请求参数校验失败",
        error_code="E_VALIDATION",
        trace_id=ctx.trace_id,
        request_id=ctx.request_id,
        node_id=ctx.node_id,
        node_key=ctx.node_key,
        behavior_id=ctx.behavior_id,
        behavior_key=ctx.behavior_key,
    )
    payload["validation_errors"] = exc.errors()
    emit_obs_event(
        level="WARNING",
        message="http.validation_error",
        error_code="E_VALIDATION",
        api_path=request.url.path,
        http_method=request.method,
        http_status=422,
        payload={"errors": exc.errors()},
    )
    response = JSONResponse(status_code=422, content=payload)
    if ctx.trace_id:
        response.headers["X-Trace-Id"] = ctx.trace_id
    if ctx.request_id:
        response.headers["X-Request-Id"] = ctx.request_id
    return response


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
