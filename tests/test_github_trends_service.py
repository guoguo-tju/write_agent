"""
GitHub 趋势服务测试。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime

venv_path = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    ".venv",
    "lib",
    "python3.10",
    "site-packages",
)
if os.path.exists(venv_path):
    sys.path.insert(0, venv_path)

src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
sys.path.insert(0, src_path)

from sqlalchemy import delete
from sqlmodel import Session, select

from write_agent.models import (
    GitHubRepoEnrichmentCache,
    GitHubTrendingItem,
    GitHubTrendingSnapshot,
    Material,
)
from write_agent.services.github_trending_service import (
    EnrichmentMeta,
    TRANSLATION_SINGLE_TIMEOUT_SECONDS,
    get_github_trending_service,
)
from write_agent.services.material_service import engine


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeLLMResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> dict:
        return self._payload


SAMPLE_HTML = """
<html>
  <body>
    <article class="Box-row">
      <h2><a href="/owner1/repo1"> owner1 / repo1 </a></h2>
      <p>Awesome repository one</p>
      <span itemprop="programmingLanguage">Python</span>
      <a href="/owner1/repo1/stargazers">1,200</a>
      <span class="d-inline-block float-sm-right">350 stars this week</span>
    </article>
    <article class="Box-row">
      <h2><a href="/owner2/repo2"> owner2 / repo2 </a></h2>
      <p>Awesome repository two</p>
      <span itemprop="programmingLanguage">TypeScript</span>
      <a href="/owner2/repo2/stargazers">987</a>
      <span class="d-inline-block float-sm-right">210 stars this week</span>
    </article>
  </body>
</html>
"""


def _build_sample_html(rows: int, star_scope: str = "today") -> str:
    blocks: list[str] = []
    for idx in range(1, rows + 1):
        blocks.append(
            f"""
    <article class="Box-row">
      <h2><a href="/owner{idx}/repo{idx}"> owner{idx} / repo{idx} </a></h2>
      <p>Awesome repository {idx}</p>
      <span itemprop="programmingLanguage">Python</span>
      <a href="/owner{idx}/repo{idx}/stargazers">{1000 + idx}</a>
      <span class="d-inline-block float-sm-right">{100 + idx} stars {star_scope}</span>
    </article>
