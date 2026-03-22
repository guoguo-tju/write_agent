"""
GitHub 趋势服务测试。
"""
from __future__ import annotations

import asyncio
import os
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

from write_agent.models import GitHubTrendingItem, GitHubTrendingSnapshot, Material
from write_agent.services.github_trending_service import get_github_trending_service
from write_agent.services.material_service import engine


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


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


def _cleanup_tables() -> None:
    with Session(engine) as session:
        session.exec(delete(GitHubTrendingItem))
        session.exec(delete(GitHubTrendingSnapshot))
        session.exec(delete(Material).where(Material.tags.like("%github-trending%")))
        session.commit()


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


def test_add_item_material_dedup(monkeypatch) -> None:
    _cleanup_tables()
    service = get_github_trending_service()

    monkeypatch.setattr(
        "write_agent.services.github_trending_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(SAMPLE_HTML),
    )

    asyncio.run(service.refresh_current_week_snapshot())
    week_key = service.current_week_key()

    first = service.add_item_to_materials(week_key, "owner1/repo1")
    second = service.add_item_to_materials(week_key, "owner1/repo1")

    assert first["created"] is True
    assert second["created"] is False
    assert first["material_id"] == second["material_id"]


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
