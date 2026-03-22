"""
GitHub 趋势服务。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from sqlalchemy import delete, desc, inspect, text, update
from sqlmodel import SQLModel, Session, create_engine, select

from write_agent.core import get_logger, get_settings
from write_agent.models import (
    GitHubTrendingItem,
    GitHubTrendingSnapshot,
    Material,
)
from write_agent.services.material_service import get_material_service

logger = get_logger(__name__)
settings = get_settings()
engine = create_engine(settings.database_url, echo=False)


TRENDING_WEEKLY_URL = "https://github.com/trending?since=weekly"
TRENDING_SOURCE_URL = "https://github.com/trending?since=weekly"
STAR_WEEK_PATTERN = re.compile(r"([\d,]+)\s*stars?\s*this\s*week", re.IGNORECASE)
WEEK_KEY_PATTERN = re.compile(r"^\d{4}-W\d{2}$")


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
            ],
        )
        self._ensure_schema_compat()

    def current_week_key(self) -> str:
        return self.week_key_for_date(datetime.now(self.timezone).date())

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
        return latin_count <= max(12, zh_count * 2)

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

    def _load_week_translation_cache(self, week_key: str) -> dict[str, str]:
        """加载同周已翻译简介，避免重复调用模型。"""
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
                    GitHubTrendingSnapshot.week_key == week_key,
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
            if key and value and self._is_acceptable_zh(value) and key not in mapping:
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
            "timeout": 45,
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
                idx = row.get("index")
                text_val = self._safe_text(str(row.get("translation", "")))
                if isinstance(idx, int) and text_val and self._is_acceptable_zh(text_val):
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
            "timeout": 45,
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

    def _enrich_description_zh(self, week_key: str, items: list[TrendingItemPayload]) -> None:
        cache = self._load_week_translation_cache(week_key)
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
        for batch_index, (item_index, original_text) in enumerate(pending_pairs):
            translated = self._safe_text(translated_map.get(batch_index, ""))
            if translated:
                items[item_index].description_zh = translated
                continue
            items[item_index].description_zh = self._translate_description_to_zh_single(
                original_text
            )

    def _request_headers(self) -> dict:
        headers = {
            "User-Agent": "write-agent/1.0 (+github-trending)",
            "Accept": "text/html,application/xhtml+xml",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        return headers

    def _fetch_trending_top10(self) -> list[TrendingItemPayload]:
        response = requests.get(
            TRENDING_WEEKLY_URL,
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

            match = STAR_WEEK_PATTERN.search(week_text)
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
        with Session(engine) as session:
            snapshot = session.exec(
                select(GitHubTrendingSnapshot).where(
                    GitHubTrendingSnapshot.week_key == week_key,
                    GitHubTrendingSnapshot.snapshot_date == snapshot_date,
                )
            ).first()

            now = datetime.now(self.timezone)
            if snapshot is None:
                snapshot = GitHubTrendingSnapshot(
                    week_key=week_key,
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
        now = datetime.now(self.timezone)
        with Session(engine) as session:
            snapshot = session.exec(
                select(GitHubTrendingSnapshot).where(
                    GitHubTrendingSnapshot.week_key == week_key,
                    GitHubTrendingSnapshot.snapshot_date == snapshot_date,
                )
            ).first()

            if snapshot is None:
                snapshot = GitHubTrendingSnapshot(
                    week_key=week_key,
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

            self._archive_previous_week_if_needed(session, now.date())
            session.commit()
            session.refresh(snapshot)
            return snapshot

    def _fetch_and_persist_current_week(self) -> GitHubTrendingSnapshot:
        now = datetime.now(self.timezone)
        week_key = self.week_key_for_date(now.date())
        snapshot_date = now.date()
        try:
            items = self._fetch_trending_top10()
            self._enrich_description_zh(week_key, items)
        except Exception as error:
            logger.error("抓取 GitHub Trending 失败: %s", error, exc_info=True)
            self._upsert_failed_snapshot(week_key, snapshot_date, str(error))
            raise

        return self._save_success_snapshot(week_key, snapshot_date, items)

    async def refresh_current_week_snapshot(self) -> GitHubTrendingSnapshot:
        if self.refresh_lock.locked():
            raise RefreshInProgressError("GitHub 趋势更新中")

        async with self.refresh_lock:
            return await asyncio.to_thread(self._fetch_and_persist_current_week)

    def is_refresh_running(self) -> bool:
        return self.refresh_lock.locked()

    def _snapshot_to_dict(self, snapshot: GitHubTrendingSnapshot, requested_week_key: str) -> dict:
        with Session(engine) as session:
            items = session.exec(
                select(GitHubTrendingItem)
                .where(GitHubTrendingItem.snapshot_id == snapshot.id)
                .order_by(GitHubTrendingItem.rank)
            ).all()

            latest_failed = session.exec(
                select(GitHubTrendingSnapshot)
                .where(
                    GitHubTrendingSnapshot.week_key == requested_week_key,
                    GitHubTrendingSnapshot.fetch_status == "failed",
                )
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            ).first()

        return {
            "week_key": snapshot.week_key,
            "requested_week_key": requested_week_key,
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "captured_at": snapshot.captured_at.isoformat(),
            "is_weekly_archive": snapshot.is_weekly_archive,
            "is_stale": snapshot.week_key != requested_week_key,
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
        with Session(engine) as session:
            archive = session.exec(
                select(GitHubTrendingSnapshot)
                .where(
                    GitHubTrendingSnapshot.week_key == week_key,
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
                    GitHubTrendingSnapshot.week_key == week_key,
                    GitHubTrendingSnapshot.fetch_status == "success",
                )
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            ).first()

    def _latest_success_snapshot_global(self) -> Optional[GitHubTrendingSnapshot]:
        with Session(engine) as session:
            return session.exec(
                select(GitHubTrendingSnapshot)
                .where(GitHubTrendingSnapshot.fetch_status == "success")
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            ).first()

    def get_snapshot(self, week_key: Optional[str] = None) -> dict:
        target_week_key = (
            self._normalize_week_key(week_key) if week_key else self.current_week_key()
        )
        snapshot = self._latest_success_snapshot_for_week(target_week_key)
        if snapshot is None:
            snapshot = self._latest_success_snapshot_global()
        if snapshot is None:
            raise ValueError("暂无可用的 GitHub 趋势快照，请先手动更新")
        return self._snapshot_to_dict(snapshot, target_week_key)

    def list_available_weeks(self) -> list[dict]:
        with Session(engine) as session:
            snapshots = session.exec(
                select(GitHubTrendingSnapshot)
                .where(GitHubTrendingSnapshot.fetch_status == "success")
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            ).all()

        by_week: dict[str, dict] = {}
        for snapshot in snapshots:
            week_key = snapshot.week_key
            week_entry = by_week.get(week_key)
            if week_entry is None:
                by_week[week_key] = {
                    "week_key": week_key,
                    "latest_snapshot_date": snapshot.snapshot_date.isoformat(),
                    "latest_captured_at": snapshot.captured_at.isoformat(),
                    "has_archive": bool(snapshot.is_weekly_archive),
                }
            else:
                week_entry["has_archive"] = (
                    bool(week_entry["has_archive"]) or bool(snapshot.is_weekly_archive)
                )

        ordered = sorted(by_week.values(), key=lambda item: item["week_key"], reverse=True)
        return ordered

    def _find_week_item(self, week_key: str, repo_full_name: str) -> TrendingItemPayload:
        normalized_week = self._normalize_week_key(week_key)
        normalized_repo = (repo_full_name or "").strip().lower()
        if not normalized_repo:
            raise ValueError("repo_full_name 不能为空")

        with Session(engine) as session:
            snapshot = session.exec(
                select(GitHubTrendingSnapshot)
                .where(
                    GitHubTrendingSnapshot.week_key == normalized_week,
                    GitHubTrendingSnapshot.fetch_status == "success",
                )
                .order_by(desc(GitHubTrendingSnapshot.captured_at))
            ).first()
            if snapshot is None:
                raise ValueError(f"周榜数据不存在: {normalized_week}")

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

    def _single_material_content(self, week_key: str, item: TrendingItemPayload) -> str:
        description = item.description_zh or item.description or "暂无简介"
        lines = [
            f"# GitHub 周榜项目观察（{week_key} #{item.rank}）",
            "",
            f"- 项目：{item.repo_full_name}",
            f"- 作者：{item.owner}",
            f"- 本周新增 Star：{item.stars_this_week}",
            f"- 项目链接：{item.repo_url}",
            f"- 项目简介：{description}",
            "",
            "## 本周观察（可补充）",
            "- 这个项目解决了什么问题？",
            "- 为什么这周增长快？",
            "",
            "## 改写方向（可补充）",
            "- 面向小白的解释路径",
            "- 可落地实践建议",
        ]
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

    def add_item_to_materials(self, week_key: str, repo_full_name: str) -> dict:
        normalized_week = self._normalize_week_key(week_key)
        item = self._find_week_item(normalized_week, repo_full_name)

        with Session(engine) as session:
            existing = session.exec(
                select(Material).where(
                    Material.source_url == item.repo_url,
                    Material.tags.is_not(None),
                    Material.tags.like("%github-trending%"),
                    Material.tags.like(f"%{normalized_week}%"),
                )
            ).first()
        if existing:
            return {"material_id": existing.id, "created": False}

        title = f"[GitHub周榜 {normalized_week} #{item.rank}] {item.repo_full_name}"
        tags = f"github-trending,周榜,{normalized_week}"
        content = self._single_material_content(normalized_week, item)

        material = self.material_service.create_material(
            title=title,
            content=content,
            tags=tags,
            source_url=item.repo_url,
        )
        return {"material_id": material.id, "created": True}

    def add_week_digest_to_materials(self, week_key: str) -> dict:
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
            return {"material_id": existing.id, "created": False}

        content = self._digest_material_content(normalized_week, items)
        material = self.material_service.create_material(
            title=title,
            content=content,
            tags=tags,
            source_url=TRENDING_SOURCE_URL,
        )
        return {"material_id": material.id, "created": True}

    def build_item_rewrite_markdown(self, week_key: str, repo_full_name: str) -> dict:
        normalized_week = self._normalize_week_key(week_key)
        item = self._find_week_item(normalized_week, repo_full_name)
        return {
            "title": f"{item.repo_full_name}（{normalized_week}）",
            "content": self._single_material_content(normalized_week, item),
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
