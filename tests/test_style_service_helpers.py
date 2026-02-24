"""
风格提取辅助逻辑测试
"""

import pytest

from write_agent.services.style_service import StyleExtractionService


def test_clean_style_json_supports_markdown_fence() -> None:
    service = StyleExtractionService()
    raw = """```json
{"persona":"测试","overall_summary":"总结"}
```"""

    cleaned = service._clean_style_json(raw)
    assert cleaned == '{"persona":"测试","overall_summary":"总结"}'


def test_combine_articles_filters_empty_entries() -> None:
    service = StyleExtractionService()
    combined = service._combine_articles(["  第一篇  ", "", "   ", "第二篇"])

    assert combined == "第一篇\n\n---\n\n第二篇"


def test_clean_style_json_raises_on_invalid_payload() -> None:
    service = StyleExtractionService()

    with pytest.raises(ValueError):
        service._clean_style_json("没有任何 JSON 结构")
