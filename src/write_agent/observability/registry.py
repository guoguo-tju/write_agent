"""
可观测编号注册表（节点 + 行为模式）。
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Optional

from write_agent.core import get_logger, get_settings

logger = get_logger(__name__)
settings = get_settings()
_unknown_node_warned: set[str] = set()
_unknown_behavior_warned: set[str] = set()


@dataclass(frozen=True)
class BehaviorDef:
    behavior_id: str
    behavior_key: str
    description: str


@dataclass(frozen=True)
class NodeDef:
    node_id: str
    node_key: str
    module_path: str
    function_name: str
    owner: str
    description: str
    in_out_contract: str


UNKNOWN_BEHAVIOR = BehaviorDef(
    behavior_id="B000",
    behavior_key="UNKNOWN_BEHAVIOR",
    description="未知行为模式",
)

UNKNOWN_NODE = NodeDef(
    node_id="N000",
    node_key="UNKNOWN.NODE",
    module_path="",
    function_name="",
    owner="system",
    description="未知节点",
    in_out_contract="unknown",
)


BEHAVIOR_REGISTRY: dict[str, BehaviorDef] = {
    "HTTP_SYNC": BehaviorDef("B001", "HTTP_SYNC", "同步 HTTP 请求处理"),
    "HTTP_SSE_STREAM": BehaviorDef("B002", "HTTP_SSE_STREAM", "SSE 流式输出"),
    "WORKFLOW_NODE": BehaviorDef("B003", "WORKFLOW_NODE", "工作流节点执行"),
    "SCHEDULER_JOB": BehaviorDef("B004", "SCHEDULER_JOB", "定时调度任务"),
    "EXTERNAL_HTTP_CALL": BehaviorDef("B005", "EXTERNAL_HTTP_CALL", "外部 HTTP 调用"),
    "DB_READ": BehaviorDef("B006", "DB_READ", "数据库读操作"),
    "DB_WRITE": BehaviorDef("B007", "DB_WRITE", "数据库写操作"),
    "LLM_STREAM_CALL": BehaviorDef("B008", "LLM_STREAM_CALL", "LLM 流式调用"),
    "RAG_RETRIEVE": BehaviorDef("B009", "RAG_RETRIEVE", "RAG 检索"),
    "FILE_IO": BehaviorDef("B010", "FILE_IO", "文件读写"),
}


NODE_REGISTRY: dict[str, NodeDef] = {
    "API.MIDDLEWARE.REQUEST": NodeDef(
        node_id="N001",
        node_key="API.MIDDLEWARE.REQUEST",
        module_path="write_agent.observability.middleware",
        function_name="TraceContextMiddleware",
        owner="backend",
        description="全局请求入口中间件",
        in_out_contract="http request -> response",
    ),
    "API.REWRITES.CREATE": NodeDef(
        node_id="N010",
        node_key="API.REWRITES.CREATE",
        module_path="write_agent.api.rewrites",
        function_name="create_rewrite",
        owner="backend",
        description="改写 POST 入口",
        in_out_contract="create rewrite sse",
    ),
    "API.REWRITES.STREAM": NodeDef(
        node_id="N011",
        node_key="API.REWRITES.STREAM",
        module_path="write_agent.api.rewrites",
        function_name="rewrite_stream",
        owner="backend",
        description="改写 GET SSE 入口",
        in_out_contract="rewrite stream",
    ),
    "API.REWRITES.SSE_EVENT": NodeDef(
        node_id="N012",
        node_key="API.REWRITES.SSE_EVENT",
        module_path="write_agent.api.rewrites",
        function_name="create_rewrite",
        owner="backend",
        description="改写 SSE 事件发射",
        in_out_contract="rewrite chunk -> sse event",
    ),
    "API.REVIEWS.CREATE": NodeDef(
        node_id="N020",
        node_key="API.REVIEWS.CREATE",
        module_path="write_agent.api.reviews",
        function_name="create_review",
        owner="backend",
        description="审核 POST 入口",
        in_out_contract="create review sse",
    ),
    "API.REVIEWS.WORKFLOW": NodeDef(
        node_id="N021",
        node_key="API.REVIEWS.WORKFLOW",
        module_path="write_agent.api.reviews",
        function_name="create_workflow",
        owner="backend",
        description="完整工作流 SSE 入口",
        in_out_contract="workflow stream",
    ),
    "API.REVIEWS.SSE_EVENT": NodeDef(
        node_id="N022",
        node_key="API.REVIEWS.SSE_EVENT",
        module_path="write_agent.api.reviews",
        function_name="create_workflow",
        owner="backend",
        description="审核/工作流 SSE 事件发射",
        in_out_contract="workflow event -> sse",
    ),
    "API.REVIEWS.WORKFLOW_JOBS_CREATE": NodeDef(
        node_id="N197",
        node_key="API.REVIEWS.WORKFLOW_JOBS_CREATE",
        module_path="write_agent.api.reviews",
        function_name="create_workflow_job",
        owner="backend",
        description="异步工作流任务创建入口",
        in_out_contract="create workflow job",
    ),
    "API.REVIEWS.WORKFLOW_JOB_STATUS": NodeDef(
        node_id="N198",
        node_key="API.REVIEWS.WORKFLOW_JOB_STATUS",
        module_path="write_agent.api.reviews",
        function_name="get_workflow_job_status",
        owner="backend",
        description="异步工作流任务状态查询",
        in_out_contract="job id -> status",
    ),
    "API.REVIEWS.WORKFLOW_JOB_STREAM": NodeDef(
        node_id="N199",
        node_key="API.REVIEWS.WORKFLOW_JOB_STREAM",
        module_path="write_agent.api.reviews",
        function_name="stream_workflow_job_events",
        owner="backend",
        description="异步工作流任务 SSE 输出",
        in_out_contract="job id -> event stream",
    ),
    "API.REVIEWS.WORKFLOW_JOB_RESUME": NodeDef(
        node_id="N200",
        node_key="API.REVIEWS.WORKFLOW_JOB_RESUME",
        module_path="write_agent.api.reviews",
        function_name="resume_workflow_job",
        owner="backend",
        description="异步工作流任务恢复",
        in_out_contract="job id -> resumed",
    ),
    "API.REVIEWS.WORKFLOW_JOB_CANCEL": NodeDef(
        node_id="N201",
        node_key="API.REVIEWS.WORKFLOW_JOB_CANCEL",
        module_path="write_agent.api.reviews",
        function_name="cancel_workflow_job",
        owner="backend",
        description="异步工作流任务取消",
        in_out_contract="job id -> cancelled",
    ),
    "API.COVERS.GENERATE": NodeDef(
        node_id="N030",
        node_key="API.COVERS.GENERATE",
        module_path="write_agent.api.covers",
        function_name="generate_cover",
        owner="backend",
        description="封面生成 SSE 入口",
        in_out_contract="cover generation stream",
    ),
    "API.COVERS.SSE_EVENT": NodeDef(
        node_id="N031",
        node_key="API.COVERS.SSE_EVENT",
        module_path="write_agent.api.covers",
        function_name="_generate_cover_events",
        owner="backend",
        description="封面 SSE 事件发射",
        in_out_contract="cover event -> sse",
    ),
    "API.COVERS.MANUAL_REWRITE": NodeDef(
        node_id="N032",
        node_key="API.COVERS.MANUAL_REWRITE",
        module_path="write_agent.api.covers",
        function_name="create_manual_cover_rewrite",
        owner="backend",
        description="手动封面输入转 rewrite 记录入口",
        in_out_contract="title/content -> rewrite_id",
    ),
    "API.STYLES.EXTRACT": NodeDef(
        node_id="N040",
        node_key="API.STYLES.EXTRACT",
        module_path="write_agent.api.styles",
        function_name="extract_style",
        owner="backend",
        description="风格提取入口",
        in_out_contract="style extraction",
    ),
    "API.MATERIALS.CREATE": NodeDef(
        node_id="N050",
        node_key="API.MATERIALS.CREATE",
        module_path="write_agent.api.materials",
        function_name="create_material",
        owner="backend",
        description="素材创建入口",
        in_out_contract="create material",
    ),
    "API.GITHUB_TRENDS.ADD_ITEM": NodeDef(
        node_id="N060",
        node_key="API.GITHUB_TRENDS.ADD_ITEM",
        module_path="write_agent.api.github_trends",
        function_name="add_item_to_materials",
        owner="backend",
        description="趋势行级入素材入口",
        in_out_contract="add trend item",
    ),
    "API.GITHUB_TRENDS.BUILD_REWRITE": NodeDef(
        node_id="N061",
        node_key="API.GITHUB_TRENDS.BUILD_REWRITE",
        module_path="write_agent.api.github_trends",
        function_name="build_item_rewrite_markdown",
        owner="backend",
        description="趋势改写预填构建入口",
        in_out_contract="build rewrite prefill",
    ),
    "API.GITHUB_TRENDS.GET": NodeDef(
        node_id="N062",
        node_key="API.GITHUB_TRENDS.GET",
        module_path="write_agent.api.github_trends",
        function_name="get_github_trends",
        owner="backend",
        description="趋势快照查询入口",
        in_out_contract="query trend snapshot",
    ),
    "API.GITHUB_TRENDS.WEEKS": NodeDef(
        node_id="N063",
        node_key="API.GITHUB_TRENDS.WEEKS",
        module_path="write_agent.api.github_trends",
        function_name="get_github_trend_weeks",
        owner="backend",
        description="趋势周列表入口",
        in_out_contract="query weeks",
    ),
    "API.GITHUB_TRENDS.PERIODS": NodeDef(
        node_id="N166",
        node_key="API.GITHUB_TRENDS.PERIODS",
        module_path="write_agent.api.github_trends",
        function_name="get_github_trend_periods",
        owner="backend",
        description="趋势周期列表入口",
        in_out_contract="query periods",
    ),
    "API.GITHUB_TRENDS.REFRESH": NodeDef(
        node_id="N064",
        node_key="API.GITHUB_TRENDS.REFRESH",
        module_path="write_agent.api.github_trends",
        function_name="refresh_github_trends",
        owner="backend",
        description="趋势刷新入口",
        in_out_contract="refresh week snapshot",
    ),
    "API.GITHUB_TRENDS.ADD_WEEK_DIGEST": NodeDef(
        node_id="N065",
        node_key="API.GITHUB_TRENDS.ADD_WEEK_DIGEST",
        module_path="write_agent.api.github_trends",
        function_name="add_week_digest_to_materials",
        owner="backend",
        description="趋势周报入素材入口",
        in_out_contract="add week digest material",
    ),
    "API.XHS_TRENDS.CATEGORIES": NodeDef(
        node_id="N180",
        node_key="API.XHS_TRENDS.CATEGORIES",
        module_path="write_agent.api.xhs_trends",
        function_name="list_xhs_categories",
        owner="backend",
        description="小红书分类入口",
        in_out_contract="categories list",
    ),
    "API.XHS_TRENDS.GET": NodeDef(
        node_id="N181",
        node_key="API.XHS_TRENDS.GET",
        module_path="write_agent.api.xhs_trends",
        function_name="get_xhs_trends",
        owner="backend",
        description="小红书热点查询入口",
        in_out_contract="query xhs trends",
    ),
    "API.XHS_TRENDS.REFRESH": NodeDef(
        node_id="N182",
        node_key="API.XHS_TRENDS.REFRESH",
        module_path="write_agent.api.xhs_trends",
        function_name="refresh_xhs_trends",
        owner="backend",
        description="小红书热点刷新入口",
        in_out_contract="refresh xhs trends",
    ),
    "API.XHS_TRENDS.REFRESH_STATUS": NodeDef(
        node_id="N183",
        node_key="API.XHS_TRENDS.REFRESH_STATUS",
        module_path="write_agent.api.xhs_trends",
        function_name="get_xhs_refresh_status",
        owner="backend",
        description="小红书热点刷新状态入口",
        in_out_contract="refresh status",
    ),
    "API.XHS_TRENDS.ANALYSIS_STREAM": NodeDef(
        node_id="N184",
        node_key="API.XHS_TRENDS.ANALYSIS_STREAM",
        module_path="write_agent.api.xhs_trends",
        function_name="stream_xhs_trend_analysis",
        owner="backend",
        description="小红书热点分析流入口",
        in_out_contract="analysis stream",
    ),
    "API.XHS_TRENDS.SSE_EVENT": NodeDef(
        node_id="N185",
        node_key="API.XHS_TRENDS.SSE_EVENT",
        module_path="write_agent.api.xhs_trends",
        function_name="_analysis_sse_with_obs",
        owner="backend",
        description="小红书热点 SSE 事件",
        in_out_contract="analysis event -> sse",
    ),
    "API.LINUXDO_TRENDS.GET": NodeDef(
        node_id="N208",
        node_key="API.LINUXDO_TRENDS.GET",
        module_path="write_agent.api.linuxdo_trends",
        function_name="get_linuxdo_trends",
        owner="backend",
        description="Linux.do 趋势查询入口",
        in_out_contract="query linuxdo trends",
    ),
    "API.LINUXDO_TRENDS.PERIODS": NodeDef(
        node_id="N209",
        node_key="API.LINUXDO_TRENDS.PERIODS",
        module_path="write_agent.api.linuxdo_trends",
        function_name="get_linuxdo_trend_periods",
        owner="backend",
        description="Linux.do 周期列表入口",
        in_out_contract="query linuxdo periods",
    ),
    "API.LINUXDO_TRENDS.REFRESH": NodeDef(
        node_id="N210",
        node_key="API.LINUXDO_TRENDS.REFRESH",
        module_path="write_agent.api.linuxdo_trends",
        function_name="refresh_linuxdo_trends",
        owner="backend",
        description="Linux.do 趋势刷新入口",
        in_out_contract="refresh linuxdo trends",
    ),
    "API.LINUXDO_TRENDS.TOPIC_DETAIL": NodeDef(
        node_id="N211",
        node_key="API.LINUXDO_TRENDS.TOPIC_DETAIL",
        module_path="write_agent.api.linuxdo_trends",
        function_name="get_linuxdo_topic_detail",
        owner="backend",
        description="Linux.do 帖子详情入口",
        in_out_contract="topic id -> topic detail",
    ),
    "API.LINUXDO_TRENDS.ADD_ITEM": NodeDef(
        node_id="N212",
        node_key="API.LINUXDO_TRENDS.ADD_ITEM",
        module_path="write_agent.api.linuxdo_trends",
        function_name="add_linuxdo_item_to_materials",
        owner="backend",
        description="Linux.do 单条入素材入口",
        in_out_contract="add linuxdo item",
    ),
    "API.LINUXDO_TRENDS.BUILD_REWRITE": NodeDef(
        node_id="N213",
        node_key="API.LINUXDO_TRENDS.BUILD_REWRITE",
        module_path="write_agent.api.linuxdo_trends",
        function_name="build_linuxdo_item_rewrite",
        owner="backend",
        description="Linux.do 单条改写预填入口",
        in_out_contract="build linuxdo rewrite prefill",
    ),
    "SVC.REWRITE.CREATE": NodeDef(
        node_id="N070",
        node_key="SVC.REWRITE.CREATE",
        module_path="write_agent.services.rewrite_service",
        function_name="create_rewrite",
        owner="backend",
        description="改写记录创建服务",
        in_out_contract="source/style -> rewrite record",
    ),
    "SVC.REWRITE.STREAM": NodeDef(
        node_id="N071",
        node_key="SVC.REWRITE.STREAM",
        module_path="write_agent.services.rewrite_service",
        function_name="rewrite",
        owner="backend",
        description="改写流式执行服务",
        in_out_contract="rewrite id -> stream chunks",
    ),
    "SVC.REVIEW.CREATE": NodeDef(
        node_id="N080",
        node_key="SVC.REVIEW.CREATE",
        module_path="write_agent.services.review_service",
        function_name="create_review",
        owner="backend",
        description="审核记录创建服务",
        in_out_contract="rewrite content -> review record",
    ),
    "SVC.REVIEW.STREAM": NodeDef(
        node_id="N081",
        node_key="SVC.REVIEW.STREAM",
        module_path="write_agent.services.review_service",
        function_name="review",
        owner="backend",
        description="审核流式执行服务",
        in_out_contract="review id -> stream chunks",
    ),
    "SVC.WORKFLOW.RUN_STREAM": NodeDef(
        node_id="N090",
        node_key="SVC.WORKFLOW.RUN_STREAM",
        module_path="write_agent.services.workflow_service",
        function_name="run_stream",
        owner="backend",
        description="工作流闭环执行服务",
        in_out_contract="source/style -> loop events",
    ),
    "SVC.WORKFLOW.JOB.CREATE": NodeDef(
        node_id="N202",
        node_key="SVC.WORKFLOW.JOB.CREATE",
        module_path="write_agent.services.workflow_job_service",
        function_name="create_job",
        owner="backend",
        description="异步工作流任务创建服务",
        in_out_contract="request -> workflow job",
    ),
    "SVC.WORKFLOW.JOB.ENQUEUE": NodeDef(
        node_id="N203",
        node_key="SVC.WORKFLOW.JOB.ENQUEUE",
        module_path="write_agent.services.workflow_job_service",
        function_name="enqueue_job",
        owner="backend",
        description="异步工作流任务入队",
        in_out_contract="job id -> queue",
    ),
    "SVC.WORKFLOW.JOB.RUN": NodeDef(
        node_id="N204",
        node_key="SVC.WORKFLOW.JOB.RUN",
        module_path="write_agent.services.workflow_job_service",
        function_name="run_job",
        owner="backend",
        description="异步工作流任务执行",
        in_out_contract="job id -> stage events",
    ),
    "SVC.WORKFLOW.JOB.RECOVER": NodeDef(
        node_id="N205",
        node_key="SVC.WORKFLOW.JOB.RECOVER",
        module_path="write_agent.services.workflow_job_service",
        function_name="resume_stale_jobs",
        owner="backend",
        description="中断任务恢复",
        in_out_contract="stale jobs -> resumed jobs",
    ),
    "SVC.WORKFLOW.JOB.RESUME": NodeDef(
        node_id="N206",
        node_key="SVC.WORKFLOW.JOB.RESUME",
        module_path="write_agent.services.workflow_job_service",
        function_name="resume_job",
        owner="backend",
        description="任务手动恢复",
        in_out_contract="job id -> resumed",
    ),
    "SVC.WORKFLOW.JOB.CANCEL": NodeDef(
        node_id="N207",
        node_key="SVC.WORKFLOW.JOB.CANCEL",
        module_path="write_agent.services.workflow_job_service",
        function_name="cancel_job",
        owner="backend",
        description="任务取消",
        in_out_contract="job id -> cancelled",
    ),
    "SVC.COVER.GENERATE_PROMPT": NodeDef(
        node_id="N100",
        node_key="SVC.COVER.GENERATE_PROMPT",
        module_path="write_agent.services.cover_service",
        function_name="generate_prompt",
        owner="backend",
        description="封面提示词生成服务",
        in_out_contract="content/style -> prompt",
    ),
    "SVC.COVER.GENERATE_IMAGE": NodeDef(
        node_id="N101",
        node_key="SVC.COVER.GENERATE_IMAGE",
        module_path="write_agent.services.cover_service",
        function_name="generate_image",
        owner="backend",
        description="封面图片生成服务",
        in_out_contract="prompt/size -> image url",
    ),
    "SVC.MATERIAL.CREATE": NodeDef(
        node_id="N110",
        node_key="SVC.MATERIAL.CREATE",
        module_path="write_agent.services.material_service",
        function_name="create_material",
        owner="backend",
        description="素材创建服务",
        in_out_contract="material payload -> material record",
    ),
    "SVC.MATERIAL.UPDATE": NodeDef(
        node_id="N111",
        node_key="SVC.MATERIAL.UPDATE",
        module_path="write_agent.services.material_service",
        function_name="update_material",
        owner="backend",
        description="素材更新服务",
        in_out_contract="material patch -> material record",
    ),
    "SVC.STYLE.EXTRACT": NodeDef(
        node_id="N120",
        node_key="SVC.STYLE.EXTRACT",
        module_path="write_agent.services.style_service",
        function_name="extract_style",
        owner="backend",
        description="风格提取服务",
        in_out_contract="articles -> style",
    ),
    "SVC.GITHUB_TRENDS.REFRESH": NodeDef(
        node_id="N130",
        node_key="SVC.GITHUB_TRENDS.REFRESH",
        module_path="write_agent.services.github_trending_service",
        function_name="refresh_snapshot",
        owner="backend",
        description="趋势刷新服务",
        in_out_contract="refresh period snapshot",
    ),
    "SVC.GITHUB_TRENDS.PERIODS": NodeDef(
        node_id="N136",
        node_key="SVC.GITHUB_TRENDS.PERIODS",
        module_path="write_agent.services.github_trending_service",
        function_name="list_available_periods",
        owner="backend",
        description="趋势周期列表查询服务",
        in_out_contract="periods list",
    ),
    "SVC.GITHUB_TRENDS.ADD_ITEM": NodeDef(
        node_id="N131",
        node_key="SVC.GITHUB_TRENDS.ADD_ITEM",
        module_path="write_agent.services.github_trending_service",
        function_name="add_item_to_materials",
        owner="backend",
        description="趋势行级入素材服务",
        in_out_contract="week/repo -> material",
    ),
    "SVC.GITHUB_TRENDS.BUILD_REWRITE": NodeDef(
        node_id="N132",
        node_key="SVC.GITHUB_TRENDS.BUILD_REWRITE",
        module_path="write_agent.services.github_trending_service",
        function_name="build_item_rewrite_markdown",
        owner="backend",
        description="趋势改写预填服务",
        in_out_contract="week/repo -> markdown",
    ),
    "SVC.GITHUB_TRENDS.GET_SNAPSHOT": NodeDef(
        node_id="N133",
        node_key="SVC.GITHUB_TRENDS.GET_SNAPSHOT",
        module_path="write_agent.services.github_trending_service",
        function_name="get_snapshot",
        owner="backend",
        description="趋势快照查询服务",
        in_out_contract="week -> snapshot payload",
    ),
    "SVC.GITHUB_TRENDS.WEEKS": NodeDef(
        node_id="N134",
        node_key="SVC.GITHUB_TRENDS.WEEKS",
        module_path="write_agent.services.github_trending_service",
        function_name="list_available_weeks",
        owner="backend",
        description="趋势周列表查询服务",
        in_out_contract="weeks list",
    ),
    "SVC.GITHUB_TRENDS.ADD_WEEK_DIGEST": NodeDef(
        node_id="N135",
        node_key="SVC.GITHUB_TRENDS.ADD_WEEK_DIGEST",
        module_path="write_agent.services.github_trending_service",
        function_name="add_week_digest_to_materials",
        owner="backend",
        description="趋势周报入素材服务",
        in_out_contract="week -> material",
    ),
    "SVC.XHS_TRENDS.CATEGORIES": NodeDef(
        node_id="N186",
        node_key="SVC.XHS_TRENDS.CATEGORIES",
        module_path="write_agent.services.xhs_trends_service",
        function_name="list_categories",
        owner="backend",
        description="小红书分类服务",
        in_out_contract="categories file -> list",
    ),
    "SVC.XHS_TRENDS.REFRESH": NodeDef(
        node_id="N187",
        node_key="SVC.XHS_TRENDS.REFRESH",
        module_path="write_agent.services.xhs_trends_service",
        function_name="refresh",
        owner="backend",
        description="小红书热点刷新服务",
        in_out_contract="category -> cached trends",
    ),
    "SVC.XHS_TRENDS.GET": NodeDef(
        node_id="N188",
        node_key="SVC.XHS_TRENDS.GET",
        module_path="write_agent.services.xhs_trends_service",
        function_name="get_trends",
        owner="backend",
        description="小红书热点查询服务",
        in_out_contract="category cache -> filtered trends",
    ),
    "SVC.XHS_TRENDS.ANALYZE": NodeDef(
        node_id="N189",
        node_key="SVC.XHS_TRENDS.ANALYZE",
        module_path="write_agent.services.xhs_trends_service",
        function_name="build_analysis",
        owner="backend",
        description="小红书热点分析服务",
        in_out_contract="trends -> analysis",
    ),
    "SVC.XHS_TRENDS.STATUS": NodeDef(
        node_id="N190",
        node_key="SVC.XHS_TRENDS.STATUS",
        module_path="write_agent.services.xhs_trends_service",
        function_name="get_refresh_status",
        owner="backend",
        description="小红书热点刷新状态服务",
        in_out_contract="refresh cache -> status",
    ),
    "SVC.XHS_TRENDS.MCP_CALL": NodeDef(
        node_id="N191",
        node_key="SVC.XHS_TRENDS.MCP_CALL",
        module_path="write_agent.services.xhs_trends_service",
        function_name="_mcp_call_tool",
        owner="backend",
        description="小红书 MCP 调用服务",
        in_out_contract="tool call -> mcp result",
    ),
    "SVC.LINUXDO_TRENDS.REFRESH": NodeDef(
        node_id="N214",
        node_key="SVC.LINUXDO_TRENDS.REFRESH",
        module_path="write_agent.services.linuxdo_trending_service",
        function_name="refresh_snapshot",
        owner="backend",
        description="Linux.do 趋势刷新服务",
        in_out_contract="refresh linuxdo period snapshot",
    ),
    "SVC.LINUXDO_TRENDS.GET": NodeDef(
        node_id="N215",
        node_key="SVC.LINUXDO_TRENDS.GET",
        module_path="write_agent.services.linuxdo_trending_service",
        function_name="get_snapshot",
        owner="backend",
        description="Linux.do 趋势查询服务",
        in_out_contract="period snapshot -> trends payload",
    ),
    "SVC.LINUXDO_TRENDS.PERIODS": NodeDef(
        node_id="N216",
        node_key="SVC.LINUXDO_TRENDS.PERIODS",
        module_path="write_agent.services.linuxdo_trending_service",
        function_name="list_periods",
        owner="backend",
        description="Linux.do 周期列表服务",
        in_out_contract="period type -> periods list",
    ),
    "SVC.LINUXDO_TRENDS.TOPIC_DETAIL": NodeDef(
        node_id="N217",
        node_key="SVC.LINUXDO_TRENDS.TOPIC_DETAIL",
        module_path="write_agent.services.linuxdo_trending_service",
        function_name="get_topic_detail",
        owner="backend",
        description="Linux.do 帖子详情服务",
        in_out_contract="topic id -> topic detail",
    ),
    "SVC.LINUXDO_TRENDS.ADD_ITEM": NodeDef(
        node_id="N218",
        node_key="SVC.LINUXDO_TRENDS.ADD_ITEM",
        module_path="write_agent.services.linuxdo_trending_service",
        function_name="add_item_to_materials",
        owner="backend",
        description="Linux.do 单条入素材服务",
        in_out_contract="period/topic -> material",
    ),
    "SVC.LINUXDO_TRENDS.BUILD_REWRITE": NodeDef(
        node_id="N219",
        node_key="SVC.LINUXDO_TRENDS.BUILD_REWRITE",
        module_path="write_agent.services.linuxdo_trending_service",
        function_name="build_item_rewrite_markdown",
        owner="backend",
        description="Linux.do 单条改写预填服务",
        in_out_contract="period/topic -> markdown",
    ),
    "SVC.RAG.RETRIEVE": NodeDef(
        node_id="N140",
        node_key="SVC.RAG.RETRIEVE",
        module_path="write_agent.services.rag_service",
        function_name="search",
        owner="backend",
        description="RAG 检索服务",
        in_out_contract="query -> retrieved materials",
    ),
    "SVC.LLM.CHAT": NodeDef(
        node_id="N150",
        node_key="SVC.LLM.CHAT",
        module_path="write_agent.services.llm_service",
        function_name="chat",
        owner="backend",
        description="LLM 同步对话调用",
        in_out_contract="messages -> response text",
    ),
    "SVC.LLM.STREAM": NodeDef(
        node_id="N151",
        node_key="SVC.LLM.STREAM",
        module_path="write_agent.services.llm_service",
        function_name="stream",
        owner="backend",
        description="LLM 流式调用",
        in_out_contract="messages -> streaming chunks",
    ),
    "JOB.GITHUB_TRENDS.SCHEDULER": NodeDef(
        node_id="N160",
        node_key="JOB.GITHUB_TRENDS.SCHEDULER",
        module_path="write_agent.main",
        function_name="_github_trending_scheduler_loop",
        owner="backend",
        description="趋势定时调度任务",
        in_out_contract="time trigger -> refresh snapshot",
    ),
    "JOB.LINUXDO_TRENDS.SCHEDULER": NodeDef(
        node_id="N220",
        node_key="JOB.LINUXDO_TRENDS.SCHEDULER",
        module_path="write_agent.main",
        function_name="_linuxdo_trending_scheduler_loop",
        owner="backend",
        description="Linux.do 趋势定时调度任务",
        in_out_contract="time trigger -> refresh linuxdo snapshots",
    ),
    "OBS.API.QUERY_EVENTS": NodeDef(
        node_id="N170",
        node_key="OBS.API.QUERY_EVENTS",
        module_path="write_agent.api.observability",
        function_name="query_observability_events",
        owner="backend",
        description="查询观测事件",
        in_out_contract="query -> event list",
    ),
    "OBS.API.TRACE_DETAIL": NodeDef(
        node_id="N171",
        node_key="OBS.API.TRACE_DETAIL",
        module_path="write_agent.api.observability",
        function_name="get_trace_timeline",
        owner="backend",
        description="查询 trace 时间线",
        in_out_contract="trace_id -> timeline",
    ),
    "OBS.API.NODES": NodeDef(
        node_id="N172",
        node_key="OBS.API.NODES",
        module_path="write_agent.api.observability",
        function_name="list_observability_nodes",
        owner="backend",
        description="查询节点注册表",
        in_out_contract="nodes list",
    ),
    "OBS.API.NODE_DETAIL": NodeDef(
        node_id="N173",
        node_key="OBS.API.NODE_DETAIL",
        module_path="write_agent.api.observability",
        function_name="get_observability_node",
        owner="backend",
        description="查询节点详情",
        in_out_contract="node_id -> node detail",
    ),
}


def is_strict_mode() -> bool:
    if not settings.obs_strict_dev:
        return False
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return bool(settings.debug)


def resolve_behavior(behavior_key: Optional[str]) -> BehaviorDef:
    key = (behavior_key or "").strip()
    if key in BEHAVIOR_REGISTRY:
        return BEHAVIOR_REGISTRY[key]
    if is_strict_mode() and key:
        raise ValueError(f"E_BEHAVIOR_UNREGISTERED: {key}")
    if key and key not in _unknown_behavior_warned:
        _unknown_behavior_warned.add(key)
        logger.warning("未注册行为模式，降级为 UNKNOWN_BEHAVIOR: %s", key)
    return UNKNOWN_BEHAVIOR


def resolve_node(node_key: Optional[str]) -> NodeDef:
    key = (node_key or "").strip()
    if key in NODE_REGISTRY:
        return NODE_REGISTRY[key]
    if is_strict_mode() and key:
        raise ValueError(f"E_NODE_UNREGISTERED: {key}")
    if key and key not in _unknown_node_warned:
        _unknown_node_warned.add(key)
        logger.warning("未注册节点，降级为 UNKNOWN.NODE: %s", key)
    return UNKNOWN_NODE


def _mapping_exists(module, function_name: str) -> bool:
    if hasattr(module, function_name):
        return True
    for attr_name in dir(module):
        candidate = getattr(module, attr_name, None)
        if isinstance(candidate, type) and hasattr(candidate, function_name):
            return True
    return False


def validate_registry() -> None:
    node_ids = [node.node_id for node in NODE_REGISTRY.values()]
    node_keys = [node.node_key for node in NODE_REGISTRY.values()]
    if len(node_ids) != len(set(node_ids)):
        raise RuntimeError("observability node_id 存在重复")
    if len(node_keys) != len(set(node_keys)):
        raise RuntimeError("observability node_key 存在重复")

    behavior_ids = [item.behavior_id for item in BEHAVIOR_REGISTRY.values()]
    behavior_keys = [item.behavior_key for item in BEHAVIOR_REGISTRY.values()]
    if len(behavior_ids) != len(set(behavior_ids)):
        raise RuntimeError("observability behavior_id 存在重复")
    if len(behavior_keys) != len(set(behavior_keys)):
        raise RuntimeError("observability behavior_key 存在重复")

    # 严格模式下校验代码映射是否存在。
    if is_strict_mode():
        for node in NODE_REGISTRY.values():
            module = importlib.import_module(node.module_path)
            if not _mapping_exists(module, node.function_name):
                raise RuntimeError(
                    f"observability 节点映射无效: {node.node_key} -> "
                    f"{node.module_path}.{node.function_name}"
                )

    logger.info(
        "可观测注册表加载完成: nodes=%s, behaviors=%s",
        len(NODE_REGISTRY),
        len(BEHAVIOR_REGISTRY),
    )
