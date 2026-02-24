"""
封面风格模板渲染回归测试。
"""
from __future__ import annotations

import os
import sys

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

from write_agent.api.covers import _render_style_prompt


def test_render_style_prompt_injects_content_when_placeholder_present() -> None:
    template = "封面主题：{title}；核心：{content}"
    prompt = _render_style_prompt(
        template=template,
        title="手机端使用 Claude Code",
        content="通过手机给电脑端 CC 发指令",
    )
    assert "手机端使用 Claude Code" in prompt
    assert "通过手机给电脑端 CC 发指令" in prompt


def test_render_style_prompt_appends_context_when_placeholder_missing() -> None:
    template = "请生成吸引眼球的手绘风格公众号封面"
    prompt = _render_style_prompt(
        template=template,
        title="手机端使用 Claude Code",
        content="通过手机给电脑端 CC 发指令",
    )
    assert "文章标题参考" in prompt
    assert "手机端使用 Claude Code" in prompt
    assert "文章核心内容摘要" in prompt
