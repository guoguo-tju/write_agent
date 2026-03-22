"""
可观测上下文管理（contextvars）。
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Optional


_trace_id_var: ContextVar[str] = ContextVar("obs_trace_id", default="")
_request_id_var: ContextVar[str] = ContextVar("obs_request_id", default="")
_node_id_var: ContextVar[str] = ContextVar("obs_node_id", default="")
_node_key_var: ContextVar[str] = ContextVar("obs_node_key", default="")
_behavior_id_var: ContextVar[str] = ContextVar("obs_behavior_id", default="")
_behavior_key_var: ContextVar[str] = ContextVar("obs_behavior_key", default="")
_entity_ctx_var: ContextVar[dict[str, Any]] = ContextVar("obs_entity_ctx", default={})


@dataclass
class ObsContext:
    trace_id: str
    request_id: str
    node_id: str
    node_key: str
    behavior_id: str
    behavior_key: str
    entities: dict[str, Any]


def generate_trace_id() -> str:
    return uuid.uuid4().hex


def generate_request_id() -> str:
    return uuid.uuid4().hex


def set_trace_request(trace_id: Optional[str], request_id: Optional[str]) -> tuple[Token, Token]:
    trace_token = _trace_id_var.set((trace_id or "").strip())
    request_token = _request_id_var.set((request_id or "").strip())
    return trace_token, request_token


def reset_trace_request(tokens: tuple[Token, Token]) -> None:
    trace_token, request_token = tokens
    _trace_id_var.reset(trace_token)
    _request_id_var.reset(request_token)


def set_node_behavior(
    node_id: str,
    node_key: str,
    behavior_id: str,
    behavior_key: str,
) -> tuple[Token, Token, Token, Token]:
    t1 = _node_id_var.set(node_id)
    t2 = _node_key_var.set(node_key)
    t3 = _behavior_id_var.set(behavior_id)
    t4 = _behavior_key_var.set(behavior_key)
    return t1, t2, t3, t4


def reset_node_behavior(tokens: tuple[Token, Token, Token, Token]) -> None:
    t1, t2, t3, t4 = tokens
    _node_id_var.reset(t1)
    _node_key_var.reset(t2)
    _behavior_id_var.reset(t3)
    _behavior_key_var.reset(t4)


def merge_entities(extra: Optional[dict[str, Any]]) -> tuple[dict[str, Any], Token]:
    current = dict(_entity_ctx_var.get() or {})
    merged = {**current, **(extra or {})}
    token = _entity_ctx_var.set(merged)
    return merged, token


def reset_entities(token: Token) -> None:
    _entity_ctx_var.reset(token)


def bind_entities(extra: Optional[dict[str, Any]]) -> None:
    current = dict(_entity_ctx_var.get() or {})
    _entity_ctx_var.set({**current, **(extra or {})})


def current_context() -> ObsContext:
    return ObsContext(
        trace_id=_trace_id_var.get(),
        request_id=_request_id_var.get(),
        node_id=_node_id_var.get(),
        node_key=_node_key_var.get(),
        behavior_id=_behavior_id_var.get(),
        behavior_key=_behavior_key_var.get(),
        entities=dict(_entity_ctx_var.get() or {}),
    )


@contextmanager
def scoped_node_behavior(
    node_id: str,
    node_key: str,
    behavior_id: str,
    behavior_key: str,
    entities: Optional[dict[str, Any]] = None,
):
    node_tokens = set_node_behavior(node_id, node_key, behavior_id, behavior_key)
    _, entity_token = merge_entities(entities)
    try:
        yield
    finally:
        reset_entities(entity_token)
        reset_node_behavior(node_tokens)
