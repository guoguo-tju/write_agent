"""
API 回归测试：覆盖本轮验收修复的问题。
"""
from __future__ import annotations

import os
import sys
import uuid

# 与现有测试保持一致：显式挂载 venv site-packages 与 src 路径
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

from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session
from sqlmodel import SQLModel

from write_agent.core.database import engine
from write_agent.main import app
from write_agent.models import WritingStyle


def setup_module() -> None:
    """确保测试数据库表存在。"""
    SQLModel.metadata.create_all(engine)


def test_reviews_stream_route_not_shadowed() -> None:
    """`/api/reviews/stream` 不应被 `/{review_id}` 路由误匹配。"""
    client = TestClient(app)

    resp = client.get("/api/reviews/stream", params={"rewrite_id": 999999})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "改写记录不存在"


def test_rewrites_stream_invalid_target_words_returns_400() -> None:
    """改写参数校验错误应返回 400，而非 500。"""
    client = TestClient(app)

    resp = client.get(
        "/api/rewrites/stream",
        params={
            "source_article": "abc",
            "style_id": 1,
            "target_words": 10,
        },
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "目标字数应在 100-10000 之间"


def test_workflow_invalid_style_returns_404() -> None:
    """工作流入参中的无效风格应在入口校验返回 404。"""
    client = TestClient(app)

    resp = client.post(
        "/api/reviews/workflow",
        json={
            "source_article": "workflow test",
            "style_id": 999999,
            "target_words": 200,
            "enable_rag": False,
            "max_retries": 1,
        },
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "风格不存在"


def test_cover_style_soft_deleted_not_queryable() -> None:
    """软删除封面风格后，详情接口应返回 404。"""
    client = TestClient(app)
    name = f"regression-style-{uuid.uuid4().hex[:8]}"

    created = client.post(
        "/api/covers/styles",
        json={
            "name": name,
            "prompt_template": "cover prompt {title} {content}",
            "description": "regression",
        },
    )
    assert created.status_code == 200
    style_id = created.json()["id"]

    deleted = client.delete(f"/api/covers/styles/{style_id}")
    assert deleted.status_code == 200

    detail = client.get(f"/api/covers/styles/{style_id}")
    assert detail.status_code == 404
    assert detail.json()["detail"] == "风格不存在"


def test_covers_by_rewrites_returns_empty_list_for_missing_ids() -> None:
    """批量查询封面时，不存在的改写应被忽略而不是返回 404。"""
    client = TestClient(app)

    resp = client.get(
        "/api/covers/by-rewrites",
        params=[
            ("rewrite_ids", "999991"),
            ("rewrite_ids", "999992"),
        ],
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def _create_style_for_rewrite_tests() -> int:
    with Session(engine) as session:
        style = WritingStyle(
            name=f"rewrite-url-style-{uuid.uuid4().hex[:8]}",
            style_description="{}",
            tags="test",
        )
        session.add(style)
        session.commit()
        session.refresh(style)
        return style.id


def test_rewrite_service_resolves_url_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """改写服务接收 URL 输入时，应先抓取正文再落库。"""
    from write_agent.services.rewrite_service import RewriteService

    style_id = _create_style_for_rewrite_tests()
    service = RewriteService()
    monkeypatch.setattr(
        service,
        "_fetch_url_content",
        lambda _url: "这是从链接抓取到的正文内容",
    )

    record = service.create_rewrite(
        source_article="https://mp.weixin.qq.com/s/example",
        style_id=style_id,
        target_words=200,
    )
    assert record.source_article == "这是从链接抓取到的正文内容"


def test_rewrite_service_url_fetch_failure_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """URL 抓取失败时，改写服务应返回明确错误。"""
    from write_agent.services.rewrite_service import RewriteService

    style_id = _create_style_for_rewrite_tests()
    service = RewriteService()
    monkeypatch.setattr(service, "_fetch_url_content", lambda _url: None)

    with pytest.raises(ValueError, match="无法从 URL 抓取内容"):
        service.create_rewrite(
            source_article="https://mp.weixin.qq.com/s/example",
            style_id=style_id,
            target_words=200,
        )
