"""
可观测统一错误结构。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ObservabilityError:
    error_code: str
    detail: str
    node_id: str = ""
    node_key: str = ""
    behavior_id: str = ""
    behavior_key: str = ""
    trace_id: str = ""
    request_id: str = ""
    http_status: int = 500

    def to_response_dict(self) -> dict:
        return {
            "detail": self.detail,
            "error_code": self.error_code,
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "node_id": self.node_id,
            "node_key": self.node_key,
            "behavior_id": self.behavior_id,
            "behavior_key": self.behavior_key,
        }


def build_error_response(
    detail: str,
    error_code: str,
    trace_id: str,
    request_id: str,
    node_id: str = "",
    node_key: str = "",
    behavior_id: str = "",
    behavior_key: str = "",
) -> dict:
    payload = {
        "detail": detail,
        "error_code": error_code,
        "trace_id": trace_id,
        "request_id": request_id,
        "node_id": node_id,
        "node_key": node_key,
        "behavior_id": behavior_id,
        "behavior_key": behavior_key,
    }
    return payload


def error_code_from_status(status_code: int) -> str:
    if status_code == 400:
        return "E_BAD_REQUEST"
    if status_code == 401:
        return "E_UNAUTHORIZED"
    if status_code == 403:
        return "E_FORBIDDEN"
    if status_code == 404:
        return "E_NOT_FOUND"
    if status_code == 409:
        return "E_CONFLICT"
    if status_code == 422:
        return "E_VALIDATION"
    if status_code >= 500:
        return "E_INTERNAL"
    return "E_HTTP_ERROR"
