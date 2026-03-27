"""
API 回归测试：覆盖本轮验收修复的问题。
"""
from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace

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
from sqlmodel import select

from write_agent.core.database import engine
from write_agent.main import app
from write_agent.models import Material, RewriteRecord, WritingStyle


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


def test_workflow_invalid_target_words_returns_400() -> None:
    """工作流 target_words 越界应返回 400。"""
    client = TestClient(app)
    style_id = _create_style_for_rewrite_tests()

    resp = client.post(
        "/api/reviews/workflow",
        json={
            "source_article": "workflow test",
            "style_id": style_id,
            "target_words": 99,
            "enable_rag": False,
            "max_retries": 1,
        },
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "目标字数应在 100-10000 之间"


def test_workflow_jobs_create_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """相同幂等键重复创建任务时，应返回同一个 job_id。"""
    from write_agent.api import reviews as reviews_api

    client = TestClient(app)
    style_id = _create_style_for_rewrite_tests()
    monkeypatch.setattr(reviews_api.workflow_job_service, "enqueue_job", lambda *_args, **_kwargs: None)

    idempotency_key = f"idem-{uuid.uuid4().hex}"
    payload = {
        "source_article": "workflow test",
        "style_id": style_id,
        "target_words": 200,
        "enable_rag": True,
        "rag_top_k": 5,
        "max_retries": 1,
        "idempotency_key": idempotency_key,
    }

    first = client.post("/api/reviews/workflow/jobs", json=payload)
    second = client.post("/api/reviews/workflow/jobs", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200

    first_data = first.json()
    second_data = second.json()
    assert first_data["job_id"] == second_data["job_id"]
    assert first_data["idempotent_hit"] is False
    assert second_data["idempotent_hit"] is True
    assert first_data["status"] == second_data["status"] == "queued"
    assert first_data["checkpoint_seq"] == second_data["checkpoint_seq"] == 0

    status = client.get(f"/api/reviews/workflow/jobs/{first_data['job_id']}")
    assert status.status_code == 200
    status_data = status.json()
    assert status_data["job_id"] == first_data["job_id"]
    assert status_data["status"] == "queued"
    assert status_data["current_stage"] == "queued"
    assert status_data["checkpoint_seq"] == 0


def test_workflow_jobs_resume_and_cancel_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    """任务恢复与取消应遵循基本语义。"""
    from write_agent.api import reviews as reviews_api

    client = TestClient(app)
    style_id = _create_style_for_rewrite_tests()
    monkeypatch.setattr(reviews_api.workflow_job_service, "enqueue_job", lambda *_args, **_kwargs: None)

    created = client.post(
        "/api/reviews/workflow/jobs",
        json={
            "source_article": "workflow test",
            "style_id": style_id,
            "target_words": 200,
            "enable_rag": True,
            "rag_top_k": 5,
            "max_retries": 99,
            "idempotency_key": f"resume-cancel-{uuid.uuid4().hex}",
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    resumed = client.post(f"/api/reviews/workflow/jobs/{job_id}/resume")
    assert resumed.status_code == 200
    resumed_data = resumed.json()
    assert resumed_data["job_id"] == job_id
    assert resumed_data["status"] == "queued"
    assert resumed_data["resume_count"] == 1

    cancelled = client.post(f"/api/reviews/workflow/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    cancelled_data = cancelled.json()
    assert cancelled_data["job_id"] == job_id
    assert cancelled_data["status"] == "cancelled"
    assert cancelled_data["current_stage"] == "cancelled"

    blocked = client.post(f"/api/reviews/workflow/jobs/{job_id}/resume")
    assert blocked.status_code == 404
    assert "无法恢复" in blocked.json()["detail"]


def test_workflow_job_stream_sse_event_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """新任务 SSE 至少包含 stage/progress/content/done 事件，且结构可被前端解析。"""
    from write_agent.api import reviews as reviews_api

    client = TestClient(app)
    style_id = _create_style_for_rewrite_tests()
    monkeypatch.setattr(reviews_api.workflow_job_service, "enqueue_job", lambda *_args, **_kwargs: None)

    def fake_stream_events(job_id: int, *, from_seq: int = 0, **_kwargs):
        yield {
            "type": "stage",
            "stage": "rewrite",
            "round": 1,
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 1,
        }
        yield {
            "type": "progress",
            "stage": "rewrite",
            "round": 1,
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 2,
            "message": "25%",
        }
        yield {
            "type": "content",
            "stage": "rewrite",
            "round": 1,
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 3,
            "delta": "chunk-1",
        }
        yield {
            "type": "done",
            "stage": "finalize",
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 4,
            "status": "passed",
            "passed": True,
        }

    monkeypatch.setattr(reviews_api.workflow_job_service, "stream_events", fake_stream_events)

    created = client.post(
        "/api/reviews/workflow/jobs",
        json={
            "source_article": "workflow test",
            "style_id": style_id,
            "target_words": 200,
            "enable_rag": False,
            "max_retries": 1,
            "idempotency_key": f"stream-shape-{uuid.uuid4().hex}",
        },
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    with client.stream(
        "GET",
        f"/api/reviews/workflow/jobs/{job_id}/stream",
        params={"from_seq": 0},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        chunks = [line for line in resp.iter_lines() if line and line.startswith("data: ")]

    assert len(chunks) == 4
    events = [eval_json(chunk[6:]) for chunk in chunks]
    assert [event["type"] for event in events] == ["stage", "progress", "content", "done"]
    assert events[0]["stage"] == "rewrite"
    assert events[2]["delta"] == "chunk-1"
    assert events[-1]["status"] == "passed"
    for event in events:
        assert event["job_id"] == job_id
        obs = event.get("obs")
        assert isinstance(obs, dict)
        assert obs.get("trace_id")
        assert obs.get("node_id")
        assert obs.get("behavior_id")
        assert obs.get("event_id")
        assert obs.get("ts")


def test_workflow_bridge_stream_sse_event_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """旧工作流接口桥接后仍应返回可解析的 SSE 事件。"""
    from write_agent.api import reviews as reviews_api

    client = TestClient(app)
    style_id = _create_style_for_rewrite_tests()
    fake_job = SimpleNamespace(id=321, status="queued", rewrite_id=123, review_id=456, checkpoint_seq=0)
    captured: dict[str, object] = {}

    def fake_create_job(**kwargs):
        captured.update(kwargs)
        return fake_job, False

    def fake_stream_events(job_id: int, *, from_seq: int = 0, **_kwargs):
        yield {
            "type": "stage",
            "stage": "rewrite",
            "round": 1,
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 1,
        }
        yield {
            "type": "progress",
            "stage": "rewrite",
            "round": 1,
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 2,
            "message": "25%",
        }
        yield {
            "type": "content",
            "stage": "rewrite",
            "round": 1,
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 3,
            "delta": "chunk-1",
        }
        yield {
            "type": "done",
            "stage": "finalize",
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 4,
            "status": "passed",
            "passed": True,
        }

    monkeypatch.setattr(reviews_api.workflow_job_service, "create_job", fake_create_job)
    monkeypatch.setattr(reviews_api.workflow_job_service, "stream_events", fake_stream_events)

    with client.stream(
        "POST",
        "/api/reviews/workflow",
        json={
            "source_article": "workflow test",
            "style_id": style_id,
            "target_words": 200,
            "enable_rag": False,
            "max_retries": 99,
        },
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        chunks = [line for line in resp.iter_lines() if line and line.startswith("data: ")]

    assert captured["max_retries"] == 1
    assert captured["rag_top_k"] == 3
    assert captured["enable_rag"] is False
    assert len(chunks) == 4
    events = [eval_json(chunk[6:]) for chunk in chunks]
    assert [event["type"] for event in events] == ["stage", "progress", "content", "done"]
    assert events[-1]["status"] == "passed"
    for event in events:
        assert event["rewrite_id"] == 123
        assert event["review_id"] == 456


def test_workflow_bridge_forces_single_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """旧工作流桥接应把 max_retries 固定为 1。"""
    from write_agent.api import reviews as reviews_api

    client = TestClient(app)
    style_id = _create_style_for_rewrite_tests()
    fake_job = SimpleNamespace(id=322, status="queued", rewrite_id=123, review_id=456, checkpoint_seq=0)
    captured: dict[str, object] = {}

    def fake_create_job(**kwargs):
        captured.update(kwargs)
        return fake_job, False

    def fake_stream_events(job_id: int, *, from_seq: int = 0, **_kwargs):
        yield {
            "type": "done",
            "stage": "finalize",
            "rewrite_id": 123,
            "review_id": 456,
            "job_id": job_id,
            "seq": 1,
            "status": "passed",
            "passed": True,
        }

    monkeypatch.setattr(reviews_api.workflow_job_service, "create_job", fake_create_job)
    monkeypatch.setattr(reviews_api.workflow_job_service, "stream_events", fake_stream_events)

    with client.stream(
        "POST",
        "/api/reviews/workflow",
        json={
            "source_article": "workflow test",
            "style_id": style_id,
            "target_words": 200,
            "enable_rag": True,
            "rag_top_k": 5,
            "max_retries": 99,
        },
    ) as resp:
        assert resp.status_code == 200
        _ = list(resp.iter_lines())

    assert captured["max_retries"] == 1
    assert captured["rag_top_k"] == 5
    assert captured["enable_rag"] is True


def test_workflow_bridge_runtime_error_yields_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧工作流桥接在流式执行异常时，应输出 type=error 事件。"""
    from write_agent.api import reviews as reviews_api

    client = TestClient(app)
    style_id = _create_style_for_rewrite_tests()
    fake_job = SimpleNamespace(id=323, status="queued", rewrite_id=123, review_id=456, checkpoint_seq=0)

    def fake_create_job(**_kwargs):
        return fake_job, False

    def fake_stream_events(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(reviews_api.workflow_job_service, "create_job", fake_create_job)
    monkeypatch.setattr(reviews_api.workflow_job_service, "stream_events", fake_stream_events)

    with client.stream(
        "POST",
        "/api/reviews/workflow",
        json={
            "source_article": "workflow test",
            "style_id": style_id,
            "target_words": 200,
            "enable_rag": False,
            "max_retries": 1,
        },
    ) as resp:
        assert resp.status_code == 200
        chunks = [line for line in resp.iter_lines() if line and line.startswith("data: ")]

    assert chunks
    event = eval_json(chunks[-1][6:])
    assert event["type"] == "error"
    assert "boom" in event["message"]


def eval_json(raw: str) -> dict:
    import json

    return json.loads(raw)


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


def test_create_manual_cover_rewrite_creates_default_style_once() -> None:
    """手动输入接口应创建/复用默认风格，并返回可用 rewrite_id。"""
    client = TestClient(app)
    title = f"手动标题-{uuid.uuid4().hex[:6]}"
    content = "这是一段用于手动封面测试的正文内容，长度超过二十个字符。\n第二段内容用于验证换行保留。"

    with Session(engine) as session:
        before_count = len(
            session.exec(
                select(WritingStyle).where(WritingStyle.name == "手动输入")
            ).all()
        )

    first = client.post(
        "/api/covers/manual-rewrite",
        json={"title": title, "content": content},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["title"] == title
    assert first_payload["rewrite_id"] > 0
    assert len(first_payload["content_excerpt"]) <= 1200

    with Session(engine) as session:
        count_after_first = len(
            session.exec(
                select(WritingStyle).where(WritingStyle.name == "手动输入")
            ).all()
        )

    second = client.post(
        "/api/covers/manual-rewrite",
        json={"title": title + "-2", "content": content},
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["rewrite_id"] > 0
    assert second_payload["rewrite_id"] != first_payload["rewrite_id"]

    with Session(engine) as session:
        count_after_second = len(
            session.exec(
                select(WritingStyle).where(WritingStyle.name == "手动输入")
            ).all()
        )
        assert count_after_first in {before_count, before_count + 1}
        assert count_after_second == count_after_first

        rewrite = session.get(RewriteRecord, first_payload["rewrite_id"])
        assert rewrite is not None
        assert rewrite.source_article == title
        assert rewrite.status == "completed"
        assert rewrite.final_content == content
        assert rewrite.actual_words == len(content)


def test_create_manual_cover_rewrite_validates_title_and_content() -> None:
    """手动输入接口应校验标题与正文长度。"""
    client = TestClient(app)

    bad_title = client.post(
        "/api/covers/manual-rewrite",
        json={"title": "短", "content": "这是一段明显超过二十个字符的正文内容。"},
    )
    assert bad_title.status_code == 400
    bad_title_data = bad_title.json()
    assert bad_title_data["detail"] == "标题至少 2 个字符"
    assert bad_title_data.get("trace_id")

    bad_content = client.post(
        "/api/covers/manual-rewrite",
        json={"title": "有效标题", "content": "正文太短"},
    )
    assert bad_content.status_code == 400
    bad_content_data = bad_content.json()
    assert bad_content_data["detail"] == "正文至少 20 个字符"
    assert bad_content_data.get("trace_id")


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
