"""默认风格 seed 初始化回归测试。"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

# 与现有回归测试保持一致：显式挂载 venv site-packages 与 src 路径
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

from sqlmodel import SQLModel, Session, create_engine, select

from write_agent.models.cover_style import CoverStyle
from write_agent.models.writing_style import WritingStyle
from write_agent.services import default_style_seed_service as seed_service


def _create_test_engine(tmp_path) -> object:
    db_path = tmp_path / "seed_test.db"
    test_engine = create_engine(f"sqlite:///{db_path}", echo=False)
    SQLModel.metadata.create_all(
        test_engine,
        tables=[WritingStyle.__table__, CoverStyle.__table__],
    )
    return test_engine


def test_bootstrap_default_styles_is_idempotent(tmp_path, monkeypatch) -> None:
    """初始化应只补齐缺失项，重复执行不重复写入。"""
    test_engine = _create_test_engine(tmp_path)
    monkeypatch.setattr(seed_service, "engine", test_engine)

    writing_seed_path = tmp_path / "writing.json"
    cover_seed_path = tmp_path / "cover.json"
    writing_seed_path.write_text(
        json.dumps(
            [
                {
                    "name": "默认写作风格A",
                    "style_description": "{\"persona\":\"A\"}",
                    "example_text": "示例A",
                    "tags": "默认,A",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cover_seed_path.write_text(
        json.dumps(
            [
                {
                    "name": "默认封面风格A",
                    "prompt_template": "请生成 {title}",
                    "description": "desc",
                    "is_active": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = seed_service.bootstrap_default_styles(
        writing_seed_path=writing_seed_path,
        cover_seed_path=cover_seed_path,
    )
    assert first == {"inserted_writing_styles": 1, "inserted_cover_styles": 1}

    second = seed_service.bootstrap_default_styles(
        writing_seed_path=writing_seed_path,
        cover_seed_path=cover_seed_path,
    )
    assert second == {"inserted_writing_styles": 0, "inserted_cover_styles": 0}

    with Session(test_engine) as session:
        writing_rows = session.exec(select(WritingStyle)).all()
        cover_rows = session.exec(select(CoverStyle)).all()

    assert len(writing_rows) == 1
    assert writing_rows[0].name == "默认写作风格A"
    assert writing_rows[0].style_description == "{\"persona\":\"A\"}"
    assert writing_rows[0].example_text == "示例A"
    assert writing_rows[0].tags == "默认,A"

    assert len(cover_rows) == 1
    assert cover_rows[0].name == "默认封面风格A"
    assert cover_rows[0].prompt_template == "请生成 {title}"
    assert cover_rows[0].description == "desc"
    assert cover_rows[0].is_active is True


def test_bootstrap_default_styles_does_not_override_existing(tmp_path, monkeypatch) -> None:
    """同名记录已存在时，不应被 seed 覆盖。"""
    test_engine = _create_test_engine(tmp_path)
    monkeypatch.setattr(seed_service, "engine", test_engine)

    with Session(test_engine) as session:
        session.add(
            WritingStyle(
                name="默认写作风格A",
                style_description="{\"persona\":\"existing\"}",
                example_text="existing example",
                tags="existing",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        session.add(
            CoverStyle(
                name="默认封面风格A",
                prompt_template="existing prompt",
                description="existing desc",
                is_active=False,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
        )
        session.commit()

    writing_seed_path = tmp_path / "writing.json"
    cover_seed_path = tmp_path / "cover.json"
    writing_seed_path.write_text(
        json.dumps(
            [
                {
                    "name": "默认写作风格A",
                    "style_description": "{\"persona\":\"seed\"}",
                    "example_text": "seed example",
                    "tags": "seed",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cover_seed_path.write_text(
        json.dumps(
            [
                {
                    "name": "默认封面风格A",
                    "prompt_template": "seed prompt",
                    "description": "seed desc",
                    "is_active": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = seed_service.bootstrap_default_styles(
        writing_seed_path=writing_seed_path,
        cover_seed_path=cover_seed_path,
    )
    assert result == {"inserted_writing_styles": 0, "inserted_cover_styles": 0}

    with Session(test_engine) as session:
        writing = session.exec(
            select(WritingStyle).where(WritingStyle.name == "默认写作风格A")
        ).first()
        cover = session.exec(
            select(CoverStyle).where(CoverStyle.name == "默认封面风格A")
        ).first()

    assert writing is not None
    assert writing.style_description == "{\"persona\":\"existing\"}"
    assert writing.example_text == "existing example"
    assert writing.tags == "existing"

    assert cover is not None
    assert cover.prompt_template == "existing prompt"
    assert cover.description == "existing desc"
    assert cover.is_active is False
