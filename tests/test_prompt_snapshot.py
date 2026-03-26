"""
Prompt 快照回归测试（固定样本）
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

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

from sqlmodel import Session

from write_agent.models import RewriteRecord, WritingStyle


SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
BASE_SNAPSHOT_FILE = SNAPSHOT_DIR / "rewrite_prompt_base.txt"
REVISION_SNAPSHOT_FILE = SNAPSHOT_DIR / "rewrite_prompt_revision.txt"


class _CaptureLLM:
    def __init__(self):
        self.prompts: list[str] = []

    def stream(self, *, messages, system_prompt=None):
        self.prompts.append(messages[0]["content"])
        yield "这是一段用于快照回归的测试输出。"


def _normalize(value: str) -> str:
    return (value or "").strip().replace("\r\n", "\n")


def _prepare_rewrite_context(test_db):
    import write_agent.services.rewrite_service as rs

    rs.engine = test_db
    service = rs.RewriteService()
    capture_llm = _CaptureLLM()
    service.llm_service = capture_llm

    with Session(test_db) as session:
        style = WritingStyle(
            name="prompt-snapshot-style",
            style_description='{"persona":"测试写作者","overall_summary":"固定快照"}',
            tags="snapshot",
        )
        session.add(style)
        session.commit()
        session.refresh(style)

        rewrite = RewriteRecord(
            source_article="这是一段固定原文，用于 Prompt 快照回归测试。",
            style_id=style.id,
            target_words=200,
            enable_rag=False,
            rag_top_k=3,
            status="running",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(rewrite)
        session.commit()
        session.refresh(rewrite)
        rewrite_id = rewrite.id

    return service, capture_llm, rewrite_id


def test_rewrite_base_prompt_snapshot(test_db):
    service, capture_llm, rewrite_id = _prepare_rewrite_context(test_db)
    _ = list(service.rewrite(rewrite_id))

    assert capture_llm.prompts, "应捕获到 rewrite base prompt"
    current_prompt = _normalize(capture_llm.prompts[0])
    expected_prompt = _normalize(BASE_SNAPSHOT_FILE.read_text(encoding="utf-8"))
    assert current_prompt == expected_prompt


def test_rewrite_revision_prompt_snapshot(test_db):
    service, capture_llm, rewrite_id = _prepare_rewrite_context(test_db)
    _ = list(
        service.rewrite(
            rewrite_id,
            revision_base_content="这是第一轮改写稿。",
            review_feedback="请减少AI味，优化节奏并增强具体场景。",
        )
    )

    assert capture_llm.prompts, "应捕获到 rewrite revision prompt"
    current_prompt = _normalize(capture_llm.prompts[0])
    expected_prompt = _normalize(REVISION_SNAPSHOT_FILE.read_text(encoding="utf-8"))
    assert current_prompt == expected_prompt
