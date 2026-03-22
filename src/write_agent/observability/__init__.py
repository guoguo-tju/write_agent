"""
可观测能力导出。
"""
from .context import (
    current_context,
    bind_entities,
    generate_trace_id,
    generate_request_id,
)
from .emitter import get_observability_emitter
from .middleware import TraceContextMiddleware
from .registry import (
    NODE_REGISTRY,
    BEHAVIOR_REGISTRY,
    resolve_node,
    resolve_behavior,
    validate_registry,
)
from .utils import emit_obs_event, obs_scope, attach_obs_meta, build_obs_meta

__all__ = [
    "current_context",
    "bind_entities",
    "generate_trace_id",
    "generate_request_id",
    "get_observability_emitter",
    "TraceContextMiddleware",
    "NODE_REGISTRY",
    "BEHAVIOR_REGISTRY",
    "resolve_node",
    "resolve_behavior",
    "validate_registry",
    "emit_obs_event",
    "obs_scope",
    "attach_obs_meta",
    "build_obs_meta",
]
