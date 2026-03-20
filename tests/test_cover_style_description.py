"""
封面风格描述压缩测试。
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

from write_agent.services.cover_service import CoverService


def test_compress_style_description_prefers_key_fields() -> None:
    raw = """
    {
      "overall_summary": "科技博主风格，注重实用。",
      "persona": "像朋友一样解释技术。",
      "paragraph_templates": {"观点段": "xxxx"}
    }
    """
    compressed = CoverService._compress_style_description(raw, max_chars=120)
    assert "overall_summary:" in compressed
    assert "persona:" in compressed
    assert "paragraph_templates" not in compressed
    assert len(compressed) <= 123
