"""
封面自动 Prompt 生成超时兜底测试。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

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

from write_agent.services import cover_service as cover_service_module


class _SlowLLM:
    def chat(self, messages: list[dict]) -> str:  # noqa: ARG002
        time.sleep(0.2)
        return "slow response"


def test_generate_prompt_falls_back_when_llm_is_slow(monkeypatch) -> None:
    service = cover_service_module.CoverService()
    service.prompt_llm_timeout_seconds = 0.05

    monkeypatch.setattr(
        cover_service_module,
        "get_llm_service",
        lambda: _SlowLLM(),
    )

    prompt = asyncio.run(
        service.generate_prompt(
            content="这是一个足够长的测试文章内容，用于验证封面自动提示词在模型超时场景下会走本地兜底策略。",
            style=None,
            title="测试标题锚点",
        )
    )

    assert "A clean editorial cover illustration" in prompt
    assert "primary title anchor: 测试标题锚点" in prompt
