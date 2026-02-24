"""
改写配图占位相关回归测试
"""

from write_agent.services.rewrite_service import RewriteService


def _service_without_init() -> RewriteService:
    """绕过外部依赖初始化，仅测试纯文本辅助逻辑。"""
    return object.__new__(RewriteService)


def test_ensure_image_placeholders_adds_markers_when_missing() -> None:
    service = _service_without_init()
    content = (
        "手机端 Claude Code 的编辑体验，决定了是否愿意在通勤途中继续写作。\n\n"
        "如果操作路径太深，灵感会被来回切换页面打断。"
    )

    rewritten = service._ensure_image_placeholders(content)

    assert rewritten != content
    assert "[配图建议|名称:" in rewritten


def test_ensure_image_placeholders_keeps_existing_markers() -> None:
    service = _service_without_init()
    content = (
        "先说明背景。\n\n"
        "[配图建议|名称:移动端操作示意|说明:展示在手机端执行命令的界面]\n\n"
        "再补充结论。"
    )

    rewritten = service._ensure_image_placeholders(content)
    assert rewritten == content


def test_count_actual_words_excludes_placeholder_text() -> None:
    service = _service_without_init()
    content = "你好世界\n\n[配图建议|名称:测试|说明:描述]"

    assert service._count_actual_words(content) == 4
