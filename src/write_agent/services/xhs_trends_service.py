"""
小红书热点服务。
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests

from write_agent.core import get_logger, get_settings
from write_agent.observability import emit_obs_event, obs_scope

logger = get_logger(__name__)
settings = get_settings()


_DEFAULT_CATEGORIES = [
    {
        "key": "tech",
        "name": "科技",
        "name_en": "Tech",
        "keywords": ["AI", "AIGC", "编程", "科技趋势", "效率工具"],
    },
    {
        "key": "workplace",
        "name": "职场",
        "name_en": "Workplace",
        "keywords": ["职场", "面试", "简历", "升职", "副业"],
    },
    {
        "key": "food",
        "name": "美食",
        "name_en": "Food",
        "keywords": ["美食", "探店", "家常菜", "减脂餐", "咖啡"],
    },
    {
        "key": "emotion",
        "name": "情感",
        "name_en": "Emotion",
        "keywords": ["情感", "恋爱", "两性关系", "亲密关系", "分手"],
    },
    {
        "key": "growth",
        "name": "个人成长",
        "name_en": "Personal Growth",
        "keywords": ["个人成长", "自律", "时间管理", "学习方法", "复盘"],
    },
]


@dataclass
class XhsCategory:
    key: str
    name: str
    name_en: str
    keywords: list[str]

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "name": self.name,
            "name_en": self.name_en,
        }


class XhsTrendsService:
    """小红书热点抓取、缓存与分析。"""

    def __init__(
        self,
        *,
        categories_file: Optional[str] = None,
        cache_file: Optional[str] = None,
    ) -> None:
        self.timezone = ZoneInfo(settings.xhs_trends_timezone)
        self.lookback_days = max(1, int(settings.xhs_trends_lookback_days))
        self.min_interactions = max(0, int(settings.xhs_trends_min_interactions))
        self.default_limit = max(1, int(settings.xhs_trends_default_limit))
        self.timeout_seconds = max(1.0, float(settings.xhs_trends_timeout_seconds))
        self.mcp_timeout_seconds = max(1.0, float(settings.xhs_mcp_timeout_seconds))
        self.max_keywords_per_category = max(1, int(settings.xhs_trends_max_keywords_per_category))
        self.comment_detail_limit = max(0, int(settings.xhs_trends_comment_detail_limit))
        self.mcp_url = settings.xhs_mcp_url.strip()
        self.mcp_browser_path = settings.xhs_mcp_browser_path.strip()
        self.categories_file = Path(categories_file or settings.xhs_trends_categories_file)
        self.cache_file = Path(cache_file or settings.xhs_trends_cache_file)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._cache_lock = Lock()

    def list_categories(self) -> list[dict[str, str]]:
        with obs_scope("SVC.XHS_TRENDS.CATEGORIES", "FILE_IO"):
            categories = [item.to_dict() for item in self._load_categories()]
            emit_obs_event(
                level="INFO",
                message="svc.xhs_trends.categories",
                payload={"total": len(categories)},
            )
            return categories

    def get_cache_updated_at(self) -> str:
        cache = self._read_cache()
        return str(cache.get("updated_at") or "")

    def refresh(self, category_key: Optional[str] = None) -> dict[str, Any]:
        with obs_scope(
            "SVC.XHS_TRENDS.REFRESH",
            "WORKFLOW_NODE",
            entities={"category_key": category_key},
        ):
            categories = self._load_categories()
            category_map = {item.key: item for item in categories}
            targets: list[XhsCategory]
            if category_key:
                key = category_key.strip()
                if key not in category_map:
                    raise ValueError(f"未找到分类: {category_key}")
                targets = [category_map[key]]
            else:
                targets = categories

            now_iso = self._now_iso()
            cache = self._read_cache()
            cache_categories = cache.setdefault("categories", {})
            refreshed: list[str] = []
            errors: dict[str, str] = {}
            provider = self._get_provider()

            # http_api provider 保持历史降级行为：无 base_url 时直接沿用缓存。
            if provider == "http_api" and not settings.xhs_trends_api_base_url.strip().rstrip("/"):
                for category in targets:
                    previous = cache_categories.get(category.key, {})
                    cached_items = previous.get("items", [])
                    cache_categories[category.key] = {
                        "updated_at": previous.get("updated_at") or cache.get("updated_at") or now_iso,
                        "fetch_error": None,
                        "items": cached_items,
                    }
                self._write_cache(cache)
                emit_obs_event(
                    level="WARNING",
                    message="svc.xhs_trends.refresh.skip_missing_base_url",
                    error_code="E_XHS_BASE_URL_MISSING",
                    payload={
                        "requested_category": category_key or "all",
                        "targets": [item.key for item in targets],
                        "cache_fallback": True,
                    },
                )
                return {
                    "updated_at": cache.get("updated_at") or now_iso,
                    "refreshed_categories": [],
                    "errors": {},
                }

            precheck_error = self._precheck_provider(provider)
            if precheck_error:
                for category in targets:
                    previous = cache_categories.get(category.key, {})
                    errors[category.key] = precheck_error
                    cache_categories[category.key] = {
                        "updated_at": previous.get("updated_at") or now_iso,
                        "fetch_error": precheck_error,
                        "items": previous.get("items", []),
                    }
                cache["updated_at"] = now_iso
                self._write_cache(cache)
                emit_obs_event(
                    level="WARNING",
                    message="svc.xhs_trends.refresh.precheck_failed",
                    error_code="E_XHS_REFRESH_PRECHECK_FAILED",
                    payload={
                        "provider": provider,
                        "requested_category": category_key or "all",
                        "error": precheck_error,
                    },
                )
                return {
                    "updated_at": now_iso,
                    "refreshed_categories": [],
                    "errors": errors,
                }

            for category in targets:
                try:
                    raw_items = self._fetch_category_items(category.key)
                    normalized_items = self._normalize_items(raw_items)
                    if provider == "algovate_mcp" and self.comment_detail_limit > 0:
                        normalized_items = self._enrich_top_comments_from_mcp(
                            normalized_items,
                            limit=self.comment_detail_limit,
                        )
                    normalized_items = self._strip_internal_fields(normalized_items)
                    cache_categories[category.key] = {
                        "updated_at": now_iso,
                        "fetch_error": None,
                        "items": normalized_items,
                    }
                    refreshed.append(category.key)
                    emit_obs_event(
                        level="INFO",
                        message="svc.xhs_trends.refresh.category_done",
                        entities={"category_key": category.key},
                        payload={"items": len(normalized_items)},
                    )
                except Exception as error:
                    error_msg = str(error)
                    errors[category.key] = error_msg
                    previous = cache_categories.get(category.key, {})
                    cache_categories[category.key] = {
                        "updated_at": previous.get("updated_at") or now_iso,
                        "fetch_error": error_msg,
                        "items": previous.get("items", []),
                    }
                    emit_obs_event(
                        level="WARNING",
                        message="svc.xhs_trends.refresh.category_failed",
                        entities={"category_key": category.key},
                        error_code="E_XHS_REFRESH_FAILED",
                        payload={"error": error_msg},
                    )

            cache["updated_at"] = now_iso
            self._write_cache(cache)
            emit_obs_event(
                level="INFO",
                message="svc.xhs_trends.refresh.done",
                payload={
                    "requested_category": category_key or "all",
                    "refreshed_count": len(refreshed),
                    "error_count": len(errors),
                },
            )
            return {
                "updated_at": now_iso,
                "refreshed_categories": refreshed,
                "errors": errors,
            }

    def get_trends(
        self,
        category_key: str,
        *,
        sort: str = "hot",
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        with obs_scope(
            "SVC.XHS_TRENDS.GET",
            "DB_READ",
            entities={"category_key": category_key},
        ):
            category = self._require_category(category_key)
            normalized_sort = (sort or "hot").strip().lower()
            if normalized_sort not in {"hot", "latest"}:
                raise ValueError("sort 仅支持 hot 或 latest")

            query_limit = limit if isinstance(limit, int) else self.default_limit
            query_limit = max(1, min(query_limit, 50))

            cache = self._read_cache()
            cat_data = cache.get("categories", {}).get(category.key, {})
            raw_items = cat_data.get("items", [])
            items = self._post_filter_items(raw_items)

            if normalized_sort == "hot":
                items.sort(
                    key=lambda item: (
                        float(item.get("hot_score") or 0.0),
                        self._publish_sort_value(item.get("publish_time", "")),
                    ),
                    reverse=True,
                )
            else:
                items.sort(
                    key=lambda item: (
                        self._publish_sort_value(item.get("publish_time", "")),
                        float(item.get("hot_score") or 0.0),
                    ),
                    reverse=True,
                )

            result_items = items[:query_limit]
            emit_obs_event(
                level="INFO",
                message="svc.xhs_trends.get",
                entities={"category_key": category.key},
                payload={
                    "sort": normalized_sort,
                    "limit": query_limit,
                    "items": len(result_items),
                },
            )
            return {
                "category_key": category.key,
                "category_name": category.name,
                "category_name_en": category.name_en,
                "sort": normalized_sort,
                "lookback_days": self.lookback_days,
                "min_interactions": self.min_interactions,
                "updated_at": cat_data.get("updated_at") or cache.get("updated_at") or "",
                "fetch_error": cat_data.get("fetch_error"),
                "is_stale": bool(cat_data.get("fetch_error") and result_items),
                "items": result_items,
            }

    def build_analysis(self, category_key: str) -> dict[str, Any]:
        with obs_scope(
            "SVC.XHS_TRENDS.ANALYZE",
            "WORKFLOW_NODE",
            entities={"category_key": category_key},
        ):
            trends = self.get_trends(category_key, sort="hot", limit=max(self.default_limit, 10))
            items = trends.get("items", [])
            if not items:
                raise ValueError("暂无可分析数据，请先手动刷新")

            llm_payload = self._try_llm_analysis(
                category_name=trends["category_name"],
                items=items,
            )
            if llm_payload:
                analysis = llm_payload
            else:
                analysis = self._heuristic_analysis(items)

            emit_obs_event(
                level="INFO",
                message="svc.xhs_trends.analyze.done",
                entities={"category_key": category_key},
                payload={"items": len(items)},
            )
            return {
                "category_key": trends["category_key"],
                "category_name": trends["category_name"],
                "generated_at": self._now_iso(),
                **analysis,
            }

    def _load_categories(self) -> list[XhsCategory]:
        categories: list[dict[str, Any]] = []
        try:
            if self.categories_file.exists():
                data = json.loads(self.categories_file.read_text(encoding="utf-8"))
                raw = data.get("categories", []) if isinstance(data, dict) else []
                if isinstance(raw, list):
                    for item in raw:
                        if not isinstance(item, dict):
                            continue
                        key = (item.get("key") or "").strip()
                        name = (item.get("name") or "").strip()
                        name_en = (item.get("name_en") or name or key).strip()
                        if key and name:
                            categories.append(
                                {
                                    "key": key,
                                    "name": name,
                                    "name_en": name_en,
                                    "keywords": self._normalize_keywords(
                                        item.get("keywords"),
                                        fallback=name,
                                    ),
                                }
                            )
        except Exception as error:
            logger.warning("读取小红书分类配置失败，回退默认分类: %s", error)

        if not categories:
            categories = list(_DEFAULT_CATEGORIES)

        unique: dict[str, XhsCategory] = {}
        for item in categories:
            key = item["key"].strip()
            if not key:
                continue
            unique[key] = XhsCategory(
                key=key,
                name=item["name"].strip(),
                name_en=(item.get("name_en") or item["name"] or key).strip(),
                keywords=self._normalize_keywords(
                    item.get("keywords"),
                    fallback=item.get("name") or key,
                ),
            )
        return list(unique.values())

    @staticmethod
    def _normalize_keywords(raw_keywords: Any, *, fallback: str) -> list[str]:
        if not isinstance(raw_keywords, list):
            return [str(fallback).strip()]
        deduped: dict[str, bool] = {}
        for raw in raw_keywords:
            text = str(raw or "").strip()
            if text:
                deduped[text] = True
            if len(deduped) >= 8:
                break
        if deduped:
            return list(deduped.keys())
        return [str(fallback).strip()]

    def _require_category(self, category_key: str) -> XhsCategory:
        key = (category_key or "").strip()
        for category in self._load_categories():
            if category.key == key:
                return category
        raise ValueError(f"未找到分类: {category_key}")

    def _read_cache(self) -> dict[str, Any]:
        with self._cache_lock:
            if not self.cache_file.exists():
                return {"updated_at": "", "categories": {}}
            try:
                payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    payload.setdefault("updated_at", "")
                    payload.setdefault("categories", {})
                    return payload
            except Exception as error:
                logger.warning("读取 xhs 趋势缓存失败，忽略旧缓存: %s", error)
            return {"updated_at": "", "categories": {}}

    def _write_cache(self, payload: dict[str, Any]) -> None:
        with self._cache_lock:
            self.cache_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _get_provider(self) -> str:
        value = str(settings.xhs_trends_provider or "").strip().lower()
        if value in {"", "algovate_mcp", "http_api"}:
            return value or "algovate_mcp"
        raise ValueError(f"不支持的 XHS_TRENDS_PROVIDER: {value}")

    def _precheck_provider(self, provider: str) -> Optional[str]:
        if provider == "http_api":
            return None
        if provider != "algovate_mcp":
            return f"不支持的 XHS_TRENDS_PROVIDER: {provider}"
        if not self.mcp_url:
            return "未配置 XHS_MCP_URL"
        try:
            payload = self._mcp_call_tool("xhs_auth_status", self._build_browser_args())
        except ValueError as error:
            message = str(error)
            if self._is_transient_status_check_error(message):
                emit_obs_event(
                    level="WARNING",
                    message="svc.xhs_trends.precheck.status_check_skipped",
                    error_code="E_XHS_MCP_STATUS_CHECK_TRANSIENT",
                    payload={"error": message},
                )
                return None
            return message
        if not isinstance(payload, dict):
            return "xhs-mcp 状态检查返回格式无效"
        status = str(payload.get("status") or "").strip().lower()
        logged_in = bool(payload.get("loggedIn")) or status == "logged_in"
        if not logged_in:
            return "xhs-mcp 未登录，请先执行 npx xhs-mcp login 完成扫码登录"
        return None

    @staticmethod
    def _is_transient_status_check_error(message: str) -> bool:
        text = str(message or "").strip().lower()
        if not text:
            return False
        return (
            "statuscheckerror" in text
            or "status check error" in text
            or "status check failed" in text
        )

    def _fetch_category_items(self, category_key: str) -> list[dict[str, Any]]:
        provider = self._get_provider()
        if provider == "http_api":
            return self._fetch_category_items_http_api(category_key)
        if provider == "algovate_mcp":
            return self._fetch_category_items_algovate_mcp(category_key)
        raise ValueError(f"不支持的 XHS_TRENDS_PROVIDER: {provider}")

    def _fetch_category_items_http_api(self, category_key: str) -> list[dict[str, Any]]:
        base_url = settings.xhs_trends_api_base_url.strip().rstrip("/")
        if not base_url:
            raise ValueError("未配置 XHS_TRENDS_API_BASE_URL")

        url = f"{base_url}/trends"
        headers = {"Accept": "application/json"}
        api_key = settings.xhs_trends_api_key.strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-API-Key"] = api_key

        params = {
            "category": category_key,
            "since_days": self.lookback_days,
            "limit": max(self.default_limit, 30),
        }
        emit_obs_event(
            level="INFO",
            message="svc.xhs_trends.fetch.start",
            entities={"category_key": category_key},
            payload={"url": url, "provider": "http_api"},
        )
        response = requests.get(url, headers=headers, params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, dict):
            items = payload.get("items")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
            data = payload.get("data")
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        elif isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

        raise ValueError("第三方数据格式无效")

    def _fetch_category_items_algovate_mcp(self, category_key: str) -> list[dict[str, Any]]:
        category = self._require_category(category_key)
        aggregated: dict[str, dict[str, Any]] = {}
        keyword_errors: list[str] = []
        selected_keywords = category.keywords[: self.max_keywords_per_category]

        for keyword in selected_keywords:
            try:
                payload = self._mcp_call_tool(
                    "xhs_search_note",
                    {"keyword": keyword, **self._build_browser_args()},
                )
            except Exception as error:
                keyword_errors.append(f"{keyword}: {error}")
                emit_obs_event(
                    level="WARNING",
                    message="svc.xhs_trends.mcp.search_keyword_failed",
                    entities={"category_key": category_key},
                    error_code="E_XHS_MCP_SEARCH_KEYWORD_FAILED",
                    payload={"keyword": keyword, "error": str(error)},
                )
                continue
            feeds = payload.get("feeds")
            if not isinstance(feeds, list):
                continue
            for feed in feeds:
                normalized = self._normalize_mcp_feed(feed)
                if not normalized:
                    continue
                dedupe_key = normalized.get("id") or normalized.get("title")
                if dedupe_key:
                    aggregated[str(dedupe_key)] = normalized

        if not aggregated and keyword_errors:
            raise ValueError(keyword_errors[0])
        return list(aggregated.values())

    def _build_browser_args(self) -> dict[str, str]:
        if self.mcp_browser_path:
            return {"browser_path": self.mcp_browser_path}
        return {}

    def _mcp_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with obs_scope(
            "SVC.XHS_TRENDS.MCP_CALL",
            "EXTERNAL_HTTP_CALL",
            entities={"tool_name": tool_name},
        ):
            if not self.mcp_url:
                raise ValueError("未配置 XHS_MCP_URL")
            init_payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "write-agent", "version": "1.0"},
                },
            }
            base_headers = {
                "Accept": "application/json, text/event-stream",
            }
            try:
                emit_obs_event(
                    level="INFO",
                    message="svc.xhs_trends.mcp.start",
                    entities={"tool_name": tool_name},
                    payload={"url": self.mcp_url},
                )
                init_resp = requests.post(
                    self.mcp_url,
                    json=init_payload,
                    headers=base_headers,
                    timeout=self.mcp_timeout_seconds,
                )
                init_resp.raise_for_status()
                session_id = (
                    init_resp.headers.get("Mcp-Session-Id")
                    or init_resp.headers.get("mcp-session-id")
                    or ""
                ).strip()
                if not session_id:
                    raise ValueError("xhs-mcp 初始化失败：未返回会话 ID")

                requests.post(
                    self.mcp_url,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers={**base_headers, "Mcp-Session-Id": session_id},
                    timeout=self.mcp_timeout_seconds,
                )
                tool_resp = requests.post(
                    self.mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": str(uuid.uuid4()),
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments},
                    },
                    headers={**base_headers, "Mcp-Session-Id": session_id},
                    timeout=self.mcp_timeout_seconds,
                )
                tool_resp.raise_for_status()
                payload = self._decode_mcp_http_payload(tool_resp)
                parsed = self._parse_mcp_tool_result(payload)
                emit_obs_event(
                    level="INFO",
                    message="svc.xhs_trends.mcp.done",
                    entities={"tool_name": tool_name},
                    payload={"ok": True},
                )
                return parsed
            except requests.RequestException as error:
                emit_obs_event(
                    level="WARNING",
                    message="svc.xhs_trends.mcp.failed",
                    entities={"tool_name": tool_name},
                    error_code="E_XHS_MCP_UNAVAILABLE",
                    payload={"error": str(error)},
                )
                raise ValueError("xhs-mcp 服务不可用，请先启动 npx xhs-mcp mcp --mode http --port 3000")
            except ValueError as error:
                emit_obs_event(
                    level="WARNING",
                    message="svc.xhs_trends.mcp.failed",
                    entities={"tool_name": tool_name},
                    error_code="E_XHS_MCP_CALL_FAILED",
                    payload={"error": str(error)},
                )
                raise

    def _decode_mcp_http_payload(self, response: requests.Response) -> dict[str, Any]:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        raw = response.content or b""
        if raw:
            try:
                text = raw.decode("utf-8").strip()
            except Exception:
                text = (response.text or "").strip()
        else:
            text = (response.text or "").strip()
        if not text:
            raise ValueError("xhs-mcp 返回空响应")
        if "text/event-stream" in content_type or text.startswith("event:"):
            data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
            if not data_lines:
                raise ValueError("xhs-mcp SSE 响应缺少 data 字段")
            sse_candidates = ["\n".join(data_lines), *reversed(data_lines)]
            payload: Optional[dict[str, Any]] = None
            parse_error: Optional[Exception] = None
            for candidate in sse_candidates:
                try:
                    parsed = json.loads(candidate)
                except Exception as error:
                    parse_error = error
                    continue
                if isinstance(parsed, dict):
                    payload = parsed
                    break
            if payload is None:
                fallback = self._extract_text_payload_from_sse(text)
                if fallback is None:
                    raise ValueError(f"xhs-mcp 返回非 JSON 内容: {parse_error}")
                return fallback
            return payload
        try:
            payload = json.loads(text)
        except Exception as error:
            raise ValueError(f"xhs-mcp 返回非 JSON 内容: {error}")
        if not isinstance(payload, dict):
            raise ValueError("xhs-mcp JSON 响应格式无效")
        return payload

    def _extract_text_payload_from_sse(self, raw_text: str) -> Optional[dict[str, Any]]:
        source = raw_text.replace("\r", "")
        data_index = source.find("data:")
        if data_index >= 0:
            source = source[data_index + 5 :].strip()
        end_marker = '"}]},"jsonrpc"'
        start_marker = '"text":"'
        start = source.find(start_marker)
        end = source.rfind(end_marker)
        if start == -1 or end == -1 or end <= start + len(start_marker):
            return None
        inner = source[start + len(start_marker) : end]
        if not inner:
            return None
        if "\\n" in inner or '\\"' in inner or "\\u" in inner:
            try:
                # 优先走 JSON 字符串反转义，避免 unicode_escape 导致中文乱码。
                inner = json.loads(f'"{inner}"')
            except Exception:
                try:
                    inner = bytes(inner, "utf-8").decode("unicode_escape")
                except Exception:
                    pass
        return {
            "result": {
                "content": [{"type": "text", "text": inner}],
            }
        }

    def _parse_mcp_tool_result(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("xhs-mcp 返回格式无效")
        if isinstance(payload.get("error"), dict):
            message = payload["error"].get("message") or "xhs-mcp 调用失败"
            raise ValueError(str(message))
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError("xhs-mcp 返回缺少 result")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        if parsed.get("success") is False:
                            msg = parsed.get("error") or parsed.get("message") or "xhs-mcp 调用失败"
                            raise ValueError(str(msg))
                        return parsed
                except json.JSONDecodeError:
                    continue
        raise ValueError("xhs-mcp 返回缺少可解析内容")

    def _normalize_mcp_feed(self, raw_feed: Any) -> Optional[dict[str, Any]]:
        if not isinstance(raw_feed, dict):
            return None
        note_card = raw_feed.get("noteCard") if isinstance(raw_feed.get("noteCard"), dict) else {}
        if not isinstance(note_card, dict):
            note_card = {}
        interact_info = note_card.get("interactInfo")
        if not isinstance(interact_info, dict):
            interact_info = raw_feed.get("interact_info")
        if not isinstance(interact_info, dict):
            interact_info = {}

        note_id = self._pick_text(raw_feed, ["id", "note_id", "noteId"])
        if not note_id:
            note_id = self._pick_text(note_card, ["noteId", "id"])
        title = self._pick_text(raw_feed, ["title", "display_title", "note_title"])
        if not title:
            title = self._pick_text(note_card, ["displayTitle", "title", "noteTitle"])
        if not title:
            title = self._pick_text(raw_feed, ["desc", "description"])
        if not title:
            return None

        xsec_token = self._pick_text(raw_feed, ["xsecToken", "xsec_token"])
        if not xsec_token:
            xsec_token = self._pick_text(note_card, ["xsecToken", "xsec_token"])

        publish_time = (
            note_card.get("time")
            or raw_feed.get("time")
            or raw_feed.get("publish_time")
            or raw_feed.get("publishTime")
            or raw_feed.get("last_update_time")
        )
        if not publish_time:
            publish_time = self._extract_publish_time_from_corner_tags(note_card.get("cornerTagInfo"))

        return {
            "id": note_id,
            "title": title,
            "content_type": (
                note_card.get("type")
                or note_card.get("noteType")
                or raw_feed.get("content_type")
                or raw_feed.get("type")
            ),
            "like_count": (
                interact_info.get("likedCount")
                or interact_info.get("liked_count")
                or raw_feed.get("like_count")
            ),
            "favorite_count": (
                interact_info.get("collectedCount")
                or interact_info.get("collected_count")
                or raw_feed.get("favorite_count")
            ),
            "comment_count": (
                interact_info.get("commentCount")
                or interact_info.get("comment_count")
                or raw_feed.get("comment_count")
            ),
            "publish_time": publish_time,
            "source_url": self._build_source_url(note_id, xsec_token),
            "xsec_token": xsec_token,
            "top_comments": [],
        }

    def _extract_publish_time_from_corner_tags(self, raw_corner_tags: Any) -> Optional[str]:
        if not isinstance(raw_corner_tags, list):
            return None
        tag_text = ""
        for item in raw_corner_tags:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").strip() == "publish_time":
                tag_text = str(item.get("text") or "").strip()
                break
        if not tag_text:
            return None
        try:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", tag_text):
                parsed = datetime.strptime(tag_text, "%Y-%m-%d").replace(tzinfo=self.timezone)
                return parsed.isoformat()
            if re.match(r"^\d{2}-\d{2}$", tag_text):
                month, day = tag_text.split("-")
                now = datetime.now(self.timezone)
                candidate = datetime(
                    year=now.year,
                    month=int(month),
                    day=int(day),
                    tzinfo=self.timezone,
                )
                if candidate > now + timedelta(days=2):
                    candidate = candidate.replace(year=now.year - 1)
                return candidate.isoformat()
        except Exception:
            return None
        return None

    def _build_source_url(self, note_id: str, xsec_token: str) -> str:
        if not note_id:
            return ""
        if xsec_token:
            return (
                f"https://www.xiaohongshu.com/explore/{note_id}"
                f"?xsec_token={xsec_token}&xsec_source=pc_feed"
            )
        return f"https://www.xiaohongshu.com/explore/{note_id}"

    def _enrich_top_comments_from_mcp(
        self,
        items: list[dict[str, Any]],
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        if not items:
            return items
        top_limit = max(0, int(limit))
        if top_limit <= 0:
            return items
        enriched = [dict(item) for item in items]
        top_candidates = sorted(
            enriched,
            key=lambda item: float(item.get("hot_score") or 0.0),
            reverse=True,
        )[:top_limit]
        for item in top_candidates:
            note_id = str(item.get("id") or "").strip()
            xsec_token = str(item.get("_xsec_token") or "").strip()
            if not note_id or not xsec_token:
                continue
            try:
                detail = self._mcp_call_tool(
                    "xhs_get_note_detail",
                    {"feed_id": note_id, "xsec_token": xsec_token, **self._build_browser_args()},
                )
                comments = self._extract_top_comments_from_detail(detail)
                if comments:
                    item["top_comments"] = comments
            except Exception as error:
                emit_obs_event(
                    level="WARNING",
                    message="svc.xhs_trends.mcp.detail_failed",
                    entities={"note_id": note_id},
                    error_code="E_XHS_MCP_DETAIL_FAILED",
                    payload={"error": str(error)},
                )
        return enriched

    def _extract_top_comments_from_detail(self, detail_payload: dict[str, Any]) -> list[str]:
        candidates: list[Any] = []
        if isinstance(detail_payload, dict):
            candidates.extend(
                [
                    detail_payload.get("comments"),
                    detail_payload.get("comment_list"),
                    detail_payload.get("commentList"),
                ]
            )
            data = detail_payload.get("data")
            if isinstance(data, dict):
                candidates.extend(
                    [
                        data.get("comments"),
                        data.get("comment_list"),
                        data.get("commentList"),
                    ]
                )
                note = data.get("note")
                if isinstance(note, dict):
                    candidates.extend(
                        [
                            note.get("comments"),
                            note.get("comment_list"),
                            note.get("commentList"),
                        ]
                    )

        comments: list[str] = []
        for block in candidates:
            if len(comments) >= 5:
                break
            comments.extend(self._extract_texts_from_comment_block(block))
        deduped: dict[str, bool] = {}
        for text in comments:
            clipped = self._clip_text(text, 40)
            if clipped:
                deduped[clipped] = True
            if len(deduped) >= 5:
                break
        return list(deduped.keys())

    def _extract_texts_from_comment_block(self, block: Any) -> list[str]:
        if isinstance(block, dict):
            if isinstance(block.get("list"), list):
                return self._extract_texts_from_comment_block(block.get("list"))
            if isinstance(block.get("comments"), list):
                return self._extract_texts_from_comment_block(block.get("comments"))
            return []
        if not isinstance(block, list):
            return []
        comments: list[str] = []
        for item in block:
            if not isinstance(item, dict):
                continue
            text = self._pick_text(item, ["content", "text", "comment", "comment_content"])
            if text:
                comments.append(text)
            if len(comments) >= 5:
                break
        return comments

    @staticmethod
    def _strip_internal_fields(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for item in items:
            row = {key: value for key, value in item.items() if not str(key).startswith("_")}
            cleaned.append(row)
        return cleaned

    def _normalize_items(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cutoff = datetime.now(self.timezone) - timedelta(days=self.lookback_days)
        normalized: list[dict[str, Any]] = []
        for raw in raw_items:
            title = self._pick_text(raw, ["title", "note_title", "name", "desc", "description"])
            if not title:
                continue
            publish_time = self._parse_publish_time(
                raw.get("publish_time")
                or raw.get("published_at")
                or raw.get("create_time")
                or raw.get("timestamp")
                or raw.get("time")
                or raw.get("last_update_time")
            )
            if not publish_time or publish_time < cutoff:
                continue

            interact_info = raw.get("interact_info")
            if not isinstance(interact_info, dict):
                interact_info = {}

            like_count = self._to_int(
                raw.get("like_count")
                or raw.get("likes")
                or raw.get("liked_count")
                or interact_info.get("likedCount")
                or interact_info.get("liked_count")
            )
            favorite_count = self._to_int(
                raw.get("favorite_count")
                or raw.get("favorites")
                or raw.get("collect_count")
                or raw.get("saved_count")
                or interact_info.get("collectedCount")
                or interact_info.get("collected_count")
            )
            comment_count = self._to_int(
                raw.get("comment_count")
                or raw.get("comments")
                or interact_info.get("commentCount")
                or interact_info.get("comment_count")
            )
            interactions = like_count + favorite_count + comment_count
            if interactions < self.min_interactions:
                continue

            source_url = self._pick_text(raw, ["source_url", "share_url", "url", "note_url"])
            if not source_url:
                note_id = self._pick_text(raw, ["note_id", "id", "item_id"])
                if note_id:
                    source_url = f"https://www.xiaohongshu.com/explore/{note_id}"

            hot_score = round(like_count * 1.0 + favorite_count * 0.8 + comment_count * 0.5, 2)
            top_comments = self._normalize_top_comments(
                raw.get("top_comments") or raw.get("comments_top") or raw.get("comments")
            )
            note_id = self._pick_text(raw, ["note_id", "id", "item_id"])
            xsec_token = self._pick_text(raw, ["xsec_token", "xsecToken"])
            normalized.append(
                {
                    "id": note_id,
                    "title": title,
                    "content_type": self._normalize_content_type(
                        raw.get("content_type")
                        or raw.get("type")
                        or raw.get("note_type")
                        or raw.get("media_type")
                    ),
                    "like_count": like_count,
                    "favorite_count": favorite_count,
                    "comment_count": comment_count,
                    "publish_time": publish_time.isoformat(),
                    "source_url": source_url,
                    "hot_score": hot_score,
                    "interactions": interactions,
                    "top_comments": top_comments,
                    "_xsec_token": xsec_token,
                }
            )

        normalized.sort(
            key=lambda item: (
                float(item.get("hot_score") or 0.0),
                self._publish_sort_value(item.get("publish_time", "")),
            ),
            reverse=True,
        )
        return normalized

    def _post_filter_items(self, raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cutoff = datetime.now(self.timezone) - timedelta(days=self.lookback_days)
        filtered: list[dict[str, Any]] = []
        for item in raw_items:
            publish_time = self._parse_publish_time(item.get("publish_time"))
            if not publish_time or publish_time < cutoff:
                continue
            interactions = self._to_int(item.get("interactions"))
            if interactions <= 0:
                interactions = (
                    self._to_int(item.get("like_count"))
                    + self._to_int(item.get("favorite_count"))
                    + self._to_int(item.get("comment_count"))
                )
            if interactions < self.min_interactions:
                continue
            clean = dict(item)
            clean["interactions"] = interactions
            clean["content_type"] = self._normalize_content_type(item.get("content_type"))
            clean["hot_score"] = float(item.get("hot_score") or 0.0)
            clean["top_comments"] = self._normalize_top_comments(item.get("top_comments"))
            filtered.append(clean)
        return filtered

    def _heuristic_analysis(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        top_items = items[:3] if len(items) >= 3 else (items + items[:1] + items[:1])[:3]
        video_ratio = 0
        if items:
            video_count = sum(1 for item in items if item.get("content_type") == "video")
            video_ratio = int(round(video_count * 100 / len(items)))

        reason_points = [
            self._clip_text("高热内容标题常用数字+结果钩子", 40),
            self._clip_text(
                "视频占比{}%，说明短时高密表达更吃香".format(video_ratio),
                40,
            ),
            self._clip_text("评论集中问步骤与成本，实操向更易出圈", 40),
        ]

        fallback_comments = [
            "求一个能直接照做的步骤版", 
            "这个方案成本大概多少？", 
            "有坑点的话请提前提醒", 
        ]
        comment_pool = self._collect_comment_pool(items)
        comment_topics = [
            {
                "topic": "实操步骤",
                "ratio": "45%",
                "sample_comment": self._clip_text(comment_pool[0] if comment_pool else fallback_comments[0], 40),
            },
            {
                "topic": "成本门槛",
                "ratio": "30%",
                "sample_comment": self._clip_text(comment_pool[1] if len(comment_pool) > 1 else fallback_comments[1], 40),
            },
            {
                "topic": "避坑建议",
                "ratio": "25%",
                "sample_comment": self._clip_text(comment_pool[2] if len(comment_pool) > 2 else fallback_comments[2], 40),
            },
        ]

        inspiration_cards: list[dict[str, str]] = []
        for item in top_items:
            topic = self._clip_text(self._title_to_topic(str(item.get("title") or "")), 18)
            content_type = self._normalize_content_type(item.get("content_type"))
            if content_type == "video":
                title_hook = self._clip_text(f"3分钟讲清：{topic}的关键步骤", 40)
            else:
                title_hook = self._clip_text(f"一篇说透：{topic}的可复制打法", 40)

            interactions = self._to_int(item.get("interactions"))
            rationale = self._clip_text(
                f"该题材互动{interactions}，读者对可执行方法需求明显",
                40,
            )
            inspiration_cards.append(
                {
                    "topic": topic,
                    "content_type": content_type,
                    "title_hook": title_hook,
                    "rationale": rationale,
                }
            )

        return {
            "reason_points": reason_points[:3],
            "comment_topics": comment_topics[:3],
            "inspiration_cards": inspiration_cards[:3],
        }

    def _try_llm_analysis(self, *, category_name: str, items: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if os.getenv("PYTEST_CURRENT_TEST"):
            return None
        if not settings.openai_api_key.strip():
            return None

        try:
            from write_agent.services.llm_service import get_llm_service

            llm = get_llm_service()
            sample = [
                {
                    "title": item.get("title", ""),
                    "content_type": item.get("content_type", "image_text"),
                    "hot_score": item.get("hot_score", 0),
                    "like_count": item.get("like_count", 0),
                    "favorite_count": item.get("favorite_count", 0),
                    "comment_count": item.get("comment_count", 0),
                    "top_comments": (item.get("top_comments") or [])[:2],
                }
                for item in items[:10]
            ]
            system_prompt = (
                "你是内容洞察助手。请仅返回 JSON，字段必须包含 "
                "reason_points/comment_topics/inspiration_cards。"
            )
            user_prompt = (
                f"分类：{category_name}\n"
                "请输出：\n"
                "1) reason_points: 3条，每条<=40字；\n"
                "2) comment_topics: 3条，每条包含 topic/ratio/sample_comment；\n"
                "3) inspiration_cards: 3条，每条包含 topic/content_type/title_hook/rationale。\n"
                f"输入数据：{json.dumps(sample, ensure_ascii=False)}"
            )
            raw = llm.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=system_prompt,
                temperature=0.2,
            )
            parsed = self._extract_json_object(raw)
            if not isinstance(parsed, dict):
                return None
            return self._normalize_analysis_payload(parsed, items)
        except Exception as error:
            logger.warning("LLM 生成小红书分析失败，回退规则分析: %s", error)
            emit_obs_event(
                level="WARNING",
                message="svc.xhs_trends.analyze.llm_fallback",
                error_code="E_XHS_ANALYZE_LLM_FAILED",
                payload={"error": str(error)},
            )
            return None

    def _normalize_analysis_payload(self, payload: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
        reason_points_raw = payload.get("reason_points")
        reason_points = self._normalize_string_list(reason_points_raw, fallback=[])
        if len(reason_points) < 3:
            reason_points.extend(self._heuristic_analysis(items)["reason_points"])
        reason_points = [self._clip_text(text, 40) for text in reason_points[:3]]

        comment_topics: list[dict[str, str]] = []
        raw_topics = payload.get("comment_topics")
        if isinstance(raw_topics, list):
            for entry in raw_topics:
                if not isinstance(entry, dict):
                    continue
                topic = self._clip_text(str(entry.get("topic") or ""), 20)
                ratio = self._clip_text(str(entry.get("ratio") or ""), 10)
                sample = self._clip_text(str(entry.get("sample_comment") or ""), 40)
                if topic and ratio and sample:
                    comment_topics.append(
                        {"topic": topic, "ratio": ratio, "sample_comment": sample}
                    )
        while len(comment_topics) < 3:
            comment_topics.append(self._heuristic_analysis(items)["comment_topics"][len(comment_topics)])
        comment_topics = comment_topics[:3]

        cards: list[dict[str, str]] = []
        raw_cards = payload.get("inspiration_cards")
        if isinstance(raw_cards, list):
            for entry in raw_cards:
                if not isinstance(entry, dict):
                    continue
                topic = self._clip_text(str(entry.get("topic") or ""), 20)
                content_type = self._normalize_content_type(entry.get("content_type"))
                title_hook = self._clip_text(str(entry.get("title_hook") or ""), 40)
                rationale = self._clip_text(str(entry.get("rationale") or ""), 40)
                if topic and title_hook and rationale:
                    cards.append(
                        {
                            "topic": topic,
                            "content_type": content_type,
                            "title_hook": title_hook,
                            "rationale": rationale,
                        }
                    )
        while len(cards) < 3:
            cards.append(self._heuristic_analysis(items)["inspiration_cards"][len(cards)])
        cards = cards[:3]

        return {
            "reason_points": reason_points,
            "comment_topics": comment_topics,
            "inspiration_cards": cards,
        }

    @staticmethod
    def _extract_json_object(raw_text: str) -> Optional[dict[str, Any]]:
        text = (raw_text or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    @staticmethod
    def _normalize_string_list(value: Any, *, fallback: list[str]) -> list[str]:
        if not isinstance(value, list):
            return list(fallback)
        results: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                results.append(text)
        return results

    @staticmethod
    def _title_to_topic(title: str) -> str:
        text = re.sub(r"\s+", " ", title).strip()
        text = re.sub(r"^[#【\[]+|[】\]]+$", "", text)
        text = re.sub(r"[!！?？。；;，,]+$", "", text)
        return text or "本周热点选题"

    @staticmethod
    def _normalize_content_type(raw: Any) -> str:
        value = str(raw or "").strip().lower()
        if value in {"video", "视频", "short_video", "shortvideo"}:
            return "video"
        return "image_text"

    @staticmethod
    def _normalize_top_comments(raw: Any) -> list[str]:
        if isinstance(raw, str):
            text = raw.strip()
            return [text] if text else []
        if not isinstance(raw, list):
            return []

        comments: list[str] = []
        for item in raw:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = str(item.get("content") or item.get("text") or "").strip()
            else:
                text = ""
            if text:
                comments.append(text)
        return comments[:5]

    def _collect_comment_pool(self, items: list[dict[str, Any]]) -> list[str]:
        pool: list[str] = []
        for item in items:
            for text in self._normalize_top_comments(item.get("top_comments")):
                clean = self._clip_text(text, 40)
                if clean:
                    pool.append(clean)
        return pool[:10]

    @staticmethod
    def _pick_text(payload: dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _clip_text(value: str, max_len: int) -> str:
        text = (value or "").strip()
        if len(text) <= max_len:
            return text
        return text[: max_len - 1].rstrip() + "…"

    @staticmethod
    def _to_int(value: Any) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value or "").strip()
        if not text:
            return 0
        compact = text.replace(",", "").replace("，", "")
        match = re.search(r"(-?\d+(?:\.\d+)?)\s*([万wWkK]?)", compact)
        if match:
            number = float(match.group(1))
            unit = match.group(2)
            if unit in {"万", "w", "W"}:
                number *= 10000
            elif unit in {"k", "K"}:
                number *= 1000
            return int(number)
        cleaned = re.sub(r"[^\d.-]", "", compact)
        if not cleaned:
            return 0
        try:
            return int(float(cleaned))
        except Exception:
            return 0

    def _parse_publish_time(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                return dt.replace(tzinfo=self.timezone)
            return dt.astimezone(self.timezone)
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts = ts / 1000.0
            try:
                return datetime.fromtimestamp(ts, tz=self.timezone)
            except Exception:
                return None

        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            ts = float(text)
            if ts > 1e12:
                ts = ts / 1000.0
            try:
                return datetime.fromtimestamp(ts, tz=self.timezone)
            except Exception:
                return None

        now = datetime.now(self.timezone)
        if text == "刚刚":
            return now
        rel_match = re.match(r"^(\d+)\s*(分钟前|小时前|天前)$", text)
        if rel_match:
            amount = int(rel_match.group(1))
            unit = rel_match.group(2)
            if unit == "分钟前":
                return now - timedelta(minutes=amount)
            if unit == "小时前":
                return now - timedelta(hours=amount)
            if unit == "天前":
                return now - timedelta(days=amount)

        candidates = [text, text.replace("Z", "+00:00")]
        for item in candidates:
            try:
                parsed = datetime.fromisoformat(item)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=self.timezone)
                return parsed.astimezone(self.timezone)
            except Exception:
                continue
        return None

    def _publish_sort_value(self, publish_time: str) -> float:
        parsed = self._parse_publish_time(publish_time)
        if not parsed:
            return 0.0
        return parsed.timestamp()

    def _now_iso(self) -> str:
        return datetime.now(self.timezone).isoformat()


_xhs_trends_service: Optional[XhsTrendsService] = None


def get_xhs_trends_service() -> XhsTrendsService:
    """获取小红书热点服务单例。"""
    global _xhs_trends_service
    if _xhs_trends_service is None:
        _xhs_trends_service = XhsTrendsService()
    return _xhs_trends_service
