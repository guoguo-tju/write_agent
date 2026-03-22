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
        function_name="refresh_current_week_snapshot",
        owner="backend",
        description="趋势刷新服务",
        in_out_contract="refresh current week snapshot",
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
