from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from conftest import EXAMPLES, OK_HEADERS, TEST_KEY, Fake, Reply
from flexenai import DEFAULT_TIER, NOT_AVAILABLE, OPERATIONS, TIER_IDS, TIERS, AsyncFlexen, Flexen, InvalidInputError, TierUnavailableError

ex = EXAMPLES
RECIPE = {"id": "r1", "name": "Linsensuppe", "per_100g": {"kcal": 92, "protein_g": 5.4, "carbs_g": 11.8, "fat_g": 2.0}}

#: One call per contract operation. test_every_operation_has_a_call fails when the contract gains an operation.
CALLS: dict[str, Callable[[Flexen], Any]] = {
    "nutritionText": lambda c: c.nutrition.text(**ex["nutritionText"]["request"]),
    "nutritionPhoto": lambda c: c.nutrition.photo(image_base64="aGVsbG8=", lang="de", tier="light"),
    "nutritionCorrect": lambda c: c.nutrition.correct(**ex["nutritionCorrect"]["request"]),
    "foodsSearch": lambda c: c.foods.search(**ex["foodsSearch"]["params"]),
    "foodsBarcode": lambda c: c.foods.barcode(**ex["foodsBarcode"]["params"]),
    "goalsCalculate": lambda c: c.goals.calculate(**ex["goalsCalculate"]["request"]),
    "catalogFoodsPut": lambda c: c.catalog.foods.upsert(**ex["catalogFoodsPut"]["request"]),
    "catalogFoodsList": lambda c: c.catalog.foods.list(**ex["catalogFoodsList"]["params"]),
    "catalogFoodsGet": lambda c: c.catalog.foods.get("rezept-linsensuppe"),
    "catalogFoodsDelete": lambda c: c.catalog.foods.delete("sku-10482"),
    "catalogRecipesPut": lambda c: c.catalog.recipes.upsert([RECIPE]),
    "catalogRecipesList": lambda c: c.catalog.recipes.list(),
    "catalogRecipesGet": lambda c: c.catalog.recipes.get("r1"),
    "catalogRecipesDelete": lambda c: c.catalog.recipes.delete("r1"),
    "catalogDelete": lambda c: c.catalog.delete_all(),
    "catalogExport": lambda c: c.catalog.export(),
    "accountBalance": lambda c: c.account.balance(),
    "accountUsage": lambda c: c.account.usage(ex["accountUsage"]["params"]["from"], ex["accountUsage"]["params"]["to"]),
}

FALLBACK_RESPONSES: dict[str, Any] = {
    "catalogRecipesPut": {"saved": [{"id": "r1", "result": "created"}]},
    "catalogRecipesList": {"items": [RECIPE]},
    "catalogRecipesGet": RECIPE,
    "catalogRecipesDelete": {"id": "r1", "deleted": True},
    "catalogDelete": {"deleted_foods": 2, "deleted_recipes": 1},
    "catalogExport": {"foods": [], "recipes": [RECIPE]},
}


def expected_path(op: str) -> str:
    ids = {"catalogFoodsGet": "rezept-linsensuppe", "catalogFoodsDelete": "sku-10482"}
    path = OPERATIONS[op]["path"]
    if "{id}" in path:
        return path.replace("{id}", ids.get(op, "r1"))
    for name in ("code",):
        path = path.replace("{" + name + "}", str(ex[op]["params"].get(name)))
    return path


