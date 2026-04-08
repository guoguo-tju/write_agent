"""
GitHub 趋势服务。
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from sqlalchemy import delete, desc, inspect, text, update
from sqlmodel import SQLModel, Session, create_engine, select

from write_agent.core import get_logger, get_settings
from write_agent.models import (
    GitHubRepoEnrichmentCache,
    GitHubTrendingItem,
    GitHubTrendingSnapshot,
    Material,
)
from write_agent.observability import bind_entities, emit_obs_event, obs_scope
from write_agent.services.material_service import get_material_service

logger = get_logger(__name__)
settings = get_settings()
engine = create_engine(settings.database_url, echo=False)


TRENDING_WEEKLY_URL = "https://github.com/trending?since=weekly"
TRENDING_DAILY_URL = "https://github.com/trending?since=daily"
TRENDING_SOURCE_URL = TRENDING_WEEKLY_URL
STAR_PERIOD_PATTERN = re.compile(
    r"([\d,]+)\s*stars?\s*(?:this\s*week|today)",
    re.IGNORECASE,
)
WEEK_KEY_PATTERN = re.compile(r"^\d{4}-W\d{2}$")
DAILY_KEY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ENRICHMENT_CACHE_TTL = timedelta(days=7)
ENRICHMENT_TIMEOUT_SECONDS = 8.0
ENRICHMENT_EXTERNAL_LINK_MAX = 3
DOC_LINK_KEYWORDS = ("doc", "docs", "guide", "manual", "wiki")
ENRICHMENT_SECTION_HEADER = "## 仓库增强信息（自动抓取）"
TRANSLATION_SINGLE_RETRY_MAX = 3
# 单条补翻在本地网关场景下 4s 容易命中超时，放宽到 8s 降低误降级概率。
TRANSLATION_SINGLE_TIMEOUT_SECONDS = 8.0


class RefreshInProgressError(RuntimeError):
    """刷新任务正在执行。"""


@dataclass
class TrendingItemPayload:
    rank: int
    repo_full_name: str
    repo_name: str
    owner: str
    description: str
    description_zh: Optional[str]
    repo_url: str
    stars_this_week: int
    language: Optional[str]
    total_stars: Optional[int]


@dataclass
class EnrichmentMeta:
    attempted: bool
    cache_hit: bool
    degraded: bool
    degrade_reason: str
    duration_ms: int
    fetched_at: str
    sources: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "cache_hit": self.cache_hit,
            "degraded": self.degraded,
            "degrade_reason": self.degrade_reason,
            "duration_ms": self.duration_ms,
            "fetched_at": self.fetched_at,
            "sources": self.sources,
        }


class GitHubTrendingService:
    """GitHub 周榜抓取、归档、入素材。"""

    def __init__(self) -> None:
        self.timezone = ZoneInfo(settings.github_trending_timezone)
        self.refresh_lock = asyncio.Lock()
        self.material_service = get_material_service()
        SQLModel.metadata.create_all(
            engine,
            tables=[
                GitHubTrendingSnapshot.__table__,
                GitHubTrendingItem.__table__,
                GitHubRepoEnrichmentCache.__table__,
            ],
        )
        self._ensure_schema_compat()

    def current_week_key(self) -> str:
        return self.week_key_for_date(datetime.now(self.timezone).date())

    def current_daily_key(self) -> str:
        return datetime.now(self.timezone).date().isoformat()

    @staticmethod
    def week_key_for_date(value: date) -> str:
        year, week, _ = value.isocalendar()
        return f"{year}-W{week:02d}"

    @staticmethod
    def _normalize_week_key(week_key: str) -> str:
        normalized = (week_key or "").strip()
        if not WEEK_KEY_PATTERN.match(normalized):
            raise ValueError("week_key 格式无效，应为 YYYY-Www")
        return normalized

    @staticmethod
    def _normalize_period_type(period_type: Optional[str]) -> str:
        normalized = (period_type or "weekly").strip().lower()
        if normalized not in {"weekly", "daily"}:
            raise ValueError("period_type 仅支持 daily 或 weekly")
        return normalized

    @staticmethod
    def _normalize_daily_key(period_key: str) -> str:
        normalized = (period_key or "").strip()
        if not DAILY_KEY_PATTERN.match(normalized):
            raise ValueError("period_key 格式无效，应为 YYYY-MM-DD")
        return normalized

    def _normalize_period_key(self, period_type: str, period_key: Optional[str]) -> str:
        mode = self._normalize_period_type(period_type)
        normalized = (period_key or "").strip()
        if mode == "weekly":
            if not normalized:
                normalized = self.current_week_key()
            return self._normalize_week_key(normalized)
        if not normalized:
            normalized = self.current_daily_key()
        return self._normalize_daily_key(normalized)

    @staticmethod
    def _parse_int(value: str) -> Optional[int]:
        cleaned = re.sub(r"[^\d]", "", value or "")
        if not cleaned:
            return None
        return int(cleaned)

    @staticmethod
    def _safe_text(value: Optional[str]) -> str:
        return (value or "").strip()

    @staticmethod
    def _escape_md_cell(value: str) -> str:
        return (value or "").replace("|", "\\|").replace("\n", " ").strip()

    @staticmethod
    def _contains_chinese(value: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", value or ""))

    @staticmethod
    def _is_acceptable_zh(value: str) -> bool:
        text_value = (value or "").strip()
        if not text_value:
            return False
        zh_count = len(re.findall(r"[\u4e00-\u9fff]", text_value))
        if zh_count == 0:
            return False
        latin_count = len(re.findall(r"[A-Za-z]", text_value))
        if latin_count == 0:
            return True

        # 兼容“中文主干 + 大量模型/术语英文名”的翻译结果，
        # 同时拦截“几乎全英文，仅夹杂极少中文字符”的低质量输出。
        total_alpha = zh_count + latin_count
        zh_ratio = zh_count / total_alpha if total_alpha else 0.0
        if zh_ratio < 0.12 and zh_count < 10:
            return False
        return True

    @staticmethod
    def _zh_translation_fallback() -> str:
        return "该项目英文简介暂未完成中文翻译，请稍后重试。"

    def _ensure_schema_compat(self) -> None:
        """兼容历史库：description_zh 列可能不存在。"""
        with engine.begin() as conn:
            db_inspector = inspect(conn)
            if not db_inspector.has_table("github_trending_items"):
                return
            columns = {col["name"] for col in db_inspector.get_columns("github_trending_items")}
            if "description_zh" not in columns:
                conn.execute(
                    text("ALTER TABLE github_trending_items ADD COLUMN description_zh TEXT")
                )
                logger.info("github_trending_items 已补齐 description_zh 列")

            snapshot_columns = {
                col["name"] for col in db_inspector.get_columns("github_trending_snapshots")
            }
            if "period_type" not in snapshot_columns:
                conn.execute(
                    text(
                        "ALTER TABLE github_trending_snapshots ADD COLUMN period_type TEXT DEFAULT 'weekly'"
                    )
                )
                logger.info("github_trending_snapshots 已补齐 period_type 列")
            if "period_key" not in snapshot_columns:
                conn.execute(
                    text("ALTER TABLE github_trending_snapshots ADD COLUMN period_key TEXT")
                )
                logger.info("github_trending_snapshots 已补齐 period_key 列")
            conn.execute(
                text(
                    "UPDATE github_trending_snapshots "
                    "SET period_type='weekly' "
                    "WHERE period_type IS NULL OR period_type=''"
                )
            )
            conn.execute(
                text(
                    "UPDATE github_trending_snapshots "
                    "SET period_key=week_key "
                    "WHERE period_key IS NULL OR period_key=''"
                )
            )

    def _load_period_translation_cache(self, period_type: str, period_key: str) -> dict[str, str]:
        """加载同周期已翻译简介，避免重复调用模型。"""
        mode = self._normalize_period_type(period_type)
        normalized_key = self._normalize_period_key(mode, period_key)
        fallback_value = self._zh_translation_fallback()
        with Session(engine) as session:
            rows = session.exec(
                select(
                    GitHubTrendingItem.repo_full_name,
                    GitHubTrendingItem.description_zh,
                    GitHubTrendingSnapshot.captured_at,
                )
                .join(
                    GitHubTrendingSnapshot,
                    GitHubTrendingSnapshot.id == GitHubTrendingItem.snapshot_id,
                )
                .where(
                    GitHubTrendingSnapshot.period_type == mode,
                    GitHubTrendingSnapshot.period_key == normalized_key,
                    GitHubTrendingSnapshot.fetch_status == "success",
                    GitHubTrendingItem.description_zh.is_not(None),
                    GitHubTrendingItem.description_zh != "",
                )
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            ).all()

        mapping: dict[str, str] = {}
        for repo_full_name, description_zh, _ in rows:
            key = (repo_full_name or "").strip().lower()
            value = (description_zh or "").strip()
            if (
                key
                and value
                and value != fallback_value
                and self._is_acceptable_zh(value)
                and key not in mapping
            ):
                mapping[key] = value
        return mapping

    @staticmethod
    def _extract_json_array(raw: str) -> Optional[list]:
        content = (raw or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content, flags=re.IGNORECASE).strip()
            if content.endswith("```"):
                content = content[:-3].strip()
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, list) else None
        except Exception:
            pass

        start = content.find("[")
        end = content.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(content[start : end + 1])
            return parsed if isinstance(parsed, list) else None
        except Exception:
            return None

    @staticmethod
    def _normalize_translation_index(value: Any) -> Optional[int]:
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, float) and value.is_integer():
            normalized = int(value)
            return normalized if normalized >= 0 else None
        if isinstance(value, str):
            compact = value.strip()
            if compact.isdigit():
                return int(compact)
        return None

    def _translate_descriptions_to_zh_batch(self, texts: list[str]) -> dict[int, str]:
        if not texts:
            return {}
        if os.getenv("PYTEST_CURRENT_TEST"):
            return {}
        if not settings.openai_api_key or not settings.openai_model:
            return {}

        base_url = settings.openai_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        payload_items = [{"index": idx, "text": text} for idx, text in enumerate(texts)]
        system_prompt = (
            "你是技术翻译助手。把输入英文项目简介翻译成简体中文。"
            "保留项目名、术语、数字。"
            "仅输出 JSON 数组：[{\"index\": number, \"translation\": \"...\"}]。"
        )
        user_prompt = (
            "请翻译以下简介，严格返回 JSON 数组：\n"
            + json.dumps(payload_items, ensure_ascii=False)
        )
        request_kwargs = {
            "url": f"{base_url}/chat/completions",
            "headers": {
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            "json": {
                "model": settings.openai_model,
                "temperature": 0.0,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            "timeout": min(12.0, max(2.0, float(settings.openai_timeout_seconds))),
        }

        try:
            parsed = urlparse(base_url)
            if parsed.hostname in {"127.0.0.1", "localhost"}:
                with requests.Session() as session:
                    session.trust_env = False
                    response = session.post(**request_kwargs)
            else:
                response = requests.post(**request_kwargs)
            response.raise_for_status()

            content = (
                response.json().get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            rows = self._extract_json_array(str(content))
            if not rows:
                return {}

            translated: dict[int, str] = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                idx = self._normalize_translation_index(row.get("index"))
                text_val = self._safe_text(str(row.get("translation", "")))
                if idx is not None and text_val and self._is_acceptable_zh(text_val):
                    translated[idx] = text_val
            return translated
        except Exception as error:
            logger.warning("GitHub 简介批量翻译失败，回退原文: %s", error)
            return {}

    def _translate_description_to_zh_single(self, text_value: str) -> Optional[str]:
        description = self._safe_text(text_value)
        if not description:
            return None
        if self._is_acceptable_zh(description):
            return description
        if os.getenv("PYTEST_CURRENT_TEST"):
            return None
        if not settings.openai_api_key or not settings.openai_model:
            return None

        base_url = settings.openai_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        request_kwargs = {
            "url": f"{base_url}/chat/completions",
            "headers": {
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            "json": {
                "model": settings.openai_model,
                "temperature": 0.0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是技术翻译助手。保留项目名、术语、数字。"
                            "仅输出简体中文翻译结果，不要解释。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "请把下面 GitHub 项目简介翻译成简体中文：\n"
                            f"{description}"
                        ),
                    },
                ],
            },
            "timeout": min(
                TRANSLATION_SINGLE_TIMEOUT_SECONDS,
                max(1.5, float(settings.openai_timeout_seconds)),
            ),
        }

        try:
            parsed = urlparse(base_url)
            if parsed.hostname in {"127.0.0.1", "localhost"}:
                with requests.Session() as session:
                    session.trust_env = False
                    response = session.post(**request_kwargs)
            else:
                response = requests.post(**request_kwargs)
            response.raise_for_status()
            translated = self._safe_text(
                response.json().get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return translated if self._is_acceptable_zh(translated) else None
        except Exception as error:
            logger.warning("GitHub 简介单条翻译失败，回退原文: %s", error)
            return None

    def _translate_description_to_zh_single_with_retry(
        self,
        text_value: str,
    ) -> Optional[str]:
        attempts = max(1, int(TRANSLATION_SINGLE_RETRY_MAX))
        for _ in range(attempts):
            translated = self._translate_description_to_zh_single(text_value)
            if translated:
                return translated
        return None

    def _enrich_description_zh(
        self,
        period_type: str,
        period_key: str,
        items: list[TrendingItemPayload],
    ) -> None:
        cache = self._load_period_translation_cache(period_type, period_key)
        pending_pairs: list[tuple[int, str]] = []

        for idx, item in enumerate(items):
            repo_key = item.repo_full_name.strip().lower()
            cached = cache.get(repo_key)
            if cached:
                item.description_zh = cached
                continue

            description = self._safe_text(item.description)
            if not description:
                item.description_zh = None
                continue

            if self._is_acceptable_zh(description):
                item.description_zh = description
                continue

            pending_pairs.append((idx, description))

        translated_map = self._translate_descriptions_to_zh_batch(
            [text for _, text in pending_pairs]
        )
        for batch_index, (item_index, _original_text) in enumerate(pending_pairs):
            translated = self._safe_text(translated_map.get(batch_index, ""))
            if translated:
                items[item_index].description_zh = translated
                continue
            single = self._translate_description_to_zh_single_with_retry(_original_text)
            if single:
                items[item_index].description_zh = single
                continue
            items[item_index].description_zh = self._zh_translation_fallback()

    def _request_headers(self) -> dict:
        headers = {
            "User-Agent": "write-agent/1.0 (+github-trending)",
            "Accept": "text/html,application/xhtml+xml",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        return headers

    @staticmethod
    def _truncate_text(value: str, max_len: int) -> str:
        text_value = (value or "").strip()
        if len(text_value) <= max_len:
            return text_value
        return f"{text_value[:max_len]}..."

    @staticmethod
    def _remaining_budget(deadline: float) -> float:
        return max(0.1, deadline - time.monotonic())

    @staticmethod
    def _default_enrich_meta(attempted: bool) -> EnrichmentMeta:
        return EnrichmentMeta(
            attempted=attempted,
            cache_hit=False,
            degraded=False,
            degrade_reason="",
            duration_ms=0,
            fetched_at="",
            sources=[],
        )

    def _finalize_enrich_meta(self, meta: EnrichmentMeta, start: float) -> EnrichmentMeta:
        meta.duration_ms = int((time.monotonic() - start) * 1000)
        return meta

    def _request_json_with_retry(
        self,
        url: str,
        headers: dict[str, str],
        deadline: float,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=min(2.5, self._remaining_budget(deadline)),
                )
                response.raise_for_status()
                return response.json()
            except Exception as error:
                last_error = error
                if attempt == 0 and self._remaining_budget(deadline) > 0.2:
                    time.sleep(0.15)
                    continue
                raise
        raise RuntimeError(str(last_error) if last_error else "request failed")

    def _request_text_with_retry(
        self,
        url: str,
        headers: dict[str, str],
        deadline: float,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=min(2.5, self._remaining_budget(deadline)),
                )
                response.raise_for_status()
                return response.text
            except Exception as error:
                last_error = error
                if attempt == 0 and self._remaining_budget(deadline) > 0.2:
                    time.sleep(0.15)
                    continue
                raise
        raise RuntimeError(str(last_error) if last_error else "request failed")

    @staticmethod
    def _readme_to_plain_text(readme_markdown: str) -> str:
        if not readme_markdown:
            return ""
        text_value = readme_markdown
        text_value = re.sub(r"```[\s\S]*?```", " ", text_value)
        text_value = re.sub(r"`([^`]+)`", r"\1", text_value)
        text_value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text_value)
        text_value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text_value)
        text_value = re.sub(r"[#>*_~\-]{1,}", " ", text_value)
        text_value = re.sub(r"\s+", " ", text_value)
        return text_value.strip()

    def _extract_readme_highlights(self, readme_markdown: str) -> dict[str, Any]:
        if not readme_markdown:
            return {"summary": "", "feature_points": [], "quick_start": []}

        lines = [line.strip() for line in readme_markdown.splitlines() if line.strip()]
        clean_lines = [line for line in lines if not line.startswith("```")]
        plain_text = self._readme_to_plain_text(readme_markdown)
        summary = ""
        for line in clean_lines:
            candidate = re.sub(r"^[#>*\-\s]+", "", line).strip()
            if len(candidate) >= 20 and not candidate.startswith("http"):
                summary = candidate
                break
        if not summary:
            summary = plain_text

        feature_points: list[str] = []
        quick_start: list[str] = []
        for line in clean_lines:
            normalized = re.sub(r"^[>*\-\d.\s]+", "", line).strip()
            if not normalized:
                continue
            lower = normalized.lower()
            if (
                re.match(r"^[A-Za-z0-9\u4e00-\u9fff]", normalized)
                and (
                    line.startswith(("-", "*"))
                    or "feature" in lower
                    or "支持" in normalized
                    or "提供" in normalized
                )
            ):
                feature_points.append(normalized)

            if (
                any(keyword in lower for keyword in ("install", "usage", "quick start", "getting started"))
                or "安装" in normalized
                or "使用" in normalized
                or re.search(r"\b(pip|npm|pnpm|yarn|cargo|go install)\b", lower)
            ):
                quick_start.append(normalized)

        return {
            "summary": summary,
            "feature_points": self._dedupe_lines(feature_points),
            "quick_start": self._dedupe_lines(quick_start),
        }

    @staticmethod
    def _extract_readme_urls(readme_markdown: str) -> list[str]:
        if not readme_markdown:
            return []
        markdown_links = re.findall(r"\[[^\]]+\]\((https://[^)\s]+)\)", readme_markdown)
        plain_links = re.findall(r"(https://[^\s)]+)", readme_markdown)
        links = markdown_links + plain_links
        normalized: list[str] = []
        seen: set[str] = set()
        for link in links:
            link_value = link.strip()
            if not link_value.startswith("https://"):
                continue
            if link_value in seen:
                continue
            seen.add(link_value)
            normalized.append(link_value)
        return normalized

    def _select_external_urls(
        self,
        repo_data: dict[str, Any],
        readme_markdown: str,
    ) -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()

        homepage = self._safe_text(str(repo_data.get("homepage") or ""))
        if homepage.startswith("https://"):
            selected.append(homepage)
            seen.add(homepage)

        for link in self._extract_readme_urls(readme_markdown):
            if len(selected) >= ENRICHMENT_EXTERNAL_LINK_MAX:
                break
            if link in seen:
                continue
            lower = link.lower()
            if any(keyword in lower for keyword in DOC_LINK_KEYWORDS):
                selected.append(link)
                seen.add(link)

        return selected[:ENRICHMENT_EXTERNAL_LINK_MAX]

    def _fetch_external_page_summary(
        self,
        url: str,
        deadline: float,
    ) -> Optional[dict[str, str]]:
        try:
            html_text = self._request_text_with_retry(
                url=url,
                headers={"User-Agent": "write-agent/1.0 (+github-trending)"},
                deadline=deadline,
            )
            soup = BeautifulSoup(html_text, "html.parser")
            title = self._safe_text(
                soup.title.get_text(" ", strip=True) if soup.title else ""
            )
            for node in soup(["script", "style", "nav", "footer", "header"]):
                node.decompose()
            paragraphs = [
                self._safe_text(p.get_text(" ", strip=True))
                for p in soup.select("p")
                if self._safe_text(p.get_text(" ", strip=True))
            ]
            summary = ""
            for paragraph in paragraphs:
                if len(paragraph) >= 30:
                    summary = paragraph
                    break
            if not summary:
                summary = self._truncate_text(soup.get_text(" ", strip=True), 180)
            if not title and not summary:
                return None
            return {
                "url": url,
                "title": self._truncate_text(title, 120),
                "summary": self._truncate_text(summary, 220),
            }
        except Exception:
            return None

    def _load_enrichment_cache(self, repo_full_name: str) -> Optional[GitHubRepoEnrichmentCache]:
        with Session(engine) as session:
            return session.exec(
                select(GitHubRepoEnrichmentCache).where(
                    GitHubRepoEnrichmentCache.repo_full_name == repo_full_name
                )
            ).first()

    def _upsert_enrichment_cache(
        self,
        repo_full_name: str,
        payload: Optional[dict[str, Any]] = None,
        last_error: Optional[str] = None,
    ) -> None:
        now = datetime.now(self.timezone)
        with Session(engine) as session:
            record = session.exec(
                select(GitHubRepoEnrichmentCache).where(
                    GitHubRepoEnrichmentCache.repo_full_name == repo_full_name
                )
            ).first()
            if record is None:
                if payload is None:
                    return
                record = GitHubRepoEnrichmentCache(
                    repo_full_name=repo_full_name,
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    fetched_at=now,
                    last_error=last_error,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                if payload is not None:
                    record.payload_json = json.dumps(payload, ensure_ascii=False)
                    record.fetched_at = now
                record.last_error = last_error
                record.updated_at = now
            session.commit()

    @staticmethod
    def _cache_is_fresh(record: GitHubRepoEnrichmentCache) -> bool:
        now = datetime.now(record.fetched_at.tzinfo) if record.fetched_at.tzinfo else datetime.now()
        return (now - record.fetched_at) <= ENRICHMENT_CACHE_TTL

    def _fetch_repo_enrichment(self, repo_full_name: str, deadline: float) -> dict[str, Any]:
        if self._remaining_budget(deadline) <= 0.15:
            raise TimeoutError("enhancement_timeout")

        api_headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "write-agent/1.0 (+github-trending)",
        }

        repo_api_url = f"https://api.github.com/repos/{repo_full_name}"
        repo_data = self._request_json_with_retry(
            url=repo_api_url,
            headers=api_headers,
            deadline=deadline,
        )
        sources = ["github_api"]

        readme_markdown = ""
        try:
            readme_data = self._request_json_with_retry(
                url=f"{repo_api_url}/readme",
                headers=api_headers,
                deadline=deadline,
            )
            encoded = self._safe_text(str(readme_data.get("content") or ""))
            if encoded:
                readme_markdown = base64.b64decode(encoded).decode("utf-8", errors="ignore")
                sources.append("readme")
        except Exception:
            readme_markdown = ""

        latest_release: dict[str, str] | None = None
        try:
            release_data = self._request_json_with_retry(
                url=f"{repo_api_url}/releases/latest",
                headers=api_headers,
                deadline=deadline,
            )
            latest_release = {
                "tag": self._safe_text(str(release_data.get("tag_name") or "")),
                "name": self._safe_text(str(release_data.get("name") or "")),
                "published_at": self._safe_text(str(release_data.get("published_at") or "")),
            }
        except Exception:
            latest_release = None

        readme_highlights = self._extract_readme_highlights(readme_markdown)
        external_refs: list[dict[str, str]] = []
        for link in self._select_external_urls(repo_data, readme_markdown):
            if self._remaining_budget(deadline) <= 0.15:
                break
            page_summary = self._fetch_external_page_summary(link, deadline)
            if not page_summary:
                continue
            external_refs.append(page_summary)
            if link == self._safe_text(str(repo_data.get("homepage") or "")):
                if "homepage" not in sources:
                    sources.append("homepage")
            elif "docs" not in sources:
                sources.append("docs")

        payload = {
            "repo_full_name": repo_full_name,
            "description": self._safe_text(str(repo_data.get("description") or "")),
            "topics": repo_data.get("topics") or [],
            "license": self._safe_text(str((repo_data.get("license") or {}).get("name") or "")),
            "stats": {
                "stars": int(repo_data.get("stargazers_count") or 0),
                "forks": int(repo_data.get("forks_count") or 0),
                "open_issues": int(repo_data.get("open_issues_count") or 0),
                "language": self._safe_text(str(repo_data.get("language") or "")),
            },
            "latest_release": latest_release,
            "readme": readme_highlights,
            "external_refs": external_refs,
            "generated_at": datetime.now(self.timezone).isoformat(),
            "sources": sources,
        }
        return payload

    def _get_repo_enrichment(
        self,
        repo_full_name: str,
        enhance: bool = True,
    ) -> tuple[Optional[dict[str, Any]], EnrichmentMeta]:
        start = time.monotonic()
        meta = self._default_enrich_meta(attempted=enhance)
        normalized_repo = self._safe_text(repo_full_name).lower()
        if not enhance:
            return None, self._finalize_enrich_meta(meta, start)

        if not settings.github_token:
            meta.degraded = True
            meta.degrade_reason = "missing_github_token"
            return None, self._finalize_enrich_meta(meta, start)

        cache = self._load_enrichment_cache(normalized_repo)
        if cache and self._cache_is_fresh(cache):
            try:
                payload = json.loads(cache.payload_json)
                meta.cache_hit = True
                meta.fetched_at = cache.fetched_at.isoformat()
                if isinstance(payload, dict):
                    payload_sources = payload.get("sources")
                    if isinstance(payload_sources, list):
                        meta.sources = [str(item) for item in payload_sources]
                return payload, self._finalize_enrich_meta(meta, start)
            except Exception:
                logger.warning("解析仓库增强缓存失败，回退实时抓取: %s", normalized_repo)

        deadline = start + ENRICHMENT_TIMEOUT_SECONDS
        try:
            payload = self._fetch_repo_enrichment(normalized_repo, deadline=deadline)
            self._upsert_enrichment_cache(normalized_repo, payload=payload, last_error=None)
            meta.fetched_at = str(payload.get("generated_at") or "")
            payload_sources = payload.get("sources")
            if isinstance(payload_sources, list):
                meta.sources = [str(item) for item in payload_sources]
            return payload, self._finalize_enrich_meta(meta, start)
        except Exception as error:
            logger.warning("仓库增强抓取失败: %s, error=%s", normalized_repo, error)
            self._upsert_enrichment_cache(
                normalized_repo,
                payload=None,
                last_error=self._truncate_text(str(error), 300),
            )
            meta.degraded = True
            error_text = str(error).lower()
            if "timeout" in error_text:
                meta.degrade_reason = "timeout"
            elif "403" in error_text or "429" in error_text:
                meta.degrade_reason = "rate_limited"
            else:
                meta.degrade_reason = "fetch_failed"
            return None, self._finalize_enrich_meta(meta, start)

    def _fetch_trending_top10(self, period_type: str = "weekly") -> list[TrendingItemPayload]:
        mode = self._normalize_period_type(period_type)
        url = TRENDING_DAILY_URL if mode == "daily" else TRENDING_WEEKLY_URL
        response = requests.get(
            url,
            headers=self._request_headers(),
            timeout=20,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("article.Box-row")
        if not rows:
            rows = soup.select("article")

        items: list[TrendingItemPayload] = []
        for rank, row in enumerate(rows[:10], start=1):
            title_link = row.select_one("h2 a")
            if title_link is None:
                continue

            href = self._safe_text(title_link.get("href", ""))
            parts = [p for p in href.strip("/").split("/") if p]
            if len(parts) < 2:
                continue

            owner, repo_name = parts[0], parts[1]
            repo_full_name = f"{owner}/{repo_name}"
            repo_url = f"https://github.com/{repo_full_name}"

            desc_node = row.select_one("p")
            description = self._safe_text(desc_node.get_text(" ", strip=True) if desc_node else "")

            language_node = row.select_one('span[itemprop="programmingLanguage"]')
            language = self._safe_text(
                language_node.get_text(" ", strip=True) if language_node else ""
            ) or None

            total_stars = None
            for link in row.select("a"):
                href_val = self._safe_text(link.get("href", ""))
                if href_val.endswith("/stargazers"):
                    total_stars = self._parse_int(link.get_text(" ", strip=True))
                    if total_stars is not None:
                        break

            stars_this_week = 0
            week_span = row.select_one("span.d-inline-block.float-sm-right")
            week_text = self._safe_text(
                week_span.get_text(" ", strip=True) if week_span else ""
            )
            if not week_text:
                for span in row.select("span"):
                    text = self._safe_text(span.get_text(" ", strip=True))
                    if "this week" in text.lower():
                        week_text = text
                        break

            match = STAR_PERIOD_PATTERN.search(week_text)
            if match:
                stars_this_week = self._parse_int(match.group(1)) or 0
            else:
                stars_this_week = self._parse_int(week_text) or 0

            items.append(
                TrendingItemPayload(
                    rank=rank,
                    repo_full_name=repo_full_name,
                    repo_name=repo_name,
                    owner=owner,
                    description=description,
                    description_zh=None,
                    repo_url=repo_url,
                    stars_this_week=stars_this_week,
                    language=language,
                    total_stars=total_stars,
                )
            )

        if not items:
            raise RuntimeError("未能解析到 GitHub Trending 周榜数据")

        return items

    def _upsert_failed_snapshot(self, week_key: str, snapshot_date: date, error_message: str) -> None:
        self._upsert_failed_period_snapshot(
            period_type="weekly",
            period_key=week_key,
            week_key=week_key,
            snapshot_date=snapshot_date,
            error_message=error_message,
        )

    def _upsert_failed_period_snapshot(
        self,
        *,
        period_type: str,
        period_key: str,
        week_key: str,
        snapshot_date: date,
        error_message: str,
    ) -> None:
        store_week_key = week_key if period_type == "weekly" else period_key
        with Session(engine) as session:
            snapshot = session.exec(
                select(GitHubTrendingSnapshot).where(
                    GitHubTrendingSnapshot.period_type == period_type,
                    GitHubTrendingSnapshot.period_key == period_key,
                    GitHubTrendingSnapshot.snapshot_date == snapshot_date,
                )
            ).first()

            now = datetime.now(self.timezone)
            if snapshot is None:
                snapshot = GitHubTrendingSnapshot(
                    week_key=store_week_key,
                    period_type=period_type,
                    period_key=period_key,
                    snapshot_date=snapshot_date,
                    captured_at=now,
                    is_weekly_archive=False,
                    fetch_status="failed",
                    fetch_error=error_message[:500],
                )
                session.add(snapshot)
            else:
                snapshot.captured_at = now
                snapshot.fetch_status = "failed"
                snapshot.fetch_error = error_message[:500]
                snapshot.week_key = store_week_key

            session.commit()

    def _archive_previous_week_if_needed(self, session: Session, now_date: date) -> None:
        if now_date.weekday() != 0:  # 周一
            return

        previous_week_date = now_date - timedelta(days=7)
        previous_week_key = self.week_key_for_date(previous_week_date)
        previous_latest = session.exec(
            select(GitHubTrendingSnapshot)
            .where(
                GitHubTrendingSnapshot.week_key == previous_week_key,
                GitHubTrendingSnapshot.fetch_status == "success",
            )
            .order_by(desc(GitHubTrendingSnapshot.captured_at))
        ).first()
        if previous_latest is None:
            return

        session.exec(
            update(GitHubTrendingSnapshot)
            .where(GitHubTrendingSnapshot.week_key == previous_week_key)
            .values(is_weekly_archive=False)
        )
        previous_latest.is_weekly_archive = True

    def _save_success_snapshot(
        self,
        week_key: str,
        snapshot_date: date,
        items: list[TrendingItemPayload],
    ) -> GitHubTrendingSnapshot:
        return self._save_success_period_snapshot(
            period_type="weekly",
            period_key=week_key,
            week_key=week_key,
            snapshot_date=snapshot_date,
            items=items,
        )

    def _save_success_period_snapshot(
        self,
        *,
        period_type: str,
        period_key: str,
        week_key: str,
        snapshot_date: date,
        items: list[TrendingItemPayload],
    ) -> GitHubTrendingSnapshot:
        now = datetime.now(self.timezone)
        store_week_key = week_key if period_type == "weekly" else period_key
        with Session(engine) as session:
            snapshot = session.exec(
                select(GitHubTrendingSnapshot).where(
                    GitHubTrendingSnapshot.period_type == period_type,
                    GitHubTrendingSnapshot.period_key == period_key,
                    GitHubTrendingSnapshot.snapshot_date == snapshot_date,
                )
            ).first()

            if snapshot is None:
                snapshot = GitHubTrendingSnapshot(
                    week_key=store_week_key,
                    period_type=period_type,
                    period_key=period_key,
                    snapshot_date=snapshot_date,
                    captured_at=now,
                    fetch_status="success",
                    fetch_error=None,
                    is_weekly_archive=False,
                )
                session.add(snapshot)
                session.flush()
            else:
                snapshot.captured_at = now
                snapshot.fetch_status = "success"
                snapshot.fetch_error = None
                snapshot.week_key = store_week_key
                session.exec(
                    delete(GitHubTrendingItem).where(
                        GitHubTrendingItem.snapshot_id == snapshot.id
                    )
                )

            for item in items:
                session.add(
                    GitHubTrendingItem(
                        snapshot_id=snapshot.id,
                        rank=item.rank,
                        repo_full_name=item.repo_full_name,
                        repo_name=item.repo_name,
                        owner=item.owner,
                        description=item.description,
                        description_zh=item.description_zh,
                        repo_url=item.repo_url,
                        stars_this_week=item.stars_this_week,
                        language=item.language,
                        total_stars=item.total_stars,
                    )
                )

            if period_type == "weekly":
                self._archive_previous_week_if_needed(session, now.date())
            session.commit()
            session.refresh(snapshot)
            return snapshot

    def _fetch_and_persist_current_week(self) -> GitHubTrendingSnapshot:
        return self._fetch_and_persist_period("weekly")

    def _fetch_and_persist_period(self, period_type: str) -> GitHubTrendingSnapshot:
        now = datetime.now(self.timezone)
        mode = self._normalize_period_type(period_type)
        if mode == "daily":
            period_key = now.date().isoformat()
            week_key = period_key
        else:
            period_key = self.week_key_for_date(now.date())
            week_key = period_key
        snapshot_date = now.date()
        try:
            items = self._fetch_trending_top10(mode)
            self._enrich_description_zh(mode, period_key, items)
        except Exception as error:
            logger.error("抓取 GitHub Trending 失败(%s): %s", mode, error, exc_info=True)
            self._upsert_failed_period_snapshot(
                period_type=mode,
                period_key=period_key,
                week_key=week_key,
                snapshot_date=snapshot_date,
                error_message=str(error),
            )
            raise

        return self._save_success_period_snapshot(
            period_type=mode,
            period_key=period_key,
            week_key=week_key,
            snapshot_date=snapshot_date,
            items=items,
        )

    def _needs_translation_retry(self, description: str, description_zh: Optional[str]) -> bool:
        original = self._safe_text(description)
        translated = self._safe_text(description_zh)
        fallback = self._zh_translation_fallback()
        if not original:
            return False
        if translated == fallback:
            return True
        if self._is_acceptable_zh(translated):
            return False
        if self._is_acceptable_zh(original):
            return translated != original
        return True

    def _retry_untranslated_descriptions_for_period(
        self,
        period_type: str,
        period_key: Optional[str] = None,
    ) -> GitHubTrendingSnapshot:
        mode = self._normalize_period_type(period_type)
        normalized_period_key = self._normalize_period_key(mode, period_key)
        with Session(engine) as session:
            snapshot = session.exec(
                select(GitHubTrendingSnapshot)
                .where(
                    GitHubTrendingSnapshot.period_type == mode,
                    GitHubTrendingSnapshot.period_key == normalized_period_key,
                    GitHubTrendingSnapshot.fetch_status == "success",
                )
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            ).first()
            if snapshot is None:
                raise ValueError(f"{mode} 数据不存在: {normalized_period_key}")

            rows = session.exec(
                select(GitHubTrendingItem)
                .where(GitHubTrendingItem.snapshot_id == snapshot.id)
                .order_by(GitHubTrendingItem.rank)
            ).all()
            if not rows:
                raise ValueError(f"{mode} 数据为空: {normalized_period_key}")

            row_ids: list[int] = []
            payload_items: list[TrendingItemPayload] = []
            for row in rows:
                if row.id is None:
                    continue
                row_ids.append(int(row.id))
                payload_items.append(
                    TrendingItemPayload(
                        rank=row.rank,
                        repo_full_name=row.repo_full_name,
                        repo_name=row.repo_name,
                        owner=row.owner,
                        description=row.description or "",
                        description_zh=row.description_zh or None,
                        repo_url=row.repo_url,
                        stars_this_week=row.stars_this_week,
                        language=row.language,
                        total_stars=row.total_stars,
                    )
                )

        pending_before = sum(
            1
            for item in payload_items
            if self._needs_translation_retry(item.description, item.description_zh)
        )
        if pending_before == 0:
            logger.info(
                "GitHub 趋势补翻跳过：%s/%s 无未完成中文翻译条目",
                mode,
                normalized_period_key,
            )
            return snapshot

        self._enrich_description_zh(mode, normalized_period_key, payload_items)
        pending_after = sum(
            1
            for item in payload_items
            if self._needs_translation_retry(item.description, item.description_zh)
        )
        now = datetime.now(self.timezone)

        with Session(engine) as session:
            persisted_snapshot = session.exec(
                select(GitHubTrendingSnapshot).where(GitHubTrendingSnapshot.id == snapshot.id)
            ).first()
            if persisted_snapshot is None:
                raise ValueError(f"{mode} 数据不存在: {normalized_period_key}")

            for row_id, item in zip(row_ids, payload_items):
                session.exec(
                    update(GitHubTrendingItem)
                    .where(GitHubTrendingItem.id == row_id)
                    .values(description_zh=item.description_zh)
                )

            persisted_snapshot.captured_at = now
            session.commit()
            session.refresh(persisted_snapshot)

        logger.info(
            "GitHub 趋势补翻完成：%s/%s before=%s after=%s",
            mode,
            normalized_period_key,
            pending_before,
            pending_after,
        )
        return persisted_snapshot

    async def refresh_current_week_snapshot(self) -> GitHubTrendingSnapshot:
        return await self.refresh_snapshot("weekly")

    async def refresh_snapshot(
        self,
        period_type: str = "weekly",
        *,
        period_key: Optional[str] = None,
        retry_untranslated_only: bool = False,
    ) -> GitHubTrendingSnapshot:
        with obs_scope("SVC.GITHUB_TRENDS.REFRESH", "WORKFLOW_NODE"):
            if self.refresh_lock.locked():
                raise RefreshInProgressError("GitHub 趋势更新中")

            async with self.refresh_lock:
                mode = self._normalize_period_type(period_type)
                emit_obs_event(
                    level="INFO",
                    message="svc.github_trends.refresh.start",
                    payload={
                        "period_type": mode,
                        "period_key": period_key or "",
                        "retry_untranslated_only": bool(retry_untranslated_only),
                    },
                )
                if retry_untranslated_only:
                    snapshot = await asyncio.to_thread(
                        self._retry_untranslated_descriptions_for_period,
                        mode,
                        period_key,
                    )
                else:
                    snapshot = await asyncio.to_thread(self._fetch_and_persist_period, mode)
                bind_entities({"week_key": snapshot.week_key, "period_key": snapshot.period_key})
                emit_obs_event(
                    level="INFO",
                    message="svc.github_trends.refresh.done",
                    entities={"week_key": snapshot.week_key, "period_key": snapshot.period_key},
                    payload={
                        "snapshot_date": snapshot.snapshot_date.isoformat(),
                        "period_type": snapshot.period_type,
                        "period_key": snapshot.period_key,
                        "retry_untranslated_only": bool(retry_untranslated_only),
                    },
                )
                return snapshot

    def is_refresh_running(self) -> bool:
        return self.refresh_lock.locked()

    def _snapshot_to_dict(
        self,
        snapshot: GitHubTrendingSnapshot,
        requested_week_key: str,
        requested_period_type: str = "weekly",
        requested_period_key: Optional[str] = None,
    ) -> dict:
        with Session(engine) as session:
            items = session.exec(
                select(GitHubTrendingItem)
                .where(GitHubTrendingItem.snapshot_id == snapshot.id)
                .order_by(GitHubTrendingItem.rank)
            ).all()

            latest_failed = session.exec(
                select(GitHubTrendingSnapshot)
                .where(
                    GitHubTrendingSnapshot.period_type == snapshot.period_type,
                    GitHubTrendingSnapshot.period_key == snapshot.period_key,
                    GitHubTrendingSnapshot.week_key == requested_week_key,
                    GitHubTrendingSnapshot.fetch_status == "failed",
                )
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            ).first()

        return {
            "week_key": snapshot.week_key,
            "requested_week_key": requested_week_key,
            "period_type": snapshot.period_type,
            "requested_period_type": requested_period_type,
            "period_key": snapshot.period_key,
            "requested_period_key": requested_period_key or requested_week_key,
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "captured_at": snapshot.captured_at.isoformat(),
            "is_weekly_archive": snapshot.is_weekly_archive,
            "is_stale": (
                snapshot.period_type != requested_period_type
                or snapshot.period_key != (requested_period_key or requested_week_key)
            ),
            "is_refreshing": self.is_refresh_running(),
            "fetch_error": latest_failed.fetch_error if latest_failed else None,
            "items": [
                {
                    "rank": item.rank,
                    "repo_full_name": item.repo_full_name,
                    "repo_name": item.repo_name,
                    "owner": item.owner,
                    "description": item.description,
                    "description_zh": item.description_zh,
                    "repo_url": item.repo_url,
                    "stars_this_week": item.stars_this_week,
                    "language": item.language,
                    "total_stars": item.total_stars,
                }
                for item in items
            ],
        }

    def _latest_success_snapshot_for_week(self, week_key: str) -> Optional[GitHubTrendingSnapshot]:
        return self._latest_success_snapshot_for_period("weekly", week_key)

    def _latest_success_snapshot_for_period(
        self,
        period_type: str,
        period_key: str,
    ) -> Optional[GitHubTrendingSnapshot]:
        mode = self._normalize_period_type(period_type)
        normalized_key = self._normalize_period_key(mode, period_key)
        with Session(engine) as session:
            archive = session.exec(
                select(GitHubTrendingSnapshot)
                .where(
                    GitHubTrendingSnapshot.period_type == mode,
                    GitHubTrendingSnapshot.period_key == normalized_key,
                    GitHubTrendingSnapshot.fetch_status == "success",
                    GitHubTrendingSnapshot.is_weekly_archive == True,  # noqa: E712
                )
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            ).first()
            if archive:
                return archive

            return session.exec(
                select(GitHubTrendingSnapshot)
                .where(
                    GitHubTrendingSnapshot.period_type == mode,
                    GitHubTrendingSnapshot.period_key == normalized_key,
                    GitHubTrendingSnapshot.fetch_status == "success",
                )
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            ).first()

    def _latest_success_snapshot_global(
        self,
        period_type: Optional[str] = None,
    ) -> Optional[GitHubTrendingSnapshot]:
        mode = self._normalize_period_type(period_type or "weekly")
        with Session(engine) as session:
            statement = (
                select(GitHubTrendingSnapshot)
                .where(
                    GitHubTrendingSnapshot.fetch_status == "success",
                    GitHubTrendingSnapshot.period_type == mode,
                )
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            )
            return session.exec(statement).first()

    def get_snapshot(
        self,
        week_key: Optional[str] = None,
        period_type: str = "weekly",
        period_key: Optional[str] = None,
    ) -> dict:
        with obs_scope(
            "SVC.GITHUB_TRENDS.GET_SNAPSHOT",
            "DB_READ",
            entities={
                "week_key": week_key,
                "period_type": period_type,
                "period_key": period_key,
            },
        ):
            mode = self._normalize_period_type(period_type)
            if mode == "weekly":
                target_period_key = self._normalize_week_key(
                    period_key or week_key or self.current_week_key()
                )
                target_week_key = target_period_key
            else:
                target_period_key = self._normalize_daily_key(
                    period_key or self.current_daily_key()
                )
                target_week_key = week_key or target_period_key

            snapshot = self._latest_success_snapshot_for_period(mode, target_period_key)
            if snapshot is None:
                snapshot = self._latest_success_snapshot_global(mode)
            if snapshot is None:
                raise ValueError("暂无可用的 GitHub 趋势快照，请先手动更新")
            emit_obs_event(
                level="INFO",
                message="svc.github_trends.get_snapshot",
                entities={
                    "week_key": target_week_key,
                    "period_type": mode,
                    "period_key": target_period_key,
                },
            )
            return self._snapshot_to_dict(
                snapshot,
                target_week_key,
                requested_period_type=mode,
                requested_period_key=target_period_key,
            )

    def list_available_weeks(self) -> list[dict]:
        weekly = self.list_available_periods("weekly", limit=52)
        return [
            {
                "week_key": item["period_key"],
                "latest_snapshot_date": item["latest_snapshot_date"],
                "latest_captured_at": item["latest_captured_at"],
                "has_archive": item.get("has_archive", False),
            }
            for item in weekly
        ]

    def list_available_periods(self, period_type: str, limit: int = 12) -> list[dict]:
        mode = self._normalize_period_type(period_type)
        with obs_scope("SVC.GITHUB_TRENDS.PERIODS", "DB_READ"):
            with Session(engine) as session:
                snapshots = session.exec(
                    select(GitHubTrendingSnapshot)
                    .where(
                        GitHubTrendingSnapshot.fetch_status == "success",
                        GitHubTrendingSnapshot.period_type == mode,
                    )
                    .order_by(desc(GitHubTrendingSnapshot.captured_at))
                ).all()

            by_period: dict[str, dict] = {}
            for snapshot in snapshots:
                period_key = snapshot.period_key or snapshot.week_key
                period_entry = by_period.get(period_key)
                if period_entry is None:
                    by_period[period_key] = {
                        "period_type": mode,
                        "period_key": period_key,
                        "latest_snapshot_date": snapshot.snapshot_date.isoformat(),
                        "latest_captured_at": snapshot.captured_at.isoformat(),
                        "has_archive": bool(snapshot.is_weekly_archive),
                    }
                else:
                    period_entry["has_archive"] = (
                        bool(period_entry["has_archive"]) or bool(snapshot.is_weekly_archive)
                    )

            ordered = sorted(by_period.values(), key=lambda item: item["period_key"], reverse=True)[
                : max(1, limit)
            ]
            emit_obs_event(
                level="INFO",
                message="svc.github_trends.list_periods",
                payload={"total": len(ordered), "period_type": mode},
            )
            return ordered

    def _find_week_item(self, week_key: str, repo_full_name: str) -> TrendingItemPayload:
        return self._find_period_item("weekly", week_key, repo_full_name)

    def _find_period_item(
        self,
        period_type: str,
        period_key: str,
        repo_full_name: str,
    ) -> TrendingItemPayload:
        mode = self._normalize_period_type(period_type)
        normalized_period_key = self._normalize_period_key(mode, period_key)
        normalized_repo = (repo_full_name or "").strip().lower()
        if not normalized_repo:
            raise ValueError("repo_full_name 不能为空")

        with Session(engine) as session:
            snapshot = session.exec(
                select(GitHubTrendingSnapshot)
                .where(
                    GitHubTrendingSnapshot.period_type == mode,
                    GitHubTrendingSnapshot.period_key == normalized_period_key,
                    GitHubTrendingSnapshot.fetch_status == "success",
                )
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            ).first()
            if snapshot is None:
                raise ValueError(f"{mode} 数据不存在: {normalized_period_key}")

            rows = session.exec(
                select(GitHubTrendingItem).where(
                    GitHubTrendingItem.snapshot_id == snapshot.id,
                )
            ).all()

        for row in rows:
            if row.repo_full_name.lower() == normalized_repo:
                return TrendingItemPayload(
                    rank=row.rank,
                    repo_full_name=row.repo_full_name,
                    repo_name=row.repo_name,
                    owner=row.owner,
                    description=row.description or "",
                    description_zh=row.description_zh or None,
                    repo_url=row.repo_url,
                    stars_this_week=row.stars_this_week,
                    language=row.language,
                    total_stars=row.total_stars,
                )
        raise ValueError(f"未找到项目: {repo_full_name}")

    @staticmethod
    def _has_enrichment_section(content: str) -> bool:
        source = content or ""
        has_new_block = (
            "### 项目介绍" in source
            and "### 核心特点与优势" in source
            and "### 为什么会受欢迎" in source
        )
        has_legacy_block = (
            ENRICHMENT_SECTION_HEADER in source
            or "<!-- github-enrich repo:" in source
        )
        return has_new_block or has_legacy_block

    @staticmethod
    def _has_legacy_material_scaffolding(content: str) -> bool:
        source = content or ""
        return "## 本周观察（可补充）" in source and "## 改写方向（可补充）" in source

    def _strip_legacy_material_scaffolding(self, content: str) -> str:
        source = (content or "").strip()
        if not source:
            return source
        pattern = re.compile(
            r"\n## 本周观察（可补充）[\s\S]*?\n## 改写方向（可补充）[\s\S]*?(?=\n## |\Z)",
            re.MULTILINE,
        )
        cleaned = pattern.sub("\n", source)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _upsert_enrichment_section_in_content(
        self,
        content: str,
        section_text: str,
    ) -> str:
        source = self._strip_legacy_material_scaffolding(content or "")
        new_section = section_text.strip()
        if not source:
            return new_section

        marker_pattern = re.compile(
            r"\n*<!-- github-enrich repo:[^\n]* -->\n## 仓库增强信息（自动抓取）[\s\S]*$",
            re.MULTILINE,
        )
        if marker_pattern.search(source):
            return marker_pattern.sub(f"\n\n{new_section}", source).strip()

        header_pattern = re.compile(
            r"\n*## 仓库增强信息（自动抓取）[\s\S]*$",
            re.MULTILINE,
        )
        if header_pattern.search(source):
            return header_pattern.sub(f"\n\n{new_section}", source).strip()

        new_pattern = re.compile(
            r"\n*### 项目介绍[\s\S]*$",
            re.MULTILINE,
        )
        if new_pattern.search(source):
            return new_pattern.sub(f"\n\n{new_section}", source).strip()
        return f"{source}\n\n{new_section}".strip()

    def _pick_chinese_text(self, *values: Any, fallback: str) -> str:
        for raw in values:
            text_value = self._safe_text(str(raw or ""))
            if text_value and self._is_acceptable_zh(text_value):
                return text_value
        for raw in values:
            text_value = self._safe_text(str(raw or ""))
            if text_value and self._contains_chinese(text_value):
                return text_value
        return fallback

    @staticmethod
    def _dedupe_lines(lines: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for line in lines:
            text_value = (line or "").strip()
            if not text_value or text_value in seen:
                continue
            seen.add(text_value)
            deduped.append(text_value)
        return deduped

    def _build_advantage_points(
        self,
        item: TrendingItemPayload,
        enrichment_payload: dict[str, Any],
        limit: Optional[int] = None,
    ) -> list[str]:
        readme = enrichment_payload.get("readme") or {}
        topics = enrichment_payload.get("topics") or []
        stats = enrichment_payload.get("stats") or {}
        quick_start = readme.get("quick_start") or []

        candidates: list[str] = []
        for point in readme.get("feature_points") or []:
            point_text = self._safe_text(str(point))
            if not point_text:
                continue
            if self._is_acceptable_zh(point_text) or self._contains_chinese(point_text):
                candidates.append(self._trim_sentence_tail(point_text))

        for point in quick_start:
            point_text = self._safe_text(str(point))
            if not point_text:
                continue
            if self._is_acceptable_zh(point_text) or self._contains_chinese(point_text):
                candidates.append(f"工程细节涉及：{self._trim_sentence_tail(point_text)}")

        for topic in topics:
            topic_text = self._safe_text(str(topic))
            if topic_text:
                candidates.append(f"围绕主题“{topic_text}”形成了可复用的能力模块。")

        language = self._safe_text(str(stats.get("language") or ""))
        if language:
            candidates.append(f"主要技术语言为 {language}，便于工程团队按语言生态进行二次扩展。")

        if not candidates:
            fallback_intro = self._pick_chinese_text(
                item.description_zh,
                enrichment_payload.get("description"),
                item.description,
                fallback="围绕真实问题提供可执行能力，强调效率提升与结果可复用。",
            )
            candidates = [
                self._trim_sentence_tail(fallback_intro),
                "关注工程化落地与长期维护成本，适合沉淀为内容选题。",
            ]
        deduped = self._dedupe_lines(candidates)
        if limit is not None and limit > 0:
            return deduped[:limit]
        return deduped

    def _build_popularity_reasons(
        self,
        item: TrendingItemPayload,
        stats: dict[str, Any],
        latest_release: dict[str, Any],
    ) -> list[str]:
        stars_total = int(stats.get("stars") or item.total_stars or 0)
        forks = int(stats.get("forks") or 0)
        open_issues = int(stats.get("open_issues") or 0)

        reasons: list[str] = []
        if item.stars_this_week > 0:
            reasons.append(f"本周新增星标 {item.stars_this_week}，短期关注度持续走高。")
        if stars_total > 0 or forks > 0:
            reasons.append(f"累计星标 {stars_total}、分叉 {forks}，社区认可度较高。")
        if open_issues > 0:
            reasons.append(f"公开问题 {open_issues} 条，说明社区反馈活跃、迭代信号明确。")

        release_name = self._safe_text(
            str(latest_release.get("tag") or latest_release.get("name") or "")
        )
        release_time = self._safe_text(str(latest_release.get("published_at") or ""))
        if release_name:
            if release_time:
                reasons.append(f"近期仍有版本发布（{release_name}，{release_time}），维护节奏稳定。")
            else:
                reasons.append(f"近期发布版本 {release_name}，持续迭代能力清晰可见。")

        if not reasons:
            reasons.append("项目定位清晰、价值表达直接，易被开发者快速理解并传播。")
        return self._dedupe_lines([self._truncate_text(reason, 92) for reason in reasons])[:3]

    def _build_advantage_paragraph(
        self,
        item: TrendingItemPayload,
        enrichment_payload: dict[str, Any],
    ) -> str:
        readme = enrichment_payload.get("readme") or {}
        topics = enrichment_payload.get("topics") or []
        stats = enrichment_payload.get("stats") or {}
        latest_release = enrichment_payload.get("latest_release") or {}

        points = self._build_advantage_points(item, enrichment_payload, limit=None)
        points_text = "；".join([self._trim_sentence_tail(point) for point in points]) or "能力边界清晰、价值表达直接"

        language = self._safe_text(str(stats.get("language") or ""))
        license_text = self._safe_text(str(enrichment_payload.get("license") or ""))
        release_name = self._safe_text(
            str(latest_release.get("tag") or latest_release.get("name") or "")
        )
        release_time = self._safe_text(str(latest_release.get("published_at") or ""))
        topic_count = len(topics) if isinstance(topics, list) else 0

        lines = [
            f"基于仓库公开信息，{item.repo_full_name} 的核心能力可以拆成以下几类：{points_text}。",
            "与同类项目相比，它不是只提供单点脚本或孤立工具，而是强调模块间可组合、可复用、可扩展的工程化能力。",
            "这种能力结构让它既能用于快速实验，也能逐步演进为团队级流程资产，差异化体现在“从想法到交付”的完整链路支持。",
        ]
        if language or license_text or topic_count > 0:
            extra_parts: list[str] = []
            if language:
                extra_parts.append(f"主要语言为 {language}")
            if license_text:
                extra_parts.append(f"许可协议为 {license_text}")
            if topic_count > 0:
                extra_parts.append(f"覆盖 {topic_count} 个公开技术主题")
            lines.append("从技术元信息看，" + "、".join(extra_parts) + "，这也强化了其技术可迁移性与长期维护可行性。")

        if release_name:
            if release_time:
                lines.append(f"最近版本为 {release_name}（{release_time}），说明技术亮点在持续演进，而不是一次性发布。")
            else:
                lines.append(f"最近版本为 {release_name}，说明技术亮点在持续演进，而不是一次性发布。")

        summary = self._safe_text(str(readme.get("summary") or ""))
        if summary and (self._is_acceptable_zh(summary) or self._contains_chinese(summary)):
            lines.append(f"README 中对价值主张的表达是：{self._trim_sentence_tail(summary)}。")

        paragraph = "".join(lines).replace("\n", " ").strip()
        paragraph = re.sub(r"\s+", " ", paragraph)
        return paragraph

    def _build_scenario_hint(
        self,
        intro: str,
        advantage_points: list[str],
    ) -> str:
        merged = f"{intro} {' '.join(advantage_points)}"
        scenarios: list[str] = []
        if "智能体" in merged or "代理" in merged:
            scenarios.append("智能体流程设计与任务编排")
        if "自动化" in merged or "流程" in merged:
            scenarios.append("团队流程自动化与协作提效")
        if "数据" in merged or "检索" in merged:
            scenarios.append("知识检索与信息组织优化")
        if "前端" in merged or "浏览器" in merged:
            scenarios.append("前端交互自动化与工具集成")
        if not scenarios:
            scenarios = ["技术选型调研", "工程效率优化", "产品化能力验证"]
        return "、".join(self._dedupe_lines(scenarios)[:3])

    @staticmethod
    def _trim_sentence_tail(value: str) -> str:
        return (value or "").strip().rstrip("。；;，,")

    def _build_intro_paragraph(
        self,
        item: TrendingItemPayload,
        enrichment_payload: dict[str, Any],
    ) -> str:
        readme = enrichment_payload.get("readme") or {}
        topics = enrichment_payload.get("topics") or []

        position = self._pick_chinese_text(
            item.description_zh,
            readme.get("summary"),
            enrichment_payload.get("description"),
            item.description,
            fallback="该项目聚焦智能化开发能力与工程实践落地，强调可复用的方法论与协作效率。",
        )
        position = self._safe_text(position)

        feature_points = readme.get("feature_points") or []
        problem_points: list[str] = []
        for point in feature_points:
            point_text = self._safe_text(str(point))
            if not point_text:
                continue
            if any(
                keyword in point_text
                for keyword in ("解决", "降低", "减少", "提升", "统一", "自动化", "协作", "编排", "管理", "预测")
            ):
                problem_points.append(self._trim_sentence_tail(point_text))

        topic_labels = [self._safe_text(str(topic)) for topic in topics if self._safe_text(str(topic))]
        if not problem_points:
            if topic_labels:
                problem_points.append(
                    f"它主要解决“{topic_labels[0]}”及相关场景中从需求拆解到执行落地成本高、协作断点多的问题"
                )
            else:
                problem_points.append("它主要解决从想法到可交付结果之间链路分散、复用困难、协作成本偏高的问题")

        background_lines: list[str] = []
        if topic_labels:
            background_lines.append(
                "项目背景来自当前 AI 工程实践对系统化能力的需求提升，仓库公开主题覆盖："
                + "、".join(topic_labels)
                + "。"
            )
        readme_summary = self._safe_text(str(readme.get("summary") or ""))
        if readme_summary and (self._is_acceptable_zh(readme_summary) or self._contains_chinese(readme_summary)):
            background_lines.append(f"README 的背景表述强调：{self._trim_sentence_tail(readme_summary)}。")
        if not background_lines:
            background_lines.append("其背景是团队希望把零散工具能力沉淀成可复用、可协作、可持续维护的工程资产。")

        lines: list[str] = [
            f"{item.repo_full_name} 是一个{self._trim_sentence_tail(position)}。",
            "它聚焦的问题是："
            + "；".join(self._dedupe_lines(problem_points))
            + "。",
        ]
        lines.extend(background_lines)

        paragraph = "".join(lines).replace("\n", " ").strip()
        paragraph = re.sub(r"\s+", " ", paragraph)
        return paragraph

    def _build_enrichment_section(
        self,
        item: TrendingItemPayload,
        enrichment_payload: dict[str, Any],
    ) -> str:
        stats = enrichment_payload.get("stats") or {}
        latest_release = enrichment_payload.get("latest_release") or {}

        intro = self._build_intro_paragraph(item, enrichment_payload)
        advantage_paragraph = self._build_advantage_paragraph(item, enrichment_payload)
        popularity_reasons = self._build_popularity_reasons(item, stats, latest_release)

        lines = [
            "### 项目介绍",
            f"- {intro}",
            "",
            "### 核心特点与优势",
            f"- {advantage_paragraph}",
        ]
        lines.extend(["", "### 为什么会受欢迎"])
        lines.extend([f"- {self._truncate_text(reason, 120)}" for reason in popularity_reasons])
        return "\n".join(lines).strip()

    def _build_rewrite_structured_summary(
        self,
        item: TrendingItemPayload,
        enrichment_payload: dict[str, Any],
    ) -> str:
        stats = enrichment_payload.get("stats") or {}
        latest_release = enrichment_payload.get("latest_release") or {}

        position = self._pick_chinese_text(
            item.description_zh,
            enrichment_payload.get("description"),
            (enrichment_payload.get("readme") or {}).get("summary"),
            item.description,
            fallback="该仓库本周增长显著，适合围绕其解决的问题与业务价值进行写作。",
        )
        advantage_points = self._build_advantage_points(item, enrichment_payload, limit=3)
        popularity_reasons = self._build_popularity_reasons(item, stats, latest_release)
        scenarios = self._build_scenario_hint(position, advantage_points)

        open_issues = int(stats.get("open_issues") or 0)
        if open_issues >= 80:
            issue_risk = "公开问题数量较高，说明功能边界与稳定性仍需在真实场景下继续验证。"
        elif open_issues >= 20:
            issue_risk = "仍有一定公开问题待处理，落地前建议先评估稳定性与维护投入。"
        else:
            issue_risk = "公开问题规模可控，但上线前仍建议先完成兼容性与压力验证。"
        license_text = self._safe_text(str(enrichment_payload.get("license") or ""))
        if license_text:
            limits = (
                f"{issue_risk} 同时需要确认许可协议（{license_text}）与商用边界，避免二次分发风险。"
            )
        else:
            limits = f"{issue_risk} 同时需要明确许可边界与版本策略，避免后续合规风险。"

        release_name = self._safe_text(
            str(latest_release.get("tag") or latest_release.get("name") or "")
        )
        release_time = self._safe_text(str(latest_release.get("published_at") or ""))
        trend = (
            f"本周新增星标 {item.stars_this_week}，累计星标 {int(stats.get('stars') or item.total_stars or 0)}，"
            f"分叉 {int(stats.get('forks') or 0)}。"
        )
        if release_name:
            if release_time:
                trend += f" 最近版本为 {release_name}（{release_time}）。"
            else:
                trend += f" 最近版本为 {release_name}。"

        lines = [
            f"- 项目定位：{self._truncate_text(position, 90)}",
            f"- 核心优势：{self._truncate_text('；'.join(advantage_points), 110)}",
            f"- 受欢迎原因：{self._truncate_text('；'.join(popularity_reasons), 120)}",
            f"- 适用场景：{self._truncate_text(scenarios, 90)}",
            f"- 风险/局限：{self._truncate_text(limits, 140)}",
            f"- 最近动态：{self._truncate_text(trend, 120)}",
        ]
        summary = "\n".join(lines).strip()
        if len(summary) < 300:
            lines[4] = (
                lines[4]
                + " 写作时建议补充同类方案对比、团队采用门槛与长期维护成本，避免只强调热度而忽略决策条件。"
            )
            summary = "\n".join(lines).strip()
        return summary[:500]

    def _single_material_content(
        self,
        period_key: str,
        item: TrendingItemPayload,
        enrichment_payload: Optional[dict[str, Any]] = None,
        period_type: str = "weekly",
    ) -> str:
        mode = self._normalize_period_type(period_type)
        period_label = "周榜" if mode == "weekly" else "日榜"
        star_label = "本周新增 Star" if mode == "weekly" else "今日新增 Star"
        description = item.description_zh or item.description or "暂无简介"
        lines = [
            f"# GitHub {period_label}项目观察（{period_key} #{item.rank}）",
            "",
            f"- 项目：{item.repo_full_name}",
            f"- 作者：{item.owner}",
            f"- {star_label}：{item.stars_this_week}",
            f"- 项目链接：{item.repo_url}",
            f"- 项目简介：{description}",
        ]
        if enrichment_payload:
            lines.extend(["", self._build_enrichment_section(item, enrichment_payload)])
        return "\n".join(lines).strip()

    def _digest_material_content(self, week_key: str, items: list[TrendingItemPayload]) -> str:
        rows = [
            "| 排名 | 项目 | 作者 | 本周新增Star | 简介 | 链接 |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
        sorted_items = sorted(
            items,
            key=lambda it: (it.stars_this_week, -it.rank),
            reverse=True,
        )
        for display_rank, item in enumerate(sorted_items, start=1):
            rows.append(
                "| {rank} | {project} | {owner} | {stars} | {desc} | {url} |".format(
                    rank=display_rank,
                    project=self._escape_md_cell(item.repo_full_name),
                    owner=self._escape_md_cell(item.owner),
                    stars=item.stars_this_week,
                    desc=self._escape_md_cell(
                        item.description_zh or item.description or "暂无简介"
                    ),
                    url=item.repo_url,
                )
            )
        rows.extend(
            [
                "",
                "## 本周观察（可补充）",
                "- 哪些方向最值得跟进？",
                "- 适合做成什么类型的内容？",
                "",
                "## 改写提示（可补充）",
                "- 面向小白解释核心价值",
                "- 给出具体上手路径和注意事项",
            ]
        )
        return "\n".join(rows).strip()

    def add_item_to_materials(
        self,
        week_key: Optional[str],
        repo_full_name: str,
        enhance: bool = True,
        *,
        period_type: str = "weekly",
        period_key: Optional[str] = None,
    ) -> dict:
        mode = self._normalize_period_type(period_type)
        resolved_period_key = self._normalize_period_key(mode, period_key or week_key)
        period_label = "周榜" if mode == "weekly" else "日榜"
        with obs_scope(
            "SVC.GITHUB_TRENDS.ADD_ITEM",
            "WORKFLOW_NODE",
            entities={"week_key": week_key, "period_type": mode, "period_key": resolved_period_key},
        ):
            item = self._find_period_item(mode, resolved_period_key, repo_full_name)
            enrichment_payload, enrich_meta = self._get_repo_enrichment(
                repo_full_name=item.repo_full_name,
                enhance=enhance,
            )

            with Session(engine) as session:
                existing = session.exec(
                    select(Material).where(
                        Material.source_url == item.repo_url,
                        Material.tags.is_not(None),
                        Material.tags.like("%github-trending%"),
                        Material.tags.like(f"%{resolved_period_key}%"),
                    )
                ).first()

            if existing:
                updated = False
                if enrichment_payload:
                    expected_section = self._build_enrichment_section(
                        item,
                        enrichment_payload,
                    )
                    has_expected_section = expected_section in (existing.content or "")
                    should_upgrade_existing = (
                        not self._has_enrichment_section(existing.content)
                        or not has_expected_section
                        or self._has_legacy_material_scaffolding(existing.content or "")
                    )
                else:
                    expected_section = ""
                    should_upgrade_existing = False

                if enrichment_payload and should_upgrade_existing:
                    updated_content = self._upsert_enrichment_section_in_content(
                        content=existing.content or "",
                        section_text=expected_section,
                    )
                    self.material_service.update_material(
                        material_id=existing.id,
                        title=existing.title,
                        content=updated_content,
                        tags=existing.tags,
                        source_url=existing.source_url,
                    )
                    updated = True
                bind_entities(
                    {
                        "material_id": existing.id,
                        "week_key": resolved_period_key,
                        "period_type": mode,
                        "period_key": resolved_period_key,
                    }
                )
                emit_obs_event(
                    level="INFO",
                    message="svc.github_trends.add_item.existing",
                    entities={
                        "material_id": existing.id,
                        "week_key": resolved_period_key,
                        "period_type": mode,
                        "period_key": resolved_period_key,
                    },
                    payload={"updated": updated},
                )
                return {
                    "material_id": existing.id,
                    "created": False,
                    "updated": updated,
                    "period_type": mode,
                    "period_key": resolved_period_key,
                    "enrich": enrich_meta.to_dict(),
                }

            title = f"[GitHub{period_label} {resolved_period_key} #{item.rank}] {item.repo_full_name}"
            tags = f"github-trending,{period_label},{resolved_period_key}"
            content = self._single_material_content(
                resolved_period_key,
                item,
                enrichment_payload=enrichment_payload,
                period_type=mode,
            )

            material = self.material_service.create_material(
                title=title,
                content=content,
                tags=tags,
                source_url=item.repo_url,
            )
            bind_entities(
                {
                    "material_id": material.id,
                    "week_key": resolved_period_key,
                    "period_type": mode,
                    "period_key": resolved_period_key,
                }
            )
            emit_obs_event(
                level="INFO",
                message="svc.github_trends.add_item.created",
                entities={
                    "material_id": material.id,
                    "week_key": resolved_period_key,
                    "period_type": mode,
                    "period_key": resolved_period_key,
                },
            )
            return {
                "material_id": material.id,
                "created": True,
                "updated": False,
                "period_type": mode,
                "period_key": resolved_period_key,
                "enrich": enrich_meta.to_dict(),
            }

    def add_week_digest_to_materials(self, week_key: str) -> dict:
        with obs_scope(
            "SVC.GITHUB_TRENDS.ADD_WEEK_DIGEST",
            "WORKFLOW_NODE",
            entities={"week_key": week_key},
        ):
            normalized_week = self._normalize_week_key(week_key)
            snapshot = self._latest_success_snapshot_for_week(normalized_week)
            if snapshot is None:
                raise ValueError(f"周榜数据不存在: {normalized_week}")

            with Session(engine) as session:
                rows = session.exec(
                    select(GitHubTrendingItem)
                    .where(GitHubTrendingItem.snapshot_id == snapshot.id)
                    .order_by(GitHubTrendingItem.rank)
                ).all()

            items = [
                TrendingItemPayload(
                    rank=row.rank,
                    repo_full_name=row.repo_full_name,
                    repo_name=row.repo_name,
                    owner=row.owner,
                    description=row.description or "",
                    description_zh=row.description_zh or None,
                    repo_url=row.repo_url,
                    stars_this_week=row.stars_this_week,
                    language=row.language,
                    total_stars=row.total_stars,
                )
                for row in rows
            ]
            if not items:
                raise ValueError(f"周榜数据为空: {normalized_week}")

            title = f"GitHub 周榜 Top10（{normalized_week}）"
            tags = f"github-trending,周榜,{normalized_week}"

            with Session(engine) as session:
                existing = session.exec(
                    select(Material).where(
                        Material.title == title,
                        Material.tags.is_not(None),
                        Material.tags.like("%github-trending%"),
                        Material.tags.like(f"%{normalized_week}%"),
                    )
                ).first()
            if existing:
                bind_entities({"material_id": existing.id, "week_key": normalized_week})
                emit_obs_event(
                    level="INFO",
                    message="svc.github_trends.add_week_digest.existing",
                    entities={"material_id": existing.id, "week_key": normalized_week},
                )
                return {"material_id": existing.id, "created": False}

            content = self._digest_material_content(normalized_week, items)
            material = self.material_service.create_material(
                title=title,
                content=content,
                tags=tags,
                source_url=TRENDING_SOURCE_URL,
            )
            bind_entities({"material_id": material.id, "week_key": normalized_week})
            emit_obs_event(
                level="INFO",
                message="svc.github_trends.add_week_digest.created",
                entities={"material_id": material.id, "week_key": normalized_week},
            )
            return {"material_id": material.id, "created": True}

    def build_item_rewrite_markdown(
        self,
        week_key: Optional[str],
        repo_full_name: str,
        enhance: bool = True,
        *,
        period_type: str = "weekly",
        period_key: Optional[str] = None,
    ) -> dict:
        mode = self._normalize_period_type(period_type)
        resolved_period_key = self._normalize_period_key(mode, period_key or week_key)
        with obs_scope(
            "SVC.GITHUB_TRENDS.BUILD_REWRITE",
            "WORKFLOW_NODE",
            entities={"week_key": week_key, "period_type": mode, "period_key": resolved_period_key},
        ):
            item = self._find_period_item(mode, resolved_period_key, repo_full_name)
            enrichment_payload, enrich_meta = self._get_repo_enrichment(
                repo_full_name=item.repo_full_name,
                enhance=enhance,
            )
            if enrichment_payload:
                structured_summary = self._build_rewrite_structured_summary(
                    item,
                    enrichment_payload,
                )
                content = "\n".join(
                    [
                        self._single_material_content(
                            resolved_period_key,
                            item,
                            enrichment_payload=enrichment_payload,
                            period_type=mode,
                        ),
                        "",
                        "## 仓库增强速览（结构化）",
                        structured_summary,
                    ]
                ).strip()
            else:
                content = self._single_material_content(
                    resolved_period_key,
                    item,
                    period_type=mode,
                )

            emit_obs_event(
                level="INFO",
                message="svc.github_trends.build_rewrite",
                entities={
                    "week_key": resolved_period_key,
                    "period_type": mode,
                    "period_key": resolved_period_key,
                },
                payload={"repo_full_name": item.repo_full_name, "enhance": enhance},
            )
            title_scope = "周榜" if mode == "weekly" else "日榜"
            return {
                "title": f"{item.repo_full_name}（{title_scope} {resolved_period_key}）",
                "content": content,
                "period_type": mode,
                "period_key": resolved_period_key,
                "enrich": enrich_meta.to_dict(),
            }

    def build_week_digest_rewrite_markdown(self, week_key: str) -> dict:
        normalized_week = self._normalize_week_key(week_key)
        snapshot = self._latest_success_snapshot_for_week(normalized_week)
        if snapshot is None:
            raise ValueError(f"周榜数据不存在: {normalized_week}")

        with Session(engine) as session:
            rows = session.exec(
                select(GitHubTrendingItem)
                .where(GitHubTrendingItem.snapshot_id == snapshot.id)
                .order_by(GitHubTrendingItem.rank)
            ).all()

        items = [
            TrendingItemPayload(
                rank=row.rank,
                repo_full_name=row.repo_full_name,
                repo_name=row.repo_name,
                owner=row.owner,
                description=row.description or "",
                description_zh=row.description_zh or None,
                repo_url=row.repo_url,
                stars_this_week=row.stars_this_week,
                language=row.language,
                total_stars=row.total_stars,
            )
            for row in rows
        ]
        return {
            "title": f"GitHub 周榜 Top10（{normalized_week}）",
            "content": self._digest_material_content(normalized_week, items),
        }


_github_trending_service: Optional[GitHubTrendingService] = None


def get_github_trending_service() -> GitHubTrendingService:
    global _github_trending_service
    if _github_trending_service is None:
        _github_trending_service = GitHubTrendingService()
    return _github_trending_service
