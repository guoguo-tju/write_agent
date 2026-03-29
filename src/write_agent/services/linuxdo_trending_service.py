"""
Linux.do 趋势服务。
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from sqlalchemy import delete, desc
from sqlmodel import SQLModel, Session, create_engine, select

from write_agent.core import get_logger, get_settings
from write_agent.models import LinuxDoTrendingItem, LinuxDoTrendingSnapshot, Material
from write_agent.observability import bind_entities, emit_obs_event, obs_scope
from write_agent.services.material_service import get_material_service

logger = get_logger(__name__)
settings = get_settings()
engine = create_engine(settings.database_url, echo=False)

TOPIC_WEEK_KEY_PATTERN = re.compile(r"^\d{4}-W\d{2}$")
TOPIC_MONTH_KEY_PATTERN = re.compile(r"^\d{4}-\d{2}$")
SUPPORTED_PERIOD_TYPES = {"weekly", "monthly"}
SUMMARY_LIMIT = 500
SUMMARY_LLM_SOURCE_MAX = 6000
TOPIC_URL_PATTERN = re.compile(r"/t/(?:[^/]+/)?(\d+)(?:$|[/?#])")
RSS_POSTS_COUNT_PATTERN = re.compile(r"(\d+)\s*(?:个帖子|posts?)", re.IGNORECASE)


class RefreshInProgressError(RuntimeError):
    """刷新任务正在执行。"""


class RefreshCoolingDownError(RuntimeError):
    """刷新命中冷却窗口。"""

    def __init__(self, retry_after_seconds: int):
        super().__init__(f"Linux.do 趋势刷新冷却中，请 {retry_after_seconds}s 后重试")
        self.retry_after_seconds = retry_after_seconds


class RefreshRateLimitedError(RuntimeError):
    """上游返回 429 限流。"""

    def __init__(self, retry_after_seconds: int):
        super().__init__(f"Linux.do 上游限流，请 {retry_after_seconds}s 后重试")
        self.retry_after_seconds = retry_after_seconds


@dataclass
class LinuxDoTopicPayload:
    rank: int
    topic_id: int
    title: str
    content_summary: str
    author: str
    tags: list[str]
    reply_count: int
    view_count: int
    like_count: int
    publish_time: str
    topic_url: str


@dataclass
class LinuxDoRssSeed:
    rank: int
    topic_id: int
    title: str
    description_html: str
    author: str
    tags: list[str]
    publish_time: str
    topic_url: str
    posts_count: int


@dataclass
class LinuxDoTopicEnrichment:
    topic_id: int
    title: str
    slug: str
    content: str
    author: str
    tags: list[str]
    views: int
    like_count: int
    posts_count: int
    publish_time: str
    topic_url: str


class LinuxDoTrendingService:
    """Linux.do 趋势抓取、快照、入素材与改写预填。"""

    def __init__(self) -> None:
        self.timezone = ZoneInfo(settings.linuxdo_trending_timezone)
        self.base_url = settings.linuxdo_base_url.strip().rstrip("/") or "https://linux.do"
        self.timeout_seconds = max(3.0, float(settings.linuxdo_trending_timeout_seconds))
        self.default_limit = max(1, int(settings.linuxdo_trending_default_limit))
        self.refresh_cooldown_seconds = max(0.0, float(settings.linuxdo_refresh_cooldown_seconds))
        self.rss_429_retries = max(0, int(settings.linuxdo_rss_429_retries))
        self.rss_429_default_retry_after_seconds = max(
            1.0,
            float(settings.linuxdo_rss_429_default_retry_after_seconds),
        )
        self.rss_429_jitter_seconds = max(0.0, float(settings.linuxdo_rss_429_jitter_seconds))
        self.summary_use_llm = bool(settings.linuxdo_summary_use_llm)
        self.summary_llm_trigger_chars = max(200, int(settings.linuxdo_summary_llm_trigger_chars))
        self.summary_llm_timeout_seconds = max(
            3.0,
            float(settings.linuxdo_summary_llm_timeout_seconds),
        )
        self._refresh_locks = {
            "weekly": asyncio.Lock(),
            "monthly": asyncio.Lock(),
        }
        self._next_allowed_refresh_at = {
            "weekly": 0.0,
            "monthly": 0.0,
        }
        self.material_service = get_material_service()
        SQLModel.metadata.create_all(
            engine,
            tables=[LinuxDoTrendingSnapshot.__table__, LinuxDoTrendingItem.__table__],
        )

    @staticmethod
    def _normalize_period_type(period_type: str) -> str:
        normalized = (period_type or "weekly").strip().lower()
        if normalized not in SUPPORTED_PERIOD_TYPES:
            raise ValueError("period_type 仅支持 weekly/monthly")
        return normalized

    @staticmethod
    def _normalize_week_key(period_key: str) -> str:
        normalized = (period_key or "").strip()
        if not TOPIC_WEEK_KEY_PATTERN.match(normalized):
            raise ValueError("weekly 的 period_key 格式无效，应为 YYYY-Www")
        return normalized

    @staticmethod
    def _normalize_month_key(period_key: str) -> str:
        normalized = (period_key or "").strip()
        if not TOPIC_MONTH_KEY_PATTERN.match(normalized):
            raise ValueError("monthly 的 period_key 格式无效，应为 YYYY-MM")
        return normalized

    @staticmethod
    def _normalize_int(value: object) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    @staticmethod
    def _clean_text(raw: str) -> str:
        text = (raw or "").replace("\u00a0", " ").strip()
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _safe_tags(raw_tags: object) -> list[str]:
        if not isinstance(raw_tags, list):
            return []
        tags: list[str] = []
        for item in raw_tags:
            value = str(item or "").strip()
            if value:
                tags.append(value)
        return tags

    def period_key_for(self, period_type: str, value: date) -> str:
        normalized = self._normalize_period_type(period_type)
        if normalized == "weekly":
            year, week, _ = value.isocalendar()
            return f"{year}-W{week:02d}"
        return f"{value.year}-{value.month:02d}"

    def current_period_key(self, period_type: str) -> str:
        return self.period_key_for(period_type, datetime.now(self.timezone).date())

    def _normalize_period_key(self, period_type: str, period_key: str) -> str:
        normalized_type = self._normalize_period_type(period_type)
        if normalized_type == "weekly":
            return self._normalize_week_key(period_key)
        return self._normalize_month_key(period_key)

    def _top_rss_url_for_period(self, period_type: str) -> str:
        normalized = self._normalize_period_type(period_type)
        return f"{self.base_url}/top.rss?period={normalized}"

    @staticmethod
    def _topic_url(base_url: str, topic_id: int, slug: str) -> str:
        safe_slug = (slug or "topic").strip() or "topic"
        return f"{base_url}/t/{safe_slug}/{topic_id}"

    @staticmethod
    def _topic_json_url(base_url: str, topic_id: int) -> str:
        return f"{base_url}/t/{topic_id}.json"

    @staticmethod
    def _extract_topic_id_from_url(url: str) -> int:
        matched = TOPIC_URL_PATTERN.search(url or "")
        if not matched:
            return 0
        return int(matched.group(1))

    @staticmethod
    def _extract_posts_count_from_html(description_html: str) -> int:
        plain = BeautifulSoup(description_html or "", "html.parser").get_text(" ")
        matched = RSS_POSTS_COUNT_PATTERN.search(plain or "")
        if not matched:
            return 0
        try:
            return int(matched.group(1))
        except Exception:
            return 0

    def _parse_pub_date_to_iso(self, raw: str) -> str:
        value = (raw or "").strip()
        if not value:
            return ""
        try:
            parsed = parsedate_to_datetime(value)
            if parsed is None:
                return value
            return parsed.isoformat()
        except Exception:
            return value

    @staticmethod
    def _parse_retry_after_seconds(raw_retry_after: str) -> Optional[float]:
        text = str(raw_retry_after or "").strip()
        if not text:
            return None
        try:
            return max(float(text), 0.0)
        except Exception:
            pass
        try:
            parsed = parsedate_to_datetime(text)
            if parsed is None:
                return None
            now = datetime.now(parsed.tzinfo or ZoneInfo("UTC"))
            return max((parsed - now).total_seconds(), 0.0)
        except Exception:
            return None

    def _set_refresh_cooldown(self, period_type: str, seconds: float) -> None:
        normalized = self._normalize_period_type(period_type)
        if seconds <= 0:
            return
        target = time.monotonic() + seconds
        self._next_allowed_refresh_at[normalized] = max(
            self._next_allowed_refresh_at[normalized],
            target,
        )

    def _remaining_cooldown_seconds(self, period_type: str) -> int:
        normalized = self._normalize_period_type(period_type)
        remaining = self._next_allowed_refresh_at[normalized] - time.monotonic()
        if remaining <= 0:
            return 0
        return int(math.ceil(remaining))

    def _default_headers(self, accept: str) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": accept,
            "Referer": f"{self.base_url}/",
        }

    def _build_summary(self, excerpt: str) -> str:
        text = self._clean_text(BeautifulSoup(excerpt or "", "html.parser").get_text(" "))
        if len(text) <= SUMMARY_LIMIT:
            return text
        # 简单摘要：优先按句号截断，再回退硬截断。
        sentence_end = max(text.rfind("。", 0, SUMMARY_LIMIT), text.rfind(".", 0, SUMMARY_LIMIT))
        if sentence_end > 80:
            return text[: sentence_end + 1]
        return text[:SUMMARY_LIMIT].rstrip()

    @staticmethod
    def _truncate_summary_text(text: str, limit: int = SUMMARY_LIMIT) -> str:
        if len(text) <= limit:
            return text
        sentence_end = max(
            text.rfind("。", 0, limit),
            text.rfind(".", 0, limit),
            text.rfind("\n", 0, limit),
        )
        if sentence_end > 80:
            return text[: sentence_end + 1].rstrip()
        return text[:limit].rstrip()

    @staticmethod
    def _normalize_summary_output(raw: str) -> str:
        lines: list[str] = []
        for line in str(raw or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines).strip()

    def _summarize_with_llm(self, source_text: str, topic_id: int) -> Optional[str]:
        input_length = len(source_text)
        emit_obs_event(
            level="INFO",
            message="svc.linuxdo_trends.summary.llm.start",
            entities={"topic_id": topic_id},
            payload={
                "input_length": input_length,
                "trigger_chars": self.summary_llm_trigger_chars,
            },
        )
        api_key = (settings.openai_api_key or "").strip()
        model = (settings.openai_model or "").strip()
        if not api_key or not model:
            emit_obs_event(
                level="WARNING",
                message="svc.linuxdo_trends.summary.llm.fallback",
                entities={"topic_id": topic_id},
                payload={"reason": "missing_openai_config"},
            )
            return None

        base_url = (settings.openai_base_url or "").strip().rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        request_kwargs = {
            "url": f"{base_url}/chat/completions",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            "json": {
                "model": model,
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是中文科技社区编辑，擅长把长文本压缩为可读性高的短摘要。",
                    },
                    {
                        "role": "user",
                        "content": (
                            "请对下面社区帖子做中文摘要，输出格式必须严格为：\n"
                            "1）先写一段2-3句的精炼短文概述核心信息；\n"
                            "2）再写“要点：”并列出3条要点（每条尽量不超过30字）。\n"
                            "总长度必须不超过500字。\n"
                            "不要输出与原文无关的信息。\n\n"
                            f"帖子内容：\n{source_text[:SUMMARY_LLM_SOURCE_MAX]}"
                        ),
                    },
                ],
            },
            "timeout": self.summary_llm_timeout_seconds,
        }
        started = time.monotonic()
        try:
            parsed = urlparse(base_url)
            if parsed.hostname in {"127.0.0.1", "localhost"}:
                with requests.Session() as session:
                    session.trust_env = False
                    response = session.post(**request_kwargs)
            else:
                response = requests.post(**request_kwargs)
            response.raise_for_status()
            llm_response = (
                response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            )
            normalized = self._normalize_summary_output(str(llm_response))
            if not normalized:
                emit_obs_event(
                    level="WARNING",
                    message="svc.linuxdo_trends.summary.llm.fallback",
                    entities={"topic_id": topic_id},
                    payload={"reason": "empty_llm_output"},
                )
                return None
            summary = self._truncate_summary_text(normalized)
            emit_obs_event(
                level="INFO",
                message="svc.linuxdo_trends.summary.llm.done",
                entities={"topic_id": topic_id},
                payload={
                    "input_length": input_length,
                    "output_length": len(summary),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
            return summary
        except requests.Timeout:
            emit_obs_event(
                level="WARNING",
                message="svc.linuxdo_trends.summary.llm.fallback",
                entities={"topic_id": topic_id},
                payload={"reason": "llm_timeout"},
            )
            return None
        except Exception as error:
            logger.warning("Linux.do 智能摘要回退 topic_id=%s: %s", topic_id, error)
            emit_obs_event(
                level="WARNING",
                message="svc.linuxdo_trends.summary.llm.fallback",
                entities={"topic_id": topic_id},
                payload={"reason": "llm_error", "error": str(error)},
            )
            return None

    def _build_topic_summary(
        self,
        *,
        topic_id: int,
        primary_text: str,
        fallback_text: str,
        allow_llm: bool = True,
    ) -> str:
        primary_plain = self._clean_text(BeautifulSoup(primary_text or "", "html.parser").get_text(" "))
        fallback_plain = self._clean_text(BeautifulSoup(fallback_text or "", "html.parser").get_text(" "))
        source_text = primary_plain or fallback_plain
        if not source_text:
            return ""
        if len(source_text) <= self.summary_llm_trigger_chars or not self.summary_use_llm or not allow_llm:
            return self._build_summary(source_text)
        llm_summary = self._summarize_with_llm(source_text, topic_id=topic_id)
        if llm_summary:
            return llm_summary
        return self._build_summary(source_text)

    def _fetch_rss_seeds(self, period_type: str) -> list[LinuxDoRssSeed]:
        url = self._top_rss_url_for_period(period_type)
        emit_obs_event(
            level="INFO",
            message="svc.linuxdo_trends.rss.fetch.start",
            payload={"period_type": period_type, "url": url},
        )
        response: requests.Response | None = None
        for attempt in range(self.rss_429_retries + 1):
            response = requests.get(
                url,
                headers=self._default_headers("application/rss+xml,application/xml,text/xml,*/*"),
                timeout=self.timeout_seconds,
            )
            try:
                response.raise_for_status()
                break
            except requests.HTTPError as error:
                status_code = getattr(error.response, "status_code", None)
                if status_code == 403:
                    raise RuntimeError(
                        "linux.do RSS 返回 403（Cloudflare challenge），当前环境无法直接抓取"
                    ) from error
                if status_code != 429:
                    raise
                retry_after = self._parse_retry_after_seconds(
                    str(getattr(error.response, "headers", {}).get("Retry-After", "")),
                )
                if retry_after is None:
                    retry_after = self.rss_429_default_retry_after_seconds * (attempt + 1)
                retry_after = max(1.0, retry_after)
                if attempt >= self.rss_429_retries:
                    self._set_refresh_cooldown(period_type, retry_after)
                    emit_obs_event(
                        level="WARNING",
                        message="svc.linuxdo_trends.rss.fetch.429.giveup",
                        entities={"period_type": period_type},
                        payload={
                            "attempt": attempt + 1,
                            "retry_after": retry_after,
                        },
                    )
                    raise RefreshRateLimitedError(int(math.ceil(retry_after))) from error
                sleep_seconds = retry_after + random.uniform(0.0, self.rss_429_jitter_seconds)
                emit_obs_event(
                    level="WARNING",
                    message="svc.linuxdo_trends.rss.fetch.429.retry",
                    entities={"period_type": period_type},
                    payload={
                        "attempt": attempt + 1,
                        "retry_after": retry_after,
                        "sleep_seconds": sleep_seconds,
                    },
                )
                time.sleep(sleep_seconds)
                continue
        if response is None:
            raise RuntimeError("linux.do RSS 请求失败：未获得响应")

        try:
            root = ElementTree.fromstring(response.text or "")
        except Exception as error:
            raise RuntimeError(f"linux.do RSS 解析失败: {error}") from error

        channel = root.find("channel")
        if channel is None:
            raise RuntimeError("linux.do RSS 缺少 channel 节点")

        rows: list[LinuxDoRssSeed] = []
        for index, item in enumerate(channel.findall("item")):
            title = self._clean_text(item.findtext("title", default=""))
            topic_url = self._clean_text(item.findtext("link", default=""))
            if not title or not topic_url:
                continue
            topic_id = self._extract_topic_id_from_url(topic_url)
            if topic_id <= 0:
                continue
            description_html = str(item.findtext("description", default="") or "")
            category = self._clean_text(item.findtext("category", default=""))
            creator = self._clean_text(
                item.findtext("{http://purl.org/dc/elements/1.1/}creator", default="")
            )
            posts_count = self._extract_posts_count_from_html(description_html)
            rows.append(
                LinuxDoRssSeed(
                    rank=index + 1,
                    topic_id=topic_id,
                    title=title,
                    description_html=description_html,
                    author=creator or "unknown",
                    tags=[category] if category else [],
                    publish_time=self._parse_pub_date_to_iso(item.findtext("pubDate", default="")),
                    topic_url=topic_url,
                    posts_count=posts_count,
                )
            )

        emit_obs_event(
            level="INFO",
            message="svc.linuxdo_trends.rss.fetch.done",
            payload={"period_type": period_type, "count": len(rows)},
        )
        return rows

    def _fetch_topic_enrichment(self, topic_id: int) -> LinuxDoTopicEnrichment:
        topic_url = self._topic_json_url(self.base_url, topic_id)
        response = requests.get(
            topic_url,
            headers=self._default_headers("application/json,text/plain,*/*"),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()

        first_post = ((payload.get("post_stream") or {}).get("posts") or [{}])[0]
        raw_tags = payload.get("tags") or []
        tags: list[str] = []
        for tag in raw_tags:
            if isinstance(tag, str):
                value = tag.strip()
            elif isinstance(tag, dict):
                value = str(tag.get("name") or tag.get("slug") or "").strip()
            else:
                value = ""
            if value:
                tags.append(value)

        content = str(first_post.get("cooked") or "") or str(first_post.get("raw") or "")
        author = (
            self._clean_text(str(first_post.get("username") or ""))
            or self._clean_text(str((payload.get("details") or {}).get("created_by", {}).get("username") or ""))
            or "unknown"
        )
        slug = self._clean_text(str(payload.get("slug") or "topic")) or "topic"
        publish_time = self._clean_text(
            str(payload.get("created_at") or first_post.get("created_at") or "")
        )
        return LinuxDoTopicEnrichment(
            topic_id=topic_id,
            title=self._clean_text(str(payload.get("title") or "")),
            slug=slug,
            content=content,
            author=author,
            tags=tags,
            views=self._normalize_int(payload.get("views")),
            like_count=self._normalize_int(payload.get("like_count")),
            posts_count=self._normalize_int(payload.get("posts_count")),
            publish_time=publish_time,
            topic_url=self._topic_url(self.base_url, topic_id, slug),
        )

    def _fetch_topics(self, period_type: str) -> list[LinuxDoTopicPayload]:
        seeds = self._fetch_rss_seeds(period_type)[: self.default_limit]
        rows: list[LinuxDoTopicPayload] = []
        partial_failed = 0
        for seed in seeds:
            payload = LinuxDoTopicPayload(
                rank=seed.rank,
                topic_id=seed.topic_id,
                title=seed.title,
                content_summary="",
                author=seed.author,
                tags=seed.tags,
                reply_count=max(seed.posts_count - 1, 0),
                view_count=0,
                like_count=0,
                publish_time=seed.publish_time,
                topic_url=seed.topic_url,
            )
            try:
                enrichment = self._fetch_topic_enrichment(seed.topic_id)
                payload.content_summary = self._build_topic_summary(
                    topic_id=seed.topic_id,
                    primary_text=enrichment.content,
                    fallback_text=seed.description_html,
                )
                payload.author = enrichment.author or payload.author
                payload.tags = enrichment.tags or payload.tags
                payload.reply_count = max(enrichment.posts_count - 1, payload.reply_count, 0)
                payload.view_count = enrichment.views
                payload.like_count = enrichment.like_count
                payload.publish_time = enrichment.publish_time or payload.publish_time
                payload.topic_url = enrichment.topic_url or payload.topic_url
                emit_obs_event(
                    level="INFO",
                    message="svc.linuxdo_trends.topic.enrich.success",
                    entities={"topic_id": seed.topic_id},
                )
            except Exception as error:
                partial_failed += 1
                payload.content_summary = self._build_topic_summary(
                    topic_id=seed.topic_id,
                    primary_text="",
                    fallback_text=seed.description_html,
                    allow_llm=False,
                )
                logger.warning("Linux.do topic 明细补全失败 topic_id=%s: %s", seed.topic_id, error)
                emit_obs_event(
                    level="WARNING",
                    message="svc.linuxdo_trends.topic.enrich.failed",
                    entities={"topic_id": seed.topic_id},
                    payload={"error": str(error)},
                )
            if not payload.content_summary:
                payload.content_summary = self._build_summary(seed.description_html) or seed.title
            rows.append(payload)

        emit_obs_event(
            level="INFO",
            message="svc.linuxdo_trends.partial_success_count",
            payload={"period_type": period_type, "total": len(rows), "failed": partial_failed},
        )
        return rows

    def _upsert_failed_snapshot(
        self,
        period_type: str,
        period_key: str,
        snapshot_date: date,
        error_message: str,
    ) -> None:
        now = datetime.now(self.timezone)
        with Session(engine) as session:
            snapshot = session.exec(
                select(LinuxDoTrendingSnapshot).where(
                    LinuxDoTrendingSnapshot.period_type == period_type,
                    LinuxDoTrendingSnapshot.period_key == period_key,
                    LinuxDoTrendingSnapshot.snapshot_date == snapshot_date,
                )
            ).first()
            if snapshot is None:
                snapshot = LinuxDoTrendingSnapshot(
                    period_type=period_type,
                    period_key=period_key,
                    snapshot_date=snapshot_date,
                )
                session.add(snapshot)
            snapshot.captured_at = now
            snapshot.fetch_status = "failed"
            snapshot.fetch_error = (error_message or "")[:500]
            session.commit()

    def _save_success_snapshot(
        self,
        period_type: str,
        period_key: str,
        snapshot_date: date,
        items: list[LinuxDoTopicPayload],
    ) -> LinuxDoTrendingSnapshot:
        now = datetime.now(self.timezone)
        with Session(engine) as session:
            snapshot = session.exec(
                select(LinuxDoTrendingSnapshot).where(
                    LinuxDoTrendingSnapshot.period_type == period_type,
                    LinuxDoTrendingSnapshot.period_key == period_key,
                    LinuxDoTrendingSnapshot.snapshot_date == snapshot_date,
                )
            ).first()
            if snapshot is None:
                snapshot = LinuxDoTrendingSnapshot(
                    period_type=period_type,
                    period_key=period_key,
                    snapshot_date=snapshot_date,
                )
                session.add(snapshot)
                session.flush()
            snapshot.captured_at = now
            snapshot.fetch_status = "success"
            snapshot.fetch_error = None

            session.exec(delete(LinuxDoTrendingItem).where(LinuxDoTrendingItem.snapshot_id == snapshot.id))
            for item in items:
                session.add(
                    LinuxDoTrendingItem(
                        snapshot_id=snapshot.id,
                        rank=item.rank,
                        topic_id=item.topic_id,
                        title=item.title,
                        content_summary=item.content_summary,
                        author=item.author,
                        tags_json=json.dumps(item.tags, ensure_ascii=False),
                        reply_count=item.reply_count,
                        view_count=item.view_count,
                        like_count=item.like_count,
                        publish_time=item.publish_time,
                        topic_url=item.topic_url,
                    )
                )
            session.commit()
            session.refresh(snapshot)
            return snapshot

    def _fetch_and_persist(
        self,
        period_type: str,
        now_dt: Optional[datetime] = None,
    ) -> LinuxDoTrendingSnapshot:
        normalized = self._normalize_period_type(period_type)
        now = now_dt or datetime.now(self.timezone)
        period_key = self.period_key_for(normalized, now.date())
        snapshot_date = now.date()

        try:
            items = self._fetch_topics(normalized)
        except Exception as error:
            logger.error("抓取 Linux.do 趋势失败: %s", error, exc_info=True)
            self._upsert_failed_snapshot(normalized, period_key, snapshot_date, str(error))
            raise

        return self._save_success_snapshot(normalized, period_key, snapshot_date, items)

    async def refresh_snapshot(
        self,
        period_type: str = "weekly",
        now_dt: Optional[datetime] = None,
    ) -> LinuxDoTrendingSnapshot:
        normalized = self._normalize_period_type(period_type)
        with obs_scope(
            "SVC.LINUXDO_TRENDS.REFRESH",
            "WORKFLOW_NODE",
            entities={"period_type": normalized},
        ):
            cooldown = self._remaining_cooldown_seconds(normalized)
            if cooldown > 0:
                emit_obs_event(
                    level="WARNING",
                    message="svc.linuxdo_trends.refresh.cooldown.hit",
                    entities={"period_type": normalized},
                    payload={"retry_after": cooldown},
                )
                raise RefreshCoolingDownError(cooldown)
            lock = self._refresh_locks[normalized]
            if lock.locked():
                raise RefreshInProgressError("Linux.do 趋势更新中")

            async with lock:
                cooldown = self._remaining_cooldown_seconds(normalized)
                if cooldown > 0:
                    emit_obs_event(
                        level="WARNING",
                        message="svc.linuxdo_trends.refresh.cooldown.hit",
                        entities={"period_type": normalized},
                        payload={"retry_after": cooldown},
                    )
                    raise RefreshCoolingDownError(cooldown)
                emit_obs_event(
                    level="INFO",
                    message="svc.linuxdo_trends.refresh.start",
                    entities={"period_type": normalized},
                )
                snapshot = await asyncio.to_thread(self._fetch_and_persist, normalized, now_dt)
                bind_entities({"period_key": snapshot.period_key})
                emit_obs_event(
                    level="INFO",
                    message="svc.linuxdo_trends.refresh.done",
                    entities={"period_key": snapshot.period_key, "period_type": normalized},
                    payload={"snapshot_date": snapshot.snapshot_date.isoformat()},
                )
                self._set_refresh_cooldown(normalized, self.refresh_cooldown_seconds)
                return snapshot

    def is_refresh_running(self, period_type: str) -> bool:
        normalized = self._normalize_period_type(period_type)
        return self._refresh_locks[normalized].locked()

    def _latest_success_snapshot_for_period(
        self,
        period_type: str,
        period_key: str,
    ) -> Optional[LinuxDoTrendingSnapshot]:
        with Session(engine) as session:
            return session.exec(
                select(LinuxDoTrendingSnapshot)
                .where(
                    LinuxDoTrendingSnapshot.period_type == period_type,
                    LinuxDoTrendingSnapshot.period_key == period_key,
                    LinuxDoTrendingSnapshot.fetch_status == "success",
                )
                .order_by(desc(LinuxDoTrendingSnapshot.captured_at))
            ).first()

    def _latest_success_snapshot_global(self, period_type: str) -> Optional[LinuxDoTrendingSnapshot]:
        with Session(engine) as session:
            return session.exec(
                select(LinuxDoTrendingSnapshot)
                .where(
                    LinuxDoTrendingSnapshot.period_type == period_type,
                    LinuxDoTrendingSnapshot.fetch_status == "success",
                )
                .order_by(desc(LinuxDoTrendingSnapshot.captured_at))
            ).first()

    def _latest_failed_for_period(
        self,
        period_type: str,
        period_key: str,
    ) -> Optional[LinuxDoTrendingSnapshot]:
        with Session(engine) as session:
            return session.exec(
                select(LinuxDoTrendingSnapshot)
                .where(
                    LinuxDoTrendingSnapshot.period_type == period_type,
                    LinuxDoTrendingSnapshot.period_key == period_key,
                    LinuxDoTrendingSnapshot.fetch_status == "failed",
                )
                .order_by(desc(LinuxDoTrendingSnapshot.captured_at))
            ).first()

    @staticmethod
    def _row_tags(row: LinuxDoTrendingItem) -> list[str]:
        try:
            parsed = json.loads(row.tags_json or "[]")
            if isinstance(parsed, list):
                return [str(tag) for tag in parsed if str(tag).strip()]
        except Exception:
            pass
        return []

    def _snapshot_to_dict(
        self,
        snapshot: LinuxDoTrendingSnapshot,
        requested_period_key: str,
        tag: Optional[str],
        limit: int,
    ) -> dict:
        with Session(engine) as session:
            rows = session.exec(
                select(LinuxDoTrendingItem)
                .where(LinuxDoTrendingItem.snapshot_id == snapshot.id)
                .order_by(LinuxDoTrendingItem.rank)
            ).all()

        normalized_tag = (tag or "").strip()
        all_tags: set[str] = set()
        items = []
        for row in rows:
            tags = self._row_tags(row)
            for item_tag in tags:
                all_tags.add(item_tag)
            if normalized_tag and normalized_tag not in tags:
                continue
            items.append(
                {
                    "rank": row.rank,
                    "topic_id": row.topic_id,
                    "title": row.title,
                    "content": row.content_summary,
                    "author": row.author,
                    "tags": tags,
                    "reply_count": row.reply_count,
                    "view_count": row.view_count,
                    "like_count": row.like_count,
                    "publish_time": row.publish_time,
                    "topic_url": row.topic_url,
                }
            )

        latest_failed = self._latest_failed_for_period(snapshot.period_type, requested_period_key)
        return {
            "period_type": snapshot.period_type,
            "period_key": snapshot.period_key,
            "requested_period_key": requested_period_key,
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "captured_at": snapshot.captured_at.isoformat(),
            "is_stale": snapshot.period_key != requested_period_key,
            "is_refreshing": self.is_refresh_running(snapshot.period_type),
            "fetch_error": latest_failed.fetch_error if latest_failed else None,
            "available_tags": sorted(all_tags),
            "items": items[: max(1, limit)],
        }

    def get_snapshot(
        self,
        period_type: str = "weekly",
        period_key: Optional[str] = None,
        tag: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> dict:
        normalized = self._normalize_period_type(period_type)
        with obs_scope(
            "SVC.LINUXDO_TRENDS.GET",
            "DB_READ",
            entities={"period_type": normalized, "period_key": period_key},
        ):
            target_key = (
                self._normalize_period_key(normalized, period_key)
                if period_key
                else self.current_period_key(normalized)
            )
            snapshot = self._latest_success_snapshot_for_period(normalized, target_key)
            if snapshot is None:
                snapshot = self._latest_success_snapshot_global(normalized)
            if snapshot is None:
                raise ValueError("暂无可用的 Linux.do 趋势快照，请先手动更新")

            emit_obs_event(
                level="INFO",
                message="svc.linuxdo_trends.get_snapshot",
                entities={"period_type": normalized, "period_key": target_key},
            )
            return self._snapshot_to_dict(
                snapshot=snapshot,
                requested_period_key=target_key,
                tag=tag,
                limit=limit or self.default_limit,
            )

    def list_periods(self, period_type: str = "weekly") -> list[dict]:
        normalized = self._normalize_period_type(period_type)
        with obs_scope(
            "SVC.LINUXDO_TRENDS.PERIODS",
            "DB_READ",
            entities={"period_type": normalized},
        ):
            with Session(engine) as session:
                snapshots = session.exec(
                    select(LinuxDoTrendingSnapshot)
                    .where(
                        LinuxDoTrendingSnapshot.period_type == normalized,
                        LinuxDoTrendingSnapshot.fetch_status == "success",
                    )
                    .order_by(desc(LinuxDoTrendingSnapshot.captured_at))
                ).all()

            by_period: dict[str, dict] = {}
            for snapshot in snapshots:
                if snapshot.period_key in by_period:
                    continue
                by_period[snapshot.period_key] = {
                    "period_key": snapshot.period_key,
                    "latest_snapshot_date": snapshot.snapshot_date.isoformat(),
                    "latest_captured_at": snapshot.captured_at.isoformat(),
                }
                if len(by_period) >= 12:
                    break

            ordered = sorted(by_period.values(), key=lambda item: item["period_key"], reverse=True)
            emit_obs_event(
                level="INFO",
                message="svc.linuxdo_trends.list_periods",
                payload={"period_type": normalized, "total": len(ordered)},
            )
            return ordered

    def _find_topic_item(self, period_type: str, period_key: str, topic_id: int) -> LinuxDoTopicPayload:
        normalized_type = self._normalize_period_type(period_type)
        normalized_key = self._normalize_period_key(normalized_type, period_key)
        normalized_topic_id = self._normalize_int(topic_id)
        if normalized_topic_id <= 0:
            raise ValueError("topic_id 无效")

        snapshot = self._latest_success_snapshot_for_period(normalized_type, normalized_key)
        if snapshot is None:
            raise ValueError(f"趋势数据不存在: {normalized_key}")

        with Session(engine) as session:
            row = session.exec(
                select(LinuxDoTrendingItem).where(
                    LinuxDoTrendingItem.snapshot_id == snapshot.id,
                    LinuxDoTrendingItem.topic_id == normalized_topic_id,
                )
            ).first()

        if row is None:
            raise ValueError(f"周期 {normalized_key} 中未找到 topic_id={normalized_topic_id}")

        return LinuxDoTopicPayload(
            rank=row.rank,
            topic_id=row.topic_id,
            title=row.title,
            content_summary=row.content_summary,
            author=row.author or "unknown",
            tags=self._row_tags(row),
            reply_count=row.reply_count,
            view_count=row.view_count,
            like_count=row.like_count,
            publish_time=row.publish_time or "",
            topic_url=row.topic_url,
        )

    def get_topic_detail(self, topic_id: int) -> dict:
        normalized_topic_id = self._normalize_int(topic_id)
        if normalized_topic_id <= 0:
            raise ValueError("topic_id 无效")

        with obs_scope(
            "SVC.LINUXDO_TRENDS.TOPIC_DETAIL",
            "EXTERNAL_HTTP_CALL",
            entities={"topic_id": normalized_topic_id},
        ):
            url = f"{self.base_url}/t/{normalized_topic_id}.json"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/plain,*/*",
                "Referer": f"{self.base_url}/",
            }
            response = requests.get(url, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()

            first_post = ((payload.get("post_stream") or {}).get("posts") or [{}])[0]
            content = self._clean_text(
                BeautifulSoup(str(first_post.get("cooked") or ""), "html.parser").get_text(" ")
            ) or self._clean_text(str(first_post.get("raw") or ""))
            topic_slug = str(payload.get("slug") or "topic")
            topic_title = self._clean_text(str(payload.get("title") or ""))
            detail = {
                "topic_id": normalized_topic_id,
                "title": topic_title,
                "content": content,
                "author": str(first_post.get("username") or "unknown"),
                "publish_time": str(first_post.get("created_at") or ""),
                "topic_url": self._topic_url(self.base_url, normalized_topic_id, topic_slug),
            }
            emit_obs_event(
                level="INFO",
                message="svc.linuxdo_trends.topic_detail",
                entities={"topic_id": normalized_topic_id},
            )
            return detail

    def _single_material_content(
        self,
        period_type: str,
        period_key: str,
        item: LinuxDoTopicPayload,
        detail_text: str,
    ) -> str:
        rows = [
            f"# Linux.do 热帖观察（{period_type}:{period_key} #{item.rank}）",
            "",
            f"- 标题：{item.title}",
            f"- 作者：{item.author}",
            f"- 标签：{', '.join(item.tags) if item.tags else '--'}",
            f"- 回复：{item.reply_count}",
            f"- 浏览：{item.view_count}",
            f"- 点赞：{item.like_count}",
            f"- 发布时间：{item.publish_time or '--'}",
            f"- 原帖链接：{item.topic_url}",
            "",
            "## 帖子内容",
            detail_text or item.content_summary,
        ]
        return "\n".join(rows).strip()

    def _resolve_detail_text_with_fallback(self, item: LinuxDoTopicPayload) -> str:
        try:
            detail = self.get_topic_detail(item.topic_id)
            detail_text = self._clean_text(str(detail.get("content") or ""))
            if detail_text:
                return detail_text
        except Exception as error:
            logger.warning("Linux.do 帖子详情降级 topic_id=%s: %s", item.topic_id, error)
            emit_obs_event(
                level="WARNING",
                message="svc.linuxdo_trends.topic_detail.degraded",
                entities={"topic_id": item.topic_id},
                payload={"error": str(error)},
            )
        return item.content_summary or item.title

    def add_item_to_materials(self, period_type: str, period_key: str, topic_id: int) -> dict:
        normalized_type = self._normalize_period_type(period_type)
        with obs_scope(
            "SVC.LINUXDO_TRENDS.ADD_ITEM",
            "WORKFLOW_NODE",
            entities={"period_type": normalized_type, "period_key": period_key},
        ):
            item = self._find_topic_item(normalized_type, period_key, topic_id)
            detail_text = self._resolve_detail_text_with_fallback(item)
            normalized_key = self._normalize_period_key(normalized_type, period_key)

            with Session(engine) as session:
                existing = session.exec(
                    select(Material).where(
                        Material.source_url == item.topic_url,
                        Material.tags.is_not(None),
                        Material.tags.like("%linuxdo-trending%"),
                        Material.tags.like(f"%{normalized_type}%"),
                        Material.tags.like(f"%{normalized_key}%"),
                    )
                ).first()

            title = f"[Linux.do {normalized_type} {normalized_key} #{item.rank}] {item.title}"
            tags = f"linuxdo-trending,{normalized_type},{normalized_key}"
            content = self._single_material_content(
                normalized_type,
                normalized_key,
                item,
                detail_text=detail_text,
            )

            if existing:
                self.material_service.update_material(
                    material_id=existing.id,
                    title=title,
                    content=content,
                    tags=tags,
                    source_url=item.topic_url,
                )
                bind_entities({"material_id": existing.id})
                emit_obs_event(
                    level="INFO",
                    message="svc.linuxdo_trends.add_item.existing",
                    entities={"material_id": existing.id},
                    payload={"updated": True},
                )
                return {"material_id": existing.id, "created": False, "updated": True}

            material = self.material_service.create_material(
                title=title,
                content=content,
                tags=tags,
                source_url=item.topic_url,
            )
            bind_entities({"material_id": material.id})
            emit_obs_event(
                level="INFO",
                message="svc.linuxdo_trends.add_item.created",
                entities={"material_id": material.id},
            )
            return {"material_id": material.id, "created": True, "updated": False}

    def build_item_rewrite_markdown(self, period_type: str, period_key: str, topic_id: int) -> dict:
        normalized_type = self._normalize_period_type(period_type)
        with obs_scope(
            "SVC.LINUXDO_TRENDS.BUILD_REWRITE",
            "WORKFLOW_NODE",
            entities={"period_type": normalized_type, "period_key": period_key},
        ):
            item = self._find_topic_item(normalized_type, period_key, topic_id)
            detail_text = self._resolve_detail_text_with_fallback(item)
            normalized_key = self._normalize_period_key(normalized_type, period_key)
            content = self._single_material_content(
                normalized_type,
                normalized_key,
                item,
                detail_text=detail_text,
            )
            emit_obs_event(
                level="INFO",
                message="svc.linuxdo_trends.build_rewrite",
                entities={"period_type": normalized_type, "period_key": normalized_key},
            )
            return {
                "title": f"Linux.do 热帖 {item.title}",
                "content": content,
            }


_linuxdo_trending_service: Optional[LinuxDoTrendingService] = None


def get_linuxdo_trending_service() -> LinuxDoTrendingService:
    global _linuxdo_trending_service
    if _linuxdo_trending_service is None:
        _linuxdo_trending_service = LinuxDoTrendingService()
    return _linuxdo_trending_service
