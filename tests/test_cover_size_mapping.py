"""
封面尺寸与比例映射测试。
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

from write_agent.api.covers import (
    _apply_aspect_ratio_to_prompt,
    _resolve_generation_size,
    _strip_prompt_control_meta,
)


def test_ratio_selection_maps_to_stable_generation_size() -> None:
    assert _resolve_generation_size("2.35:1") == "3072x1308"
    assert _resolve_generation_size("1:1") == "2048x2048"
    assert _resolve_generation_size("9:16") == "1440x2560"
    assert _resolve_generation_size("3:4") == "1728x2304"


def test_legacy_size_kept_for_generation() -> None:
    assert _resolve_generation_size("1k") == "1k"
    assert _resolve_generation_size("2k") == "2k"
    assert _resolve_generation_size("4k") == "4k"


def test_ratio_prompt_not_injected_to_text() -> None:
    prompt = _apply_aspect_ratio_to_prompt("base prompt", "2.35:1")
    assert prompt == "base prompt"


def test_strip_prompt_control_meta_lines() -> None:
    raw = """请根据提供的内容创建公众号封面图
- 手绘插画风格，比例为 2.35:1（公众号封面标准尺寸）
- 主视觉元素居中或偏左
- 2.35:1版
"""
    cleaned = _strip_prompt_control_meta(raw)
    assert "公众号" not in cleaned
    assert "2.35:1" not in cleaned
    assert "主视觉元素居中或偏左" in cleaned
