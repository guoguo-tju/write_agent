"""
封面本地持久化测试。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

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


class _FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 8192):
        _ = chunk_size
        yield self.payload


def test_persist_image_locally_writes_file_and_returns_local_media_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = CoverService()
    service.cover_storage_dir = tmp_path
    service.cover_media_url_prefix = "/media/covers"

    def _fake_get(url: str, timeout: int, stream: bool):  # noqa: ANN001
        assert url == "https://example.com/demo.png?token=abc"
        assert timeout == 120
        assert stream is True
        return _FakeResponse(b"fake-image-bytes")

    monkeypatch.setattr("write_agent.services.cover_service.requests.get", _fake_get)

    local_url = service.persist_image_locally(
        source_url="https://example.com/demo.png?token=abc",
        cover_id=100,
        rewrite_id=9,
    )

    assert local_url.startswith("/media/covers/")
    assert local_url.endswith(".png")

    relative_path = local_url.removeprefix("/media/covers/")
    local_file = tmp_path / relative_path
    assert local_file.exists()
    assert local_file.read_bytes() == b"fake-image-bytes"


def test_persist_image_locally_uses_jpg_when_extension_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = CoverService()
    service.cover_storage_dir = tmp_path
    service.cover_media_url_prefix = "/media/covers"

    monkeypatch.setattr(
        "write_agent.services.cover_service.requests.get",
        lambda *args, **kwargs: _FakeResponse(b"img"),  # noqa: ARG005
    )

    local_url = service.persist_image_locally(
        source_url="https://example.com/no-extension",
        cover_id=101,
        rewrite_id=10,
    )

    assert local_url.endswith(".jpg")
