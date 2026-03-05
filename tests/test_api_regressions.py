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
from write_agent.models import Material, WritingStyle


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


def test_styles_patch_update_success() -> None:
    """PATCH /api/styles/{id} 可成功更新风格。"""
    client = TestClient(app)
    style_id = _create_style_for_rewrite_tests()
    payload = {
        "name": "更新后的风格",
        "tags": "更新,测试",
        "example_text": "示例文本",
        "style_description": '{"persona":"理性作者","overall_summary":"测试总结"}',
    }

    resp = client.patch(f"/api/styles/{style_id}", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == style_id
    assert data["name"] == "更新后的风格"
    assert data["tags"] == "更新,测试"
    assert data["style_description"] == payload["style_description"]
    assert data["updated_at"]


def test_styles_patch_rejects_invalid_json() -> None:
    """PATCH /api/styles/{id} 应拦截非法 JSON。"""
    client = TestClient(app)
    style_id = _create_style_for_rewrite_tests()
    payload = {
        "name": "非法JSON",
        "style_description": "{bad json}",
    }

    resp = client.patch(f"/api/styles/{style_id}", json=payload)

    assert resp.status_code == 400
    assert resp.json()["detail"] == "风格描述必须是有效 JSON"


def test_styles_patch_missing_style_returns_404() -> None:
    """PATCH /api/styles/{id} 对不存在风格返回 404。"""
    client = TestClient(app)
    payload = {
        "name": "不存在风格",
        "style_description": '{"persona":"x"}',
    }

    resp = client.patch("/api/styles/999999", json=payload)

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


def test_materials_pagination_limit_and_total() -> None:
    """素材列表应支持 limit 分页并返回正确 total。"""
    client = TestClient(app)
    marker = f"mat-page-{uuid.uuid4().hex[:8]}"

    for idx in range(3):
        _create_material_for_tests(
            title=f"{marker}-title-{idx}",
            content=f"{marker}-content-{idx}",
            tags="分页,测试",
            source_url=f"https://example.com/{marker}/{idx}",
        )

    resp = client.get(
        "/api/materials",
        params={"keyword": marker, "page": 1, "limit": 2},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["limit"] == 2
    assert data["total"] >= 3
    assert len(data["items"]) == 2


def test_materials_pagination_with_tags_and_keyword() -> None:
    """素材列表应支持 tags + keyword 组合过滤并可翻页。"""
    client = TestClient(app)
    marker = f"mat-mix-{uuid.uuid4().hex[:8]}"

    first_id = _create_material_for_tests(
        title=f"{marker}-a",
        content=f"{marker}-content-a",
        tags="组合过滤,测试",
        source_url=f"https://example.com/{marker}/a",
    )
    second_id = _create_material_for_tests(
        title=f"{marker}-b",
        content=f"{marker}-content-b",
        tags="组合过滤,测试",
        source_url=f"https://example.com/{marker}/b",
    )
    # 干扰数据：同标签不同关键字
    _create_material_for_tests(
        title="noise-material",
        content="unrelated-keyword",
        tags="组合过滤,测试",
        source_url="https://example.com/noise",
    )

    page1 = client.get(
        "/api/materials",
        params={
            "tags": "组合过滤",
            "keyword": marker,
            "page": 1,
            "limit": 1,
        },
    )
    page2 = client.get(
        "/api/materials",
        params={
            "tags": "组合过滤",
            "keyword": marker,
            "page": 2,
            "limit": 1,
        },
    )

    assert page1.status_code == 200
    assert page2.status_code == 200

    data1 = page1.json()
    data2 = page2.json()
    assert data1["total"] >= 2
    assert data2["total"] >= 2
    assert len(data1["items"]) == 1
    assert len(data2["items"]) == 1

    ids = {data1["items"][0]["id"], data2["items"][0]["id"]}
    assert ids.issubset({first_id, second_id})
    assert len(ids) == 2


def test_create_material_with_url_only_wechat_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仅提交公众号 URL 时，后端应自动抓取正文并创建素材。"""
    client = TestClient(app)
    marker = f"wechat-url-only-{uuid.uuid4().hex[:6]}"

    from write_agent.api.materials import material_service

    monkeypatch.setattr(
        material_service,
        "_fetch_url_content",
        lambda _url: f"{marker} 正文内容",
    )
    monkeypatch.setattr(
        material_service.rag_service,
        "add_material",
        lambda *args, **kwargs: None,
    )

    resp = client.post(
        "/api/materials",
        json={
            "source_url": "https://mp.weixin.qq.com/s/test-demo",
            "tags": "链接抓取,公众号",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert marker in data["content"]
    assert data["source_url"] == "https://mp.weixin.qq.com/s/test-demo"


def test_create_material_with_url_only_twitter_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仅提交 Twitter/X URL 时，后端应支持 best-effort 自动抓取。"""
    client = TestClient(app)
    marker = f"twitter-url-only-{uuid.uuid4().hex[:6]}"

    from write_agent.api.materials import material_service

    monkeypatch.setattr(
        material_service,
        "_fetch_url_content",
        lambda _url: f"{marker} tweet 内容",
    )
    monkeypatch.setattr(
        material_service.rag_service,
        "add_material",
        lambda *args, **kwargs: None,
    )

    resp = client.post(
        "/api/materials",
        json={
            "source_url": "https://x.com/demo/status/1888888888888888888",
            "tags": "链接抓取,twitter",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert marker in data["content"]
    assert data["source_url"] == "https://x.com/demo/status/1888888888888888888"


def test_create_material_with_url_only_auto_infers_title_from_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仅 URL 且未传 title 时，应自动从抓取内容首行推断标题。"""
    client = TestClient(app)

    from write_agent.api.materials import material_service

    monkeypatch.setattr(
        material_service,
        "_fetch_url_content",
        lambda _url: "这是一篇自动解析出来的文章标题\n\n正文内容",
    )
    monkeypatch.setattr(
        material_service.rag_service,
        "add_material",
        lambda *args, **kwargs: None,
    )

    resp = client.post(
        "/api/materials",
        json={"source_url": "https://mp.weixin.qq.com/s/title-auto"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "这是一篇自动解析出来的文章标题"
    assert data["source_url"] == "https://mp.weixin.qq.com/s/title-auto"


def test_create_material_with_url_only_fetch_failure_returns_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """链接抓取失败时应阻止保存并返回 400。"""
    client = TestClient(app)

    from write_agent.api.materials import material_service

    monkeypatch.setattr(material_service, "_fetch_url_content", lambda _url: None)

    resp = client.post(
        "/api/materials",
        json={"source_url": "https://mp.weixin.qq.com/s/failed-fetch"},
    )

    assert resp.status_code == 400
    assert "无法从 URL 抓取内容" in resp.json()["detail"]


def test_materials_retrieve_returns_enriched_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """素材检索测试接口应返回 enrich 后字段并支持缺失素材降级。"""
    client = TestClient(app)
    marker = f"mat-retrieve-{uuid.uuid4().hex[:8]}"
    material_id = _create_material_for_tests(
        title=f"{marker}-title",
        content=f"{marker}-content",
        tags="检索,测试",
        source_url=f"https://example.com/{marker}",
    )

    from write_agent.api.materials import material_service

    monkeypatch.setattr(
        material_service.rag_service,
        "search",
        lambda query, top_k: [
            {"material_id": material_id, "content": "fallback-content", "score": 0.91},
            {"material_id": 99999999, "content": "orphan-content", "score": 0.32},
        ],
    )

    resp = client.post(
        "/api/materials/retrieve",
        json={"query": "测试检索问题", "top_k": 5},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2

    first = data["items"][0]
    assert first["material_id"] == material_id
    assert first["title"] == f"{marker}-title"
    assert first["source_url"] == f"https://example.com/{marker}"
    assert first["tags"] == "检索,测试"
    assert first["content"] == f"{marker}-content"
    assert isinstance(first["score"], float)

    second = data["items"][1]
    assert second["material_id"] == 99999999
    assert second["title"] == "素材 #99999999"
    assert second["content"] == "orphan-content"


def test_update_material_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH /api/materials/{id} 应支持更新正文并返回最新字段。"""
    client = TestClient(app)
    marker = f"mat-update-{uuid.uuid4().hex[:8]}"
    material_id = _create_material_for_tests(
        title=f"{marker}-old-title",
        content=f"{marker}-old-content",
        tags="旧标签",
        source_url=f"https://example.com/{marker}/old",
    )

    from write_agent.api.materials import material_service

    monkeypatch.setattr(material_service.rag_service, "delete_material", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(material_service.rag_service, "add_material", lambda *_args, **_kwargs: None)

    resp = client.patch(
        f"/api/materials/{material_id}",
        json={
            "title": f"{marker}-new-title",
            "content": f"{marker}-new-content",
            "tags": "新标签,测试",
            "source_url": f"https://example.com/{marker}/new",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == material_id
    assert data["title"] == f"{marker}-new-title"
    assert data["content"] == f"{marker}-new-content"
    assert data["tags"] == "新标签,测试"
    assert data["source_url"] == f"https://example.com/{marker}/new"


def test_update_material_not_found_returns_404() -> None:
    """PATCH 不存在的素材应返回 404。"""
    client = TestClient(app)

    resp = client.patch(
        "/api/materials/99999999",
        json={
            "title": "missing",
            "content": "missing-content",
        },
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "素材不存在"


def _create_material_for_tests(
    title: str,
    content: str,
    tags: str,
    source_url: str,
) -> int:
    with Session(engine) as session:
        material = Material(
            title=title,
            content=content,
            tags=tags,
            source_url=source_url,
            embedding_status="completed",
        )
        session.add(material)
        session.commit()
        session.refresh(material)
        return material.id
