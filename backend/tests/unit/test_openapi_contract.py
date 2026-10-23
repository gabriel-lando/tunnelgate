"""The committed OpenAPI document is the contract the frontend types follow."""

from __future__ import annotations

import json
from pathlib import Path

from tunnelgate.app import openapi_schema

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"


def test_openapi_matches_committed_contract() -> None:
    current = json.dumps(openapi_schema(), indent=2, sort_keys=True) + "\n"
    assert CONTRACT.exists(), "run: uv run python scripts/export_openapi.py"
    assert CONTRACT.read_text() == current, (
        "API changed: run `uv run python scripts/export_openapi.py` and update frontend/src/lib/types.ts"
    )