def without_nulls(v: Any) -> Any:
    """The contract's examples spell out null fields (name_lang: null); the dump above leaves None out."""
    if isinstance(v, dict):
        return {k: without_nulls(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [without_nulls(x) for x in v]
    return v


def test_every_operation_has_a_call() -> None:
    assert set(CALLS) == set(OPERATIONS)


@pytest.mark.parametrize("op", sorted(OPERATIONS))
def test_operation(fake: Fake, op: str) -> None:
    response = ex[op]["response"] if ex[op]["response"] is not None else FALLBACK_RESPONSES[op]
    fake.queue(Reply(200, response, headers=OK_HEADERS))
    with Flexen(TEST_KEY, base_url=fake.url, max_retries=0) as c:
        res = CALLS[op](c)
    assert len(fake.requests) == 1
    req = fake.requests[0]
    assert req.method == OPERATIONS[op]["method"]
    assert req.headers["authorization"] == f"Bearer {TEST_KEY}"
    assert req.path == expected_path(op)
    for name, where, _ in OPERATIONS[op]["params"]:
        if where == "query" and name in ex[op]["params"]:
            assert req.query[name] == str(ex[op]["params"][name])
    if OPERATIONS[op]["request"] is not None:
        assert req.headers["content-type"] == "application/json"
        if ex[op]["request"] is not None and op != "nutritionPhoto":
            assert req.json == ex[op]["request"]
    else:
        assert req.body == b""
    data = res.data.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert json.loads(json.dumps(data)) == without_nulls(response)
    assert res.status_code == 200
    assert res.request_id == "req_test_1"
    assert res.credits_charged == 1
    assert res.credits_remaining == 18341


def test_custom_foods_example(fake: Fake) -> None:
    fake.queue(Reply(200, ex["nutritionText"]["responseExamples"]["custom_foods"], headers=OK_HEADERS))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        res = c.nutrition.text(**ex["nutritionText"]["requestExamples"]["custom_foods"])
    assert fake.requests[0].json == ex["nutritionText"]["requestExamples"]["custom_foods"]
    assert res.data.items[0].source == "customer_inline"


def test_missing_and_bad_headers_are_none(fake: Fake) -> None:
    fake.queue(Reply(200, {"credits_remaining": 5}, headers={"X-Credits-Charged": "abc"}))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        res = c.account.balance()
    assert (res.credits_charged, res.credits_remaining, res.request_id) == (None, None, None)
    assert res.data.credits_remaining == 5


def test_path_parameters_are_encoded(fake: Fake) -> None:
    fake.queue(Reply(200, {"id": "a/b c", "deleted": True}, headers=OK_HEADERS))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        c.catalog.foods.delete("a/b c")
    assert fake.requests[0].url == "/v1/catalog/foods/a%2Fb%20c"


def test_unset_query_parameters_are_left_out(fake: Fake) -> None:
    fake.queue(Reply(200, {"items": []}, headers=OK_HEADERS))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        c.catalog.foods.list()
    assert fake.requests[0].url == "/v1/catalog/foods"


def test_list_parameters_go_comma_separated(fake: Fake) -> None:
    fake.queue(Reply(200, ex["foodsSearch"]["response"], headers=OK_HEADERS))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        c.foods.search("Skyr", sources=["customer_catalog", "usda_fdc"], exclude_sources=["open_food_facts"], nutrients="eu7")
    assert fake.requests[0].query == {"q": "Skyr", "sources": "customer_catalog,usda_fdc", "exclude_sources": "open_food_facts", "nutrients": "eu7"}


def test_text_settings_are_sent_unchanged(fake: Fake) -> None:
    settings: dict[str, Any] = {
        "lang": "sv", "energy_unit": "kj", "nutrients": "eu7", "provenance": "field", "hint": "ohne Zucker", "known_grams": 250.0,
        "country": "SE", "meal": "breakfast", "review_threshold": 0.4, "sources": ["usda_fdc", "model"], "profile": "app-se",
    }
    fake.queue(Reply(200, ex["nutritionText"]["response"], headers=OK_HEADERS))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        c.nutrition.text("Skyr mit Beeren", **settings)
    assert fake.requests[0].json == {"text": "Skyr mit Beeren", **settings}


def test_model_false_is_sent(fake: Fake) -> None:
    fake.queue(Reply(200, ex["nutritionText"]["response"], headers=OK_HEADERS))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        c.nutrition.text("Skyr", model=False, known_grams=150, sources=["usda_fdc"])
    assert fake.requests[0].json["model"] is False


def test_idempotent_replay_is_reported(fake: Fake) -> None:
    fake.queue(Reply(200, ex["goalsCalculate"]["response"], headers={**OK_HEADERS, "X-Credits-Charged": "0", "Idempotent-Replayed": "true"}))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        res = c.goals.calculate(**ex["goalsCalculate"]["request"], idempotency_key="k-1")
    assert fake.requests[0].headers["idempotency-key"] == "k-1"
    assert (res.idempotent_replayed, res.credits_charged) == (True, 0)


def test_max_is_in_the_contract_but_not_available_yet() -> None:
    assert (DEFAULT_TIER, TIER_IDS) == ("light", ("light", "max"))
    for op in ("nutritionText", "nutritionPhoto"):
        states = {t["id"]: t["state"] for t in TIERS[op]}
        assert states == {"light": "launch", "max": "later"}


def test_max_with_a_live_key_raises_tier_unavailable(fake: Fake) -> None:
    fake.queue(Reply(422, {"error": {"code": "tier_unavailable", "message": "max is not available yet", "request_id": "req_t"}}, headers={"X-Request-Id": "req_t"}))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        with pytest.raises(TierUnavailableError):
            c.nutrition.text("Apfel", tier="max")
    assert fake.requests[0].json["tier"] == "max"


def test_invalid_input_is_rejected_before_sending(fake: Fake) -> None:
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        with pytest.raises(InvalidInputError):
            c.catalog.foods.get("")
        with pytest.raises(InvalidInputError):
            c.goals.calculate(sex="robot", weight_kg=70, height_cm=180, age=30, activity_level="active", goal="maintain")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            c.nutrition.text("x", unknown_field=1)  # type: ignore[call-arg]
    assert fake.requests == []


def test_catalog_iterate_follows_next_cursor(fake: Fake) -> None:
    def food(i: str) -> dict[str, Any]:
        return {"id": i, "name": i, "per_100g": {"kcal": 1, "protein_g": 0, "carbs_g": 0, "fat_g": 0}}

    fake.queue(
        Reply(200, {"items": [food("a"), food("b")], "next_cursor": "c1"}, headers=OK_HEADERS),
        Reply(200, {"items": [food("c")]}, headers=OK_HEADERS),
    )
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        ids = [f.id for f in c.catalog.foods.iterate(q="x")]
    assert ids == ["a", "b", "c"]
    assert [r.url for r in fake.requests] == ["/v1/catalog/foods?q=x", "/v1/catalog/foods?q=x&cursor=c1"]


def test_not_available_endpoints_are_the_later_ones() -> None:
    paths = {o["path"] for o in OPERATIONS.values()}
    assert NOT_AVAILABLE
    for e in NOT_AVAILABLE:
        assert e["state"] == "later"
        assert e["path"] not in paths


@pytest.mark.anyio
async def test_async_client_calls(fake: Fake) -> None:
    def food(i: str) -> dict[str, Any]:
        return {"id": i, "name": i, "per_100g": {"kcal": 1, "protein_g": 0, "carbs_g": 0, "fat_g": 0}}

    fake.queue(
        Reply(200, ex["nutritionText"]["response"], headers=OK_HEADERS),
        Reply(200, ex["foodsSearch"]["response"], headers=OK_HEADERS),
        Reply(200, {"items": [food("a")], "next_cursor": "n"}, headers=OK_HEADERS),
        Reply(200, {"items": [food("b")]}, headers=OK_HEADERS),
        Reply(200, ex["accountUsage"]["response"], headers=OK_HEADERS),
    )
    async with AsyncFlexen(TEST_KEY, base_url=fake.url) as c:
        text = await c.nutrition.text("2 Scheiben Vollkornbrot", lang="de")
        search = await c.foods.search("apple", lang="de")
        ids = [f.id async for f in c.catalog.foods.iterate()]
        usage = await c.account.usage("2026-11-20", "2026-11-21")
    assert text.data.total.kcal.value == 477
    assert text.credits_remaining == 18341
    assert search.data.results[0].license == "CC0"
    assert ids == ["a", "b"]
    assert usage.data.from_ == "2026-11-20"
    assert [r.url for r in fake.requests] == [
        "/v1/nutrition/text",
        "/v1/foods/search?q=apple&lang=de",
        "/v1/catalog/foods",
        "/v1/catalog/foods?cursor=n",
        "/v1/account/usage?from=2026-11-20&to=2026-11-21",
    ]
