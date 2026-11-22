"""The scripts in examples/ run against the local fake and send what the contract expects. No network."""

from __future__ import annotations

import re
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

import flexenai._client
from conftest import EXAMPLES, OK_HEADERS, TEST_KEY, Fake, Recorded, Reply
from flexenai import OPERATIONS

DIR = Path(__file__).resolve().parents[1] / "examples"
FOOD = {"id": "sku-10482", "name": "Protein bar hazelnut", "per_100g": {"kcal": 386, "protein_g": 31, "carbs_g": 29, "fat_g": 15}}
FALLBACK: dict[str, Any] = {"catalogFoodsPut": {"saved": [{"id": "sku-10482", "result": "created"}]}, "catalogFoodsList": {"items": [FOOD]}, "catalogFoodsDelete": {"id": "sku-10482", "deleted": True}}


def answer(req: Recorded) -> Reply:
    """Contract example of the operation that matches method and path; tier max is answered as for a live key."""
    if req.json and req.json.get("tier") == "max":
        return Reply(422, {"error": {"code": "tier_unavailable", "message": "max is not available yet", "request_id": "req_t"}}, headers={"X-Request-Id": "req_t"})
    for op, d in OPERATIONS.items():
        if d["method"] == req.method and re.fullmatch(re.sub(r"\{\w+\}", "[^/]+", d["path"]), req.path):
            replay = {"Idempotent-Replayed": "true"} if "idempotency-key" in req.headers else {}
            return Reply(200, FALLBACK.get(op, EXAMPLES[op]["response"]), headers={**OK_HEADERS, **replay})
    return Reply(404, {"error": {"code": "not_found", "message": "fake: no such operation", "request_id": "req_x"}})


@pytest.fixture
def example_env(fake: Fake, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Fake:
    fake.handle(answer)
    monkeypatch.setenv("FLEXEN_API_KEY", TEST_KEY)
    monkeypatch.setattr(flexenai._client, "DEFAULT_BASE_URL", fake.url)
    photo = tmp_path / "lunch.jpg"
    photo.write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01]))
    monkeypatch.setattr(sys, "argv", ["example", str(photo)])
    return fake


def test_every_example_is_covered() -> None:
    assert sorted(p.name for p in DIR.glob("*.py")) == sorted(EXPECTED)


EXPECTED: dict[str, list[str]] = {
    "text.py": ["POST /v1/nutrition/text"],
    "photo.py": ["POST /v1/nutrition/photo"],
    "errors_and_retries.py": ["POST /v1/goals/calculate", "POST /v1/goals/calculate", "POST /v1/nutrition/text"],
    "async_catalog.py": ["POST /v1/catalog/foods", "GET /v1/catalog/foods", "GET /v1/foods/search", "DELETE /v1/catalog/foods/sku-10482"],
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_example_runs(example_env: Fake, capsys: pytest.CaptureFixture[str], name: str) -> None:
    runpy.run_path(str(DIR / name), run_name="__main__")
    assert [f"{r.method} {r.path}" for r in example_env.requests] == EXPECTED[name]
    out = capsys.readouterr().out
    assert out.strip() != ""
    assert TEST_KEY not in out
