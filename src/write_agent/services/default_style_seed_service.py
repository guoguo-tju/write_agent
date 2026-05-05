"""
默认写作风格与封面风格初始化服务。

用途：
- 将仓库内维护的默认项写入数据库，便于新用户开箱即用。
- 仅按名称补齐缺失项，不覆盖本地已有同名记录。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import SQLModel, Session, select

from write_agent.core import get_logger
from write_agent.core.database import engine
from write_agent.models.cover_style import CoverStyle
from write_agent.models.writing_style import WritingStyle

logger = get_logger(__name__)

_DEFAULT_WRITING_STYLES_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "defaults"
    / "default_writing_styles.json"
)
_DEFAULT_COVER_STYLES_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "defaults"
    / "default_cover_styles.json"
)


def _load_seed_list(path: Path) -> list[dict[str, Any]]:
    """读取 seed 文件，异常时返回空列表并记日志。"""
    if not path.exists():
        logger.warning("默认 seed 文件不存在，跳过初始化: %s", path)
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        logger.error("默认 seed 文件解析失败: %s, error=%s", path, error)
        return []

    if not isinstance(raw, list):
        logger.error("默认 seed 文件格式错误（应为数组）: %s", path)
        return []

    # 统一保证元素为 dict，忽略无效项
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            result.append(item)
        else:
            logger.warning("忽略非法 seed 元素（非对象）: path=%s", path)
    return result


def _valid_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def bootstrap_default_styles(
    writing_seed_path: Path | None = None,
    cover_seed_path: Path | None = None,
) -> dict[str, int]:
    """
    初始化默认风格数据（幂等）。

    规则：
    - 按 name 去重。
    - 仅插入缺失项，不覆盖同名已有数据。
    """
    writing_seed_path = writing_seed_path or _DEFAULT_WRITING_STYLES_PATH
    cover_seed_path = cover_seed_path or _DEFAULT_COVER_STYLES_PATH

    writing_seed = _load_seed_list(writing_seed_path)
    cover_seed = _load_seed_list(cover_seed_path)

    inserted_writing = 0
    inserted_cover = 0

    SQLModel.metadata.create_all(
        engine,
        tables=[WritingStyle.__table__, CoverStyle.__table__],
    )

    with Session(engine) as session:
        existing_writing_names: set[str] = set()
        for row in session.exec(select(WritingStyle.name)).all():
            if isinstance(row, str):
                existing_writing_names.add(row)
            elif isinstance(row, tuple) and row and isinstance(row[0], str):
                existing_writing_names.add(row[0])

        existing_cover_names: set[str] = set()
        for row in session.exec(select(CoverStyle.name)).all():
            if isinstance(row, str):
                existing_cover_names.add(row)
            elif isinstance(row, tuple) and row and isinstance(row[0], str):
                existing_cover_names.add(row[0])

        now = datetime.now()

        for item in writing_seed:
            name = _valid_text(item.get("name"))
            style_description = _valid_text(item.get("style_description"))
            if not name or not style_description:
                logger.warning("跳过无效写作风格 seed（缺少 name/style_description）: %s", item)
                continue
            if name in existing_writing_names:
                continue

            style = WritingStyle(
                name=name,
                style_description=style_description,
                example_text=item.get("example_text") if isinstance(item.get("example_text"), str) else None,
                tags=item.get("tags") if isinstance(item.get("tags"), str) else None,
                created_at=now,
                updated_at=now,
            )
            session.add(style)
            existing_writing_names.add(name)
            inserted_writing += 1

        for item in cover_seed:
            name = _valid_text(item.get("name"))
            prompt_template = _valid_text(item.get("prompt_template"))
            if not name or not prompt_template:
                logger.warning("跳过无效封面风格 seed（缺少 name/prompt_template）: %s", item)
                continue
            if name in existing_cover_names:
                continue

            style = CoverStyle(
                name=name,
                prompt_template=prompt_template,
                description=item.get("description") if isinstance(item.get("description"), str) else None,
                is_active=bool(item.get("is_active", True)),
                created_at=now,
                updated_at=now,
            )
            session.add(style)
            existing_cover_names.add(name)
            inserted_cover += 1

        if inserted_writing or inserted_cover:
            session.commit()

    return {
        "inserted_writing_styles": inserted_writing,
        "inserted_cover_styles": inserted_cover,
    }
