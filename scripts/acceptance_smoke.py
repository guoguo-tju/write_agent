"""
Acceptance smoke checks for write-agent.

Usage:
  DATABASE_URL=sqlite:///./data/acceptance_write_agent.db PYTHONPATH=src .venv/bin/python scripts/acceptance_smoke.py
  DATABASE_URL=sqlite:///./data/acceptance_write_agent.db PYTHONPATH=src .venv/bin/python scripts/acceptance_smoke.py --with-external
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Callable

from fastapi.testclient import TestClient


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _ok(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, passed=True, detail=detail)


def _fail(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, passed=False, detail=detail)


def run_check(name: str, fn: Callable[[], CheckResult]) -> CheckResult:
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - smoke tool
        return _fail(name, f"exception: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run acceptance smoke checks.")
    parser.add_argument(
        "--with-external",
        action="store_true",
        help="Run checks that call external LLM/Embedding/Image APIs.",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL", "sqlite:///./data/acceptance_write_agent.db")
    os.environ["DATABASE_URL"] = database_url
    os.environ.setdefault("NO_PROXY", "*")

    from sqlmodel import SQLModel, create_engine
    from write_agent.main import app

    # Ensure tables exist for the acceptance database.
    engine = create_engine(database_url, echo=False)
    SQLModel.metadata.create_all(engine)

    client = TestClient(app)
    results: list[CheckResult] = []

    def check_root() -> CheckResult:
        resp = client.get("/")
        if resp.status_code != 200:
            return _fail("GET /", f"status={resp.status_code}, body={resp.text[:200]}")
        return _ok("GET /", "healthy")

    def check_health() -> CheckResult:
        resp = client.get("/health")
        if resp.status_code != 200:
            return _fail("GET /health", f"status={resp.status_code}, body={resp.text[:200]}")
        return _ok("GET /health", "healthy")

    def check_material_compat() -> CheckResult:
        payload = {
            "content": "acceptance smoke material",
            "source": "https://example.com/smoke",
            "tags": "smoke,compat",
        }
        resp = client.post("/api/materials", json=payload)
        if resp.status_code != 200:
            return _fail(
                "POST /api/materials",
                f"status={resp.status_code}, body={resp.text[:300]}",
            )
        data = resp.json()
        if not data.get("title") or data.get("source_url") != payload["source"]:
            return _fail("POST /api/materials", f"unexpected response: {json.dumps(data)[:300]}")
        return _ok(
            "POST /api/materials",
            f"title={data.get('title')}, embedding_status={data.get('embedding_status')}",
        )

    def check_cover_stream_compat() -> CheckResult:
        # rewrite_id=999 is expected to fail, but stream contract should remain valid.
        lines: list[str] = []
        with client.stream("GET", "/api/covers/stream?rewrite_id=999") as resp:
            if resp.status_code != 200:
                return _fail("GET /api/covers/stream", f"status={resp.status_code}")
            for line in resp.iter_lines():
                if line:
                    lines.append(line)
                if len(lines) >= 2:
                    break

        if len(lines) < 2:
            return _fail("GET /api/covers/stream", f"too few events: {lines}")
        if '"type": "start"' not in lines[0] or '"type": "error"' not in lines[1]:
            return _fail("GET /api/covers/stream", f"unexpected events: {lines}")
        return _ok("GET /api/covers/stream", "start/error event sequence validated")

    def check_style_extract_external() -> CheckResult:
        payload = {
            "articles": ["smoke test article for style extraction"],
            "style_name": "smoke-style",
            "tags": "smoke",
        }
        resp = client.post("/api/styles/extract", json=payload)
        if resp.status_code != 200:
            return _fail(
                "POST /api/styles/extract",
                f"status={resp.status_code}, body={resp.text[:300]}",
            )
        data = resp.json()
        return _ok(
            "POST /api/styles/extract",
            f"id={data.get('id')}, style_description_len={len(data.get('style_description') or '')}",
        )

    # Always-run checks.
    results.append(run_check("GET /", check_root))
    results.append(run_check("GET /health", check_health))
    results.append(run_check("POST /api/materials", check_material_compat))
    results.append(run_check("GET /api/covers/stream", check_cover_stream_compat))

    # Optional external checks.
    if args.with_external:
        results.append(run_check("POST /api/styles/extract", check_style_extract_external))

    passed = sum(1 for item in results if item.passed)
    failed = len(results) - passed

    print("\nAcceptance Smoke Report")
    print("=" * 24)
    for item in results:
        status = "PASS" if item.passed else "FAIL"
        print(f"[{status}] {item.name}: {item.detail}")

    print("-" * 24)
    print(f"passed={passed}, failed={failed}, total={len(results)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