"""
        )
    return "<html><body>" + "".join(blocks) + "</body></html>"


def _cleanup_tables() -> None:
    with Session(engine) as session:
        session.exec(delete(GitHubTrendingItem))
        session.exec(delete(GitHubTrendingSnapshot))
        session.exec(delete(GitHubRepoEnrichmentCache))
        session.exec(delete(Material).where(Material.tags.like("%github-trending%")))
        session.commit()


def _sample_enrichment_payload(repo_full_name: str, service) -> dict:
    now = datetime.now(service.timezone).isoformat()
    return {
        "repo_full_name": repo_full_name,
        "description": "一个用于演示增强抓取的自动化仓库，强调可执行工作流和协作效率。",
        "topics": ["agent", "automation", "workflow", "productivity"],
        "license": "MIT License",
        "stats": {
            "stars": 5200,
            "forks": 820,
            "open_issues": 19,
            "language": "Python",
        },
        "latest_release": {
            "tag": "v1.2.0",
            "name": "v1.2.0",
            "published_at": "2026-03-18T10:00:00Z",
        },
        "readme": {
            "summary": "该项目提供可组合的自动化模块，帮助团队快速搭建与扩展 AI 代理工作流。",
            "feature_points": [
                "内置多代理任务分发与状态追踪",
                "支持插件式工具调用与权限隔离",
                "可观测日志链路便于排查生产问题",
            ],
            "quick_start": [
                "pip install write-agent-demo 并初始化项目配置",
                "运行 CLI 示例验证端到端执行链路",
                "按文档接入自定义模型和工具",
            ],
        },
        "external_refs": [
            {
                "url": "https://example.com/docs",
                "title": "Official Docs",
                "summary": "文档包含完整部署步骤、配置说明和常见问题排查建议。",
            }
        ],
        "generated_at": now,
        "sources": ["github_api", "readme", "docs"],
    }


def test_refresh_upserts_daily_snapshot(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML),
    )

    asyncio.run(service.refresh_current_week_snapshot())
    asyncio.run(service.refresh_current_week_snapshot())

    today = datetime.now(service.timezone).date()
    week_key = service.current_week_key()

    with Session(engine) as session:
        snapshots = session.exec(
            select(GitHubTrendingSnapshot).where(
                GitHubTrendingSnapshot.week_key == week_key,
                GitHubTrendingSnapshot.snapshot_date == today,
            )
        ).all()
        assert len(snapshots) == 1

        items = session.exec(
            select(GitHubTrendingItem).where(
                GitHubTrendingItem.snapshot_id == snapshots[0].id
            )
        ).all()
        assert len(items) == 2
        assert hasattr(items[0], "description_zh")


def test_refresh_daily_snapshot_persists_period_fields(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML.replace("this week", "today")),
    )

    asyncio.run(service.refresh_snapshot("daily"))

    today = datetime.now(service.timezone).date()
    today_key = today.isoformat()

    with Session(engine) as session:
        snapshot = session.exec(
            select(GitHubTrendingSnapshot).where(
                GitHubTrendingSnapshot.period_type == "daily",
                GitHubTrendingSnapshot.period_key == today_key,
                GitHubTrendingSnapshot.snapshot_date == today,
            )
        ).first()

    assert snapshot is not None
    assert snapshot.period_type == "daily"
    assert snapshot.period_key == today_key


def test_refresh_daily_parses_today_stars(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    html = SAMPLE_HTML.replace("350 stars this week", "350 stars today")
    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(html),
    )

    asyncio.run(service.refresh_snapshot("daily"))
    data = service.get_snapshot(period_type="daily")

    assert data["period_type"] == "daily"
    assert data["items"][0]["stars_this_week"] == 350


def test_refresh_daily_enriches_description_zh(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML.replace("this week", "today")),
    )
    monkeypatch.setattr(
        service,
        "_translate_descriptions_to_zh_batch",
        lambda texts: {0: "仓库一中文简介", 1: "仓库二中文简介"},
    )
    monkeypatch.setattr(
        service,
        "_translate_description_to_zh_single",
        lambda text: None,
    )

    asyncio.run(service.refresh_snapshot("daily"))
    data = service.get_snapshot(period_type="daily")

    assert data["period_type"] == "daily"
    assert data["items"][0]["description_zh"] == "仓库一中文简介"
    assert data["items"][1]["description_zh"] == "仓库二中文简介"


def test_refresh_daily_translation_failure_uses_zh_fallback(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML.replace("this week", "today")),
    )
    monkeypatch.setattr(service, "_translate_descriptions_to_zh_batch", lambda texts: {})
    monkeypatch.setattr(service, "_translate_description_to_zh_single", lambda text: None)

    asyncio.run(service.refresh_snapshot("daily"))
    data = service.get_snapshot(period_type="daily")

    assert data["items"][0]["description_zh"] == "该项目英文简介暂未完成中文翻译，请稍后重试。"


def test_refresh_daily_missing_batch_translation_uses_single_retry(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML.replace("this week", "today")),
    )
    monkeypatch.setattr(
        service,
        "_translate_descriptions_to_zh_batch",
        lambda texts: {0: "仓库一中文简介"},
    )
    monkeypatch.setattr(
        service,
        "_translate_description_to_zh_single",
        lambda text: "单条补翻中文",
    )

    asyncio.run(service.refresh_snapshot("daily"))
    data = service.get_snapshot(period_type="daily")

    assert data["items"][0]["description_zh"] == "仓库一中文简介"
    assert data["items"][1]["description_zh"] == "单条补翻中文"


def test_refresh_daily_missing_batch_translation_retries_each_item(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(_build_sample_html(5, "today")),
    )
    monkeypatch.setattr(service, "_translate_descriptions_to_zh_batch", lambda texts: {})
    calls: list[str] = []

    def _fake_single(text: str) -> str:
        calls.append(text)
        return f"单条补翻中文-{len(calls)}"

    monkeypatch.setattr(service, "_translate_description_to_zh_single", _fake_single)

    asyncio.run(service.refresh_snapshot("daily"))
    data = service.get_snapshot(period_type="daily")

    assert len(data["items"]) == 5
    assert len(calls) == 5
    assert [item["description_zh"] for item in data["items"]] == [
        "单条补翻中文-1",
        "单条补翻中文-2",
        "单条补翻中文-3",
        "单条补翻中文-4",
        "单条补翻中文-5",
    ]


def test_batch_translation_accepts_string_index(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.os.getenv",
        lambda key, default=None: None if key == "PYTEST_CURRENT_TEST" else os.environ.get(key, default),
    )
    monkeypatch.setattr(
        "write_agent.services.github_trending_service.settings.openai_api_key",
        "test-key",
        raising=False,
    )
    monkeypatch.setattr(
        "write_agent.services.github_trending_service.settings.openai_model",
        "test-model",
        raising=False,
    )
    monkeypatch.setattr(
        "write_agent.services.github_trending_service.settings.openai_base_url",
        "https://api.example.com/v1",
        raising=False,
    )

    llm_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        [
                            {"index": "0", "translation": "仓库一中文简介"},
                            {"index": 1, "translation": "仓库二中文简介"},
                        ],
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }
    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.post",
        lambda *args, **kwargs: _FakeLLMResponse(llm_payload),
    )

    translated = service._translate_descriptions_to_zh_batch(["repo one", "repo two"])
    assert translated == {0: "仓库一中文简介", 1: "仓库二中文简介"}


def test_single_translation_uses_relaxed_timeout(monkeypatch) -> None:
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.os.getenv",
        lambda key, default=None: None if key == "PYTEST_CURRENT_TEST" else os.environ.get(key, default),
    )
    monkeypatch.setattr(
        "write_agent.services.github_trending_service.settings.openai_api_key",
        "test-key",
        raising=False,
    )
    monkeypatch.setattr(
        "write_agent.services.github_trending_service.settings.openai_model",
        "test-model",
        raising=False,
    )
    monkeypatch.setattr(
        "write_agent.services.github_trending_service.settings.openai_base_url",
        "http://localhost:8317",
        raising=False,
    )
    monkeypatch.setattr(
        "write_agent.services.github_trending_service.settings.openai_timeout_seconds",
        60.0,
        raising=False,
    )

    captured: dict[str, float] = {}

    class _FakeSession:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return _FakeLLMResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "简体中文翻译"
                            }
                        }
                    ]
                }
            )

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.Session",
        lambda: _FakeSession(),
    )

    translated = service._translate_description_to_zh_single("Open-source voice AI")

    assert translated == "简体中文翻译"
    assert captured["timeout"] == TRANSLATION_SINGLE_TIMEOUT_SECONDS


def test_is_acceptable_zh_allows_tech_terms_with_chinese_backbone() -> None:
    service = get_github_trending_service()
    translated = (
        "提取自 ChatGPT (GPT-5.4, GPT-5.3, Codex)、Claude (Opus 4.6, Sonnet 4.6, Claude Code)、"
        "Gemini (3.1 Pro, 3 Flash, CLI)、Grok (4.2, 4)、Perplexity 等的系统提示词。定期更新。"
    )
    assert service._is_acceptable_zh(translated) is True


def test_is_acceptable_zh_rejects_mostly_english_output() -> None:
    service = get_github_trending_service()
    translated = "ChatGPT GPT-5.4 Claude Opus Gemini 3.1 Flash Grok Perplexity 中文"
    assert service._is_acceptable_zh(translated) is False


def test_translation_cache_skips_fallback_value(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()
    fallback_value = service._zh_translation_fallback()

    with Session(engine) as session:
        snapshot = GitHubTrendingSnapshot(
            week_key="2026-03-31",
            period_type="daily",
            period_key="2026-03-31",
            snapshot_date=datetime.now(service.timezone).date(),
            fetch_status="success",
            is_weekly_archive=False,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        session.add(
            GitHubTrendingItem(
                snapshot_id=snapshot.id,
                rank=1,
                repo_full_name="owner/repo",
                repo_name="repo",
                owner="owner",
                description="English desc",
                description_zh=fallback_value,
                repo_url="https://github.com/owner/repo",
                stars_this_week=100,
                language="Python",
                total_stars=1000,
            )
        )
        session.commit()

    cache = service._load_period_translation_cache("daily", "2026-03-31")
    assert cache == {}


def test_refresh_retry_untranslated_only_updates_fallback_rows(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()
    fallback_value = service._zh_translation_fallback()
    target_day = "2026-03-31"

    with Session(engine) as session:
        snapshot = GitHubTrendingSnapshot(
            week_key=target_day,
            period_type="daily",
            period_key=target_day,
            snapshot_date=datetime.fromisoformat(target_day).date(),
            fetch_status="success",
            is_weekly_archive=False,
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)

        session.add(
            GitHubTrendingItem(
                snapshot_id=snapshot.id,
                rank=1,
                repo_full_name="owner1/repo1",
                repo_name="repo1",
                owner="owner1",
                description="Already translated",
                description_zh="已有中文简介",
                repo_url="https://github.com/owner1/repo1",
                stars_this_week=100,
                language="Python",
                total_stars=1000,
            )
        )
        session.add(
            GitHubTrendingItem(
                snapshot_id=snapshot.id,
                rank=2,
                repo_full_name="owner2/repo2",
                repo_name="repo2",
                owner="owner2",
                description="Needs translation",
                description_zh=fallback_value,
                repo_url="https://github.com/owner2/repo2",
                stars_this_week=90,
                language="TypeScript",
                total_stars=900,
            )
        )
        session.commit()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("should not fetch trending html")),
    )

    pending_texts: list[str] = []

    def _fake_batch(texts: list[str]) -> dict[int, str]:
        pending_texts.extend(texts)
        return {0: "补翻后的中文简介"}

    monkeypatch.setattr(service, "_translate_descriptions_to_zh_batch", _fake_batch)
    monkeypatch.setattr(service, "_translate_description_to_zh_single", lambda text: None)

    asyncio.run(
        service.refresh_snapshot(
            "daily",
            period_key=target_day,
            retry_untranslated_only=True,
        )
    )
    data = service.get_snapshot(period_type="daily", period_key=target_day)

    assert pending_texts == ["Needs translation"]
    assert data["items"][0]["description_zh"] == "已有中文简介"
    assert data["items"][1]["description_zh"] == "补翻后的中文简介"


def test_list_daily_periods_returns_recent_7_days(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML.replace("this week", "today")),
    )

    for _ in range(2):
        asyncio.run(service.refresh_snapshot("daily"))

    periods = service.list_available_periods("daily", limit=7)

    assert periods
    assert len(periods) <= 7
    assert periods[0]["period_type"] == "daily"
    assert "period_key" in periods[0]


def test_add_item_material_dedup(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML),
    )

    asyncio.run(service.refresh_current_week_snapshot())
    week_key = service.current_week_key()

    first = service.add_item_to_materials(week_key, "owner1/repo1", enhance=False)
    second = service.add_item_to_materials(week_key, "owner1/repo1", enhance=False)

    assert first["created"] is True
    assert second["created"] is False
    assert first["material_id"] == second["material_id"]
    assert first["enrich"]["attempted"] is False
    assert second["enrich"]["attempted"] is False


def test_add_week_digest_material_dedup(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML),
    )

    asyncio.run(service.refresh_current_week_snapshot())
    week_key = service.current_week_key()

    first = service.add_week_digest_to_materials(week_key)
    second = service.add_week_digest_to_materials(week_key)

    assert first["created"] is True
    assert second["created"] is False
    assert first["material_id"] == second["material_id"]


def test_get_snapshot_marks_stale_when_fallback(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML),
    )
    asyncio.run(service.refresh_current_week_snapshot())

    data = service.get_snapshot("1999-W01")
    assert data["requested_week_key"] == "1999-W01"
    assert data["is_stale"] is True
    assert data["items"]


def test_get_repo_enrichment_degrades_without_token(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.settings.github_token",
        "",
        raising=False,
    )
    payload, meta = service._get_repo_enrichment("owner1/repo1", enhance=True)

    assert payload is None
    assert meta.attempted is True
    assert meta.degraded is True
    assert meta.degrade_reason == "missing_github_token"


def test_get_repo_enrichment_uses_fresh_cache(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()
    repo_full_name = "owner1/repo1"
    payload = _sample_enrichment_payload(repo_full_name, service)
    now = datetime.now(service.timezone)

    with Session(engine) as session:
        session.add(
            GitHubRepoEnrichmentCache(
                repo_full_name=repo_full_name,
                payload_json=json.dumps(payload, ensure_ascii=False),
                fetched_at=now,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.settings.github_token",
        "test-token",
        raising=False,
    )
    cached_payload, meta = service._get_repo_enrichment(repo_full_name, enhance=True)

    assert cached_payload is not None
    assert cached_payload["repo_full_name"] == repo_full_name
    assert meta.attempted is True
    assert meta.cache_hit is True
    assert meta.degraded is False


def test_add_item_existing_material_can_update_enrichment(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()
    repo_full_name = "owner1/repo1"
    sample_payload = _sample_enrichment_payload(repo_full_name, service)
    enrich_meta = EnrichmentMeta(
        attempted=True,
        cache_hit=False,
        degraded=False,
        degrade_reason="",
        duration_ms=35,
        fetched_at=sample_payload["generated_at"],
        sources=["github_api", "readme", "docs"],
    )

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML),
    )
    asyncio.run(service.refresh_current_week_snapshot())
    week_key = service.current_week_key()

    created = service.add_item_to_materials(week_key, repo_full_name, enhance=False)
    assert created["created"] is True

    monkeypatch.setattr(
        service,
        "_get_repo_enrichment",
        lambda repo_full_name, enhance=True: (sample_payload, enrich_meta),
    )
    updated = service.add_item_to_materials(week_key, repo_full_name, enhance=True)
    assert updated["created"] is False
    assert updated["updated"] is True
    assert updated["enrich"]["attempted"] is True

    with Session(engine) as session:
        material = session.get(Material, updated["material_id"])
        assert material is not None
        content = material.content or ""
        assert "### 项目介绍" in content
        assert "### 为什么会受欢迎" in content
        assert "## 仓库增强信息（自动抓取）" not in content
        assert "<!-- github-enrich repo:" not in content
        assert "安装/快速开始" not in content

        intro_match = re.search(r"### 项目介绍\s*\n-\s*(.+)", content)
        assert intro_match is not None
        intro_text = (intro_match.group(1) if intro_match else "").strip()
        assert intro_text
        assert "它聚焦的问题是：" in intro_text
        assert "累计星标" not in intro_text
        assert "分叉" not in intro_text
        assert "公开问题" not in intro_text
        assert "本周新增星标" not in intro_text

        advantage_match = re.search(r"### 核心特点与优势\s*\n-\s*(.+)", content)
        assert advantage_match is not None
        advantage_text = (advantage_match.group(1) if advantage_match else "").strip()
        assert advantage_text
        assert "核心能力可以拆成以下几类" in advantage_text
        assert "它聚焦的问题是：" not in advantage_text
        assert "是一个" not in advantage_text
        assert "## 本周观察（可补充）" not in content
        assert "## 改写方向（可补充）" not in content


def test_build_item_rewrite_markdown_with_enrichment(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()
    repo_full_name = "owner1/repo1"
    sample_payload = _sample_enrichment_payload(repo_full_name, service)
    enrich_meta = EnrichmentMeta(
        attempted=True,
        cache_hit=False,
        degraded=False,
        degrade_reason="",
        duration_ms=42,
        fetched_at=sample_payload["generated_at"],
        sources=["github_api", "readme", "docs"],
    )

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML),
    )
    asyncio.run(service.refresh_current_week_snapshot())
    week_key = service.current_week_key()

    monkeypatch.setattr(
        service,
        "_get_repo_enrichment",
        lambda repo_full_name, enhance=True: (sample_payload, enrich_meta),
    )
    result = service.build_item_rewrite_markdown(week_key, repo_full_name, enhance=True)

    assert result["enrich"]["attempted"] is True
    assert result["enrich"]["degraded"] is False
    assert "## 仓库增强速览（结构化）" in result["content"]
    assert "- 项目定位：" in result["content"]
    assert "- 核心优势：" in result["content"]
    assert "- 受欢迎原因：" in result["content"]
    assert "- 快速上手：" not in result["content"]
    assert "- 适用场景：" in result["content"]
    assert "- 风险/局限：" in result["content"]
    assert "- 最近动态：" in result["content"]
    structured = result["content"].split("## 仓库增强速览（结构化）", 1)[1].strip()
    assert 300 <= len(structured) <= 500
