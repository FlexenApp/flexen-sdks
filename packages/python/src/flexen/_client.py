"""Sync (Flexen) and async (AsyncFlexen) clients of the Flexen API."""

from __future__ import annotations

import json
import time
from datetime import date
from typing import Any, AsyncIterator, Iterator, Literal, Mapping, Sequence

import anyio
import anyio.to_thread
import httpx

from ._base import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    RETRY_STATUSES,
    CallOptions,
    Deadline,
    FlexenResponse,
    RetryConfig,
    build_body,
    build_url,
    compute_retry_delay,
    error_from_response,
    key_prefix,
    operation,
    parse_success,
    request_headers,
    resolve_api_key,
)
from ._errors import APIConnectionError, RequestTimeoutError
from ._generated import OPERATIONS
from ._photo import ImageBytes, ImagePath, to_image_base64

from ._generated import (
        AccountBalance,
        AccountUsage,
        CatalogCleared,
        CatalogDeleted,
        CatalogExport,
        CatalogFood,
        CatalogFoodList,
        CatalogRecipe,
        CatalogRecipeList,
        CatalogSaveResponse,
        CorrectItemInput,
        CustomFood,
        FoodSearchResponse,
        GoalsResponse,
        NutritionCorrectResponse,
        NutritionPhotoResponse,
        NutritionTextResponse,
        ProductResponse,
    )

Lang = Literal["de", "en", "fr", "es", "it", "nl", "pl", "pt", "sv", "da", "nb", "fi"]
#: "light" is the default. "max" is not available yet: with a live key the API answers 422 tier_unavailable (TierUnavailableError).
Tier = Literal["light", "max"]
EnergyUnit = Literal["kcal", "kj"]
MassUnit = Literal["g", "oz"]
VolumeUnit = Literal["ml"]
Nutrients = Literal["macros", "eu7", "full"]
Provenance = Literal["item", "field"]
Meal = Literal["breakfast", "lunch", "dinner", "snack"]
SourceId = Literal["customer_inline", "customer_catalog", "bls", "ciqual", "fineli", "livsmedelsverket", "usda_fdc", "open_food_facts", "model"]
Headers = Mapping[str, str]


def _day(v: str | date) -> str:
    return v.isoformat() if isinstance(v, date) else v


def _opts(idempotency_key: str | None, timeout: float | None, max_retries: int | None, extra_headers: Headers | None) -> CallOptions:
    return CallOptions(idempotency_key=idempotency_key, timeout=timeout, max_retries=max_retries, extra_headers=extra_headers)


class _ClientBase:
    def __init__(
        self,
        api_key: str | None,
        base_url: str | None,
        timeout: float,
        max_retries: int,
        retry: RetryConfig | None,
        default_headers: Headers | None,
    ) -> None:
        self._api_key = resolve_api_key(api_key)
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry = retry or RetryConfig()
        self._default_headers = dict(default_headers or {})

    @property
    def api_key_prefix(self) -> str:
        """Key prefix only (for example "flx_live_AbC…"), for debugging. The full key is never shown."""
        return key_prefix(self._api_key)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r}, api_key={self.api_key_prefix!r}, timeout={self.timeout}, max_retries={self.max_retries})"

    def __getstate__(self) -> None:
        raise TypeError("Flexen clients cannot be pickled (they hold the API key).")

    def _prepare(self, op: str, params: Mapping[str, Any] | None, body: Mapping[str, Any] | None, opts: CallOptions) -> tuple[str, str, dict[str, str], bytes | None, Deadline, int]:
        url = build_url(self.base_url, op, params)
        content = json.dumps(build_body(op, body or {})).encode("utf-8") if OPERATIONS[op]["request"] is not None else None
        headers = request_headers(self._api_key, self._default_headers, op, opts)
        deadline = Deadline(opts.timeout if opts.timeout is not None else self.timeout)
        max_retries = opts.max_retries if opts.max_retries is not None else self.max_retries
        return OPERATIONS[op]["method"], url, headers, content, deadline, max_retries


# ======================================================================= sync


class Flexen(_ClientBase):
    """Client of the Flexen API.

    >>> client = Flexen()  # reads FLEXEN_API_KEY
    >>> res = client.nutrition.text("2 eggs and a toast")
    >>> res.data.total.kcal.value, res.credits_remaining
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry: RetryConfig | None = None,
        default_headers: Headers | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, retry, default_headers)
        self._own_http = http_client is None
        self._http = http_client or httpx.Client(follow_redirects=False)
        self.nutrition = Nutrition(self)
        self.foods = Foods(self)
        self.goals = Goals(self)
        self.catalog = Catalog(self)
        self.account = Account(self)

    def close(self) -> None:
        if self._own_http:
            self._http.close()

    def __enter__(self) -> Flexen:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _call(self, op: str, *, params: Mapping[str, Any] | None = None, body: Mapping[str, Any] | None = None, opts: CallOptions) -> FlexenResponse[Any]:
        method, url, headers, content, deadline, max_retries = self._prepare(op, params, body, opts)
        attempt = 0
        while True:
            remaining = deadline.remaining()
            if remaining <= 0:
                raise RequestTimeoutError(f"No response within {deadline.seconds} s; the call was cancelled.")
            try:
                res = self._http.request(method, url, headers=headers, content=content, timeout=remaining)
            except httpx.TimeoutException as e:
                raise RequestTimeoutError(f"No response within {deadline.seconds} s; the call was cancelled.") from e
            except httpx.HTTPError as e:
                raise APIConnectionError(f"Could not reach {self.base_url}: {e}") from e
            if res.is_success:
                return parse_success(op, res)
            err = error_from_response(res)
            if res.status_code not in RETRY_STATUSES or attempt >= max_retries:
                raise err
            delay = compute_retry_delay(attempt, err.retry_after_seconds, self.retry)
            if delay is None:
                raise err
            if delay >= deadline.remaining():
                raise RequestTimeoutError(f"No usable response within {deadline.seconds} s; the last one was {err}.") from err
            time.sleep(delay)
            attempt += 1


class Nutrition:
    def __init__(self, client: Flexen) -> None:
        self._c = client

    @operation("nutritionText")
    def text(
        self,
        text: str,
        *,
        lang: Lang | None = None,
        energy_unit: EnergyUnit | None = None,
        mass_unit: MassUnit | None = None,
        volume_unit: VolumeUnit | None = None,
        nutrients: Nutrients | None = None,
        provenance: Provenance | None = None,
        hint: str | None = None,
        known_grams: float | None = None,
        country: str | None = None,
        meal: Meal | None = None,
        venue: str | None = None,
        review_threshold: float | None = None,
        sources: Sequence[SourceId] | None = None,
        exclude_sources: Sequence[SourceId] | None = None,
        model: str | Literal[False] | None = None,
        custom_foods: Sequence[CustomFood | Mapping[str, Any]] | None = None,
        instructions: str | None = None,
        chain_version: str | None = None,
        tier: Tier | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[NutritionTextResponse]:
        """POST /v1/nutrition/text: free text to amount, calories and macros.

        tier: "light" is the default; "max" is not available yet (422 tier_unavailable, TierUnavailableError).
        model=False works without the model, from the sources only. hint, instructions, country, meal, venue and
        known_grams make the response "not measured" (measured: false, unmeasured_because).
        """
        body = {"text": text, "lang": lang, "energy_unit": energy_unit, "mass_unit": mass_unit, "volume_unit": volume_unit, "nutrients": nutrients, "provenance": provenance, "hint": hint, "known_grams": known_grams, "country": country, "meal": meal, "venue": venue, "review_threshold": review_threshold, "sources": sources, "exclude_sources": exclude_sources, "model": model, "custom_foods": custom_foods, "instructions": instructions, "chain_version": chain_version, "tier": tier, "profile": profile}
        return self._c._call("nutritionText", body=body, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("nutritionPhoto", extra=("image_path", "image_bytes"))
    def photo(
        self,
        *,
        image_path: ImagePath | None = None,
        image_bytes: ImageBytes | None = None,
        image_base64: str | None = None,
        lang: Lang | None = None,
        energy_unit: EnergyUnit | None = None,
        mass_unit: MassUnit | None = None,
        volume_unit: VolumeUnit | None = None,
        nutrients: Nutrients | None = None,
        provenance: Provenance | None = None,
        hint: str | None = None,
        known_grams: float | None = None,
        country: str | None = None,
        meal: Meal | None = None,
        venue: str | None = None,
        review_threshold: float | None = None,
        sources: Sequence[SourceId] | None = None,
        exclude_sources: Sequence[SourceId] | None = None,
        model: str | None = None,
        custom_foods: Sequence[CustomFood | Mapping[str, Any]] | None = None,
        instructions: str | None = None,
        chain_version: str | None = None,
        tier: Tier | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[NutritionPhotoResponse]:
        """POST /v1/nutrition/photo (beta). Pass exactly one of image_path, image_bytes or image_base64.

        The photo may have at most LIMITS["imageMaxMiB"] MiB before Base64 encoding; larger photos raise
        InvalidInputError without a request. tier: "light" is the default; "max" is not available yet
        (422 tier_unavailable, TierUnavailableError).
        """
        b64 = to_image_base64(image_path=image_path, image_bytes=image_bytes, image_base64=image_base64)
        body = {"image_base64": b64, "lang": lang, "energy_unit": energy_unit, "mass_unit": mass_unit, "volume_unit": volume_unit, "nutrients": nutrients, "provenance": provenance, "hint": hint, "known_grams": known_grams, "country": country, "meal": meal, "venue": venue, "review_threshold": review_threshold, "sources": sources, "exclude_sources": exclude_sources, "model": model, "custom_foods": custom_foods, "instructions": instructions, "chain_version": chain_version, "tier": tier, "profile": profile}
        return self._c._call("nutritionPhoto", body=body, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("nutritionCorrect")
    def correct(
        self,
        items: Sequence[CorrectItemInput | Mapping[str, Any]],
        *,
        lang: Lang | None = None,
        energy_unit: EnergyUnit | None = None,
        mass_unit: MassUnit | None = None,
        volume_unit: VolumeUnit | None = None,
        nutrients: Nutrients | None = None,
        provenance: Provenance | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[NutritionCorrectResponse]:
        """POST /v1/nutrition/correct: recalculate items with corrected amounts. No model runs, 0 credits."""
        body = {"items": items, "lang": lang, "energy_unit": energy_unit, "mass_unit": mass_unit, "volume_unit": volume_unit, "nutrients": nutrients, "provenance": provenance, "profile": profile}
        return self._c._call("nutritionCorrect", body=body, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class Foods:
    def __init__(self, client: Flexen) -> None:
        self._c = client

    @operation("foodsSearch")
    def search(
        self,
        q: str,
        *,
        lang: Lang | None = None,
        energy_unit: EnergyUnit | None = None,
        nutrients: Nutrients | None = None,
        provenance: Provenance | None = None,
        sources: Sequence[SourceId] | None = None,
        exclude_sources: Sequence[SourceId] | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[FoodSearchResponse]:
        """GET /v1/foods/search: your catalog first, then open sources. sources and exclude_sources go comma-separated."""
        return self._c._call("foodsSearch", params={"q": q, "lang": lang, "energy_unit": energy_unit, "nutrients": nutrients, "provenance": provenance, "sources": sources, "exclude_sources": exclude_sources, "profile": profile}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("foodsBarcode")
    def barcode(
        self,
        code: str,
        *,
        lang: Lang | None = None,
        energy_unit: EnergyUnit | None = None,
        nutrients: Nutrients | None = None,
        provenance: Provenance | None = None,
        sources: Sequence[SourceId] | None = None,
        exclude_sources: Sequence[SourceId] | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[ProductResponse]:
        """GET /v1/foods/barcode/{code}: 8, 12, 13 or 14 digits. NotFoundError if no product is known."""
        return self._c._call("foodsBarcode", params={"code": code, "lang": lang, "energy_unit": energy_unit, "nutrients": nutrients, "provenance": provenance, "sources": sources, "exclude_sources": exclude_sources, "profile": profile}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class Goals:
    def __init__(self, client: Flexen) -> None:
        self._c = client

    @operation("goalsCalculate")
    def calculate(
        self,
        *,
        sex: Literal["male", "female", "other"],
        weight_kg: float,
        height_cm: float,
        age: int,
        activity_level: Literal["sedentary", "lightly_active", "active", "very_active"],
        goal: Literal["lose_weight", "build_muscle", "gain_weight", "endurance", "maintain"],
        lang: Lang | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[GoalsResponse]:
        """POST /v1/goals/calculate: calories, macros and water from body data and goal (Mifflin-St Jeor)."""
        body = {"sex": sex, "weight_kg": weight_kg, "height_cm": height_cm, "age": age, "activity_level": activity_level, "goal": goal, "lang": lang, "profile": profile}
        return self._c._call("goalsCalculate", body=body, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class CatalogFoods:
    def __init__(self, client: Flexen) -> None:
        self._c = client

    @operation("catalogFoodsPut")
    def upsert(
        self, foods: Sequence[CatalogFood | Mapping[str, Any]], *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None
    ) -> FlexenResponse[CatalogSaveResponse]:
        """POST /v1/catalog/foods: create or replace foods (the same id replaces)."""
        return self._c._call("catalogFoodsPut", body={"foods": foods}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("catalogFoodsList")
    def list(
        self, *, q: str | None = None, cursor: str | None = None, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None
    ) -> FlexenResponse[CatalogFoodList]:
        """GET /v1/catalog/foods: one page; pass next_cursor as cursor for the next page."""
        return self._c._call("catalogFoodsList", params={"q": q, "cursor": cursor}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    def iterate(self, *, q: str | None = None, timeout: float | None = None) -> Iterator[CatalogFood]:
        """All foods, page by page (one request per page)."""
        cursor: str | None = None
        while True:
            page = self.list(q=q, cursor=cursor, timeout=timeout)
            yield from page.data.items
            cursor = page.data.next_cursor
            if not cursor:
                return

    @operation("catalogFoodsGet")
    def get(self, id: str, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogFood]:
        """GET /v1/catalog/foods/{id}. NotFoundError if it does not exist."""
        return self._c._call("catalogFoodsGet", params={"id": id}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("catalogFoodsDelete")
    def delete(self, id: str, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogDeleted]:
        """DELETE /v1/catalog/foods/{id}. NotFoundError if it does not exist."""
        return self._c._call("catalogFoodsDelete", params={"id": id}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class CatalogRecipes:
    def __init__(self, client: Flexen) -> None:
        self._c = client

    @operation("catalogRecipesPut")
    def upsert(
        self, recipes: Sequence[CatalogRecipe | Mapping[str, Any]], *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None
    ) -> FlexenResponse[CatalogSaveResponse]:
        """POST /v1/catalog/recipes: create or replace recipes (fields preliminary in the contract)."""
        return self._c._call("catalogRecipesPut", body={"recipes": recipes}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("catalogRecipesList")
    def list(
        self, *, q: str | None = None, cursor: str | None = None, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None
    ) -> FlexenResponse[CatalogRecipeList]:
        """GET /v1/catalog/recipes: one page; pass next_cursor as cursor for the next page."""
        return self._c._call("catalogRecipesList", params={"q": q, "cursor": cursor}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    def iterate(self, *, q: str | None = None, timeout: float | None = None) -> Iterator[CatalogRecipe]:
        """All recipes, page by page (one request per page)."""
        cursor: str | None = None
        while True:
            page = self.list(q=q, cursor=cursor, timeout=timeout)
            yield from page.data.items
            cursor = page.data.next_cursor
            if not cursor:
                return

    @operation("catalogRecipesGet")
    def get(self, id: str, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogRecipe]:
        """GET /v1/catalog/recipes/{id}. NotFoundError if it does not exist."""
        return self._c._call("catalogRecipesGet", params={"id": id}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("catalogRecipesDelete")
    def delete(self, id: str, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogDeleted]:
        """DELETE /v1/catalog/recipes/{id}. NotFoundError if it does not exist."""
        return self._c._call("catalogRecipesDelete", params={"id": id}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class Catalog:
    def __init__(self, client: Flexen) -> None:
        self._c = client
        self.foods = CatalogFoods(client)
        self.recipes = CatalogRecipes(client)

    @operation("catalogDelete")
    def delete_all(self, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogCleared]:
        """DELETE /v1/catalog: deletes the whole catalog, foods and recipes."""
        return self._c._call("catalogDelete", opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("catalogExport")
    def export(self, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogExport]:
        """GET /v1/catalog/export: all foods and recipes."""
        return self._c._call("catalogExport", opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class Account:
    def __init__(self, client: Flexen) -> None:
        self._c = client

    @operation("accountBalance")
    def balance(self, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[AccountBalance]:
        """GET /v1/account/balance: current balance in credits. Free."""
        return self._c._call("accountBalance", opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("accountUsage")
    def usage(
        self, from_: str | date, to: str | date, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None
    ) -> FlexenResponse[AccountUsage]:
        """GET /v1/account/usage: calls and credits per day and endpoint (from_ and to inclusive, UTC). Free."""
        return self._c._call("accountUsage", params={"from": _day(from_), "to": _day(to)}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


# ====================================================================== async


class AsyncFlexen(_ClientBase):
    """Async client of the Flexen API (asyncio; built on anyio). Cancel a call by cancelling its task."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry: RetryConfig | None = None,
        default_headers: Headers | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout, max_retries, retry, default_headers)
        self._own_http = http_client is None
        self._http = http_client or httpx.AsyncClient(follow_redirects=False)
        self.nutrition = AsyncNutrition(self)
        self.foods = AsyncFoods(self)
        self.goals = AsyncGoals(self)
        self.catalog = AsyncCatalog(self)
        self.account = AsyncAccount(self)

    async def aclose(self) -> None:
        if self._own_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncFlexen:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _call(self, op: str, *, params: Mapping[str, Any] | None = None, body: Mapping[str, Any] | None = None, opts: CallOptions) -> FlexenResponse[Any]:
        method, url, headers, content, deadline, max_retries = self._prepare(op, params, body, opts)
        attempt = 0
        while True:
            remaining = deadline.remaining()
            if remaining <= 0:
                raise RequestTimeoutError(f"No response within {deadline.seconds} s; the call was cancelled.")
            try:
                with anyio.fail_after(remaining):
                    res = await self._http.request(method, url, headers=headers, content=content, timeout=remaining)
            except (TimeoutError, httpx.TimeoutException) as e:
                raise RequestTimeoutError(f"No response within {deadline.seconds} s; the call was cancelled.") from e
            except httpx.HTTPError as e:
                raise APIConnectionError(f"Could not reach {self.base_url}: {e}") from e
            if res.is_success:
                return parse_success(op, res)
            err = error_from_response(res)
            if res.status_code not in RETRY_STATUSES or attempt >= max_retries:
                raise err
            delay = compute_retry_delay(attempt, err.retry_after_seconds, self.retry)
            if delay is None:
                raise err
            if delay >= deadline.remaining():
                raise RequestTimeoutError(f"No usable response within {deadline.seconds} s; the last one was {err}.") from err
            await anyio.sleep(delay)
            attempt += 1


class AsyncNutrition:
    def __init__(self, client: AsyncFlexen) -> None:
        self._c = client

    @operation("nutritionText")
    async def text(
        self,
        text: str,
        *,
        lang: Lang | None = None,
        energy_unit: EnergyUnit | None = None,
        mass_unit: MassUnit | None = None,
        volume_unit: VolumeUnit | None = None,
        nutrients: Nutrients | None = None,
        provenance: Provenance | None = None,
        hint: str | None = None,
        known_grams: float | None = None,
        country: str | None = None,
        meal: Meal | None = None,
        venue: str | None = None,
        review_threshold: float | None = None,
        sources: Sequence[SourceId] | None = None,
        exclude_sources: Sequence[SourceId] | None = None,
        model: str | Literal[False] | None = None,
        custom_foods: Sequence[CustomFood | Mapping[str, Any]] | None = None,
        instructions: str | None = None,
        chain_version: str | None = None,
        tier: Tier | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[NutritionTextResponse]:
        """POST /v1/nutrition/text: free text to amount, calories and macros.

        tier: "light" is the default; "max" is not available yet (422 tier_unavailable, TierUnavailableError).
        model=False works without the model, from the sources only. hint, instructions, country, meal, venue and
        known_grams make the response "not measured" (measured: false, unmeasured_because).
        """
        body = {"text": text, "lang": lang, "energy_unit": energy_unit, "mass_unit": mass_unit, "volume_unit": volume_unit, "nutrients": nutrients, "provenance": provenance, "hint": hint, "known_grams": known_grams, "country": country, "meal": meal, "venue": venue, "review_threshold": review_threshold, "sources": sources, "exclude_sources": exclude_sources, "model": model, "custom_foods": custom_foods, "instructions": instructions, "chain_version": chain_version, "tier": tier, "profile": profile}
        return await self._c._call("nutritionText", body=body, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("nutritionPhoto", extra=("image_path", "image_bytes"))
    async def photo(
        self,
        *,
        image_path: ImagePath | None = None,
        image_bytes: ImageBytes | None = None,
        image_base64: str | None = None,
        lang: Lang | None = None,
        energy_unit: EnergyUnit | None = None,
        mass_unit: MassUnit | None = None,
        volume_unit: VolumeUnit | None = None,
        nutrients: Nutrients | None = None,
        provenance: Provenance | None = None,
        hint: str | None = None,
        known_grams: float | None = None,
        country: str | None = None,
        meal: Meal | None = None,
        venue: str | None = None,
        review_threshold: float | None = None,
        sources: Sequence[SourceId] | None = None,
        exclude_sources: Sequence[SourceId] | None = None,
        model: str | None = None,
        custom_foods: Sequence[CustomFood | Mapping[str, Any]] | None = None,
        instructions: str | None = None,
        chain_version: str | None = None,
        tier: Tier | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[NutritionPhotoResponse]:
        """POST /v1/nutrition/photo (beta). Pass exactly one of image_path, image_bytes or image_base64.

        The photo may have at most LIMITS["imageMaxMiB"] MiB before Base64 encoding; larger photos raise
        InvalidInputError without a request. tier: "light" is the default; "max" is not available yet
        (422 tier_unavailable, TierUnavailableError).
        """
        b64 = await anyio.to_thread.run_sync(lambda: to_image_base64(image_path=image_path, image_bytes=image_bytes, image_base64=image_base64))
        body = {"image_base64": b64, "lang": lang, "energy_unit": energy_unit, "mass_unit": mass_unit, "volume_unit": volume_unit, "nutrients": nutrients, "provenance": provenance, "hint": hint, "known_grams": known_grams, "country": country, "meal": meal, "venue": venue, "review_threshold": review_threshold, "sources": sources, "exclude_sources": exclude_sources, "model": model, "custom_foods": custom_foods, "instructions": instructions, "chain_version": chain_version, "tier": tier, "profile": profile}
        return await self._c._call("nutritionPhoto", body=body, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("nutritionCorrect")
    async def correct(
        self,
        items: Sequence[CorrectItemInput | Mapping[str, Any]],
        *,
        lang: Lang | None = None,
        energy_unit: EnergyUnit | None = None,
        mass_unit: MassUnit | None = None,
        volume_unit: VolumeUnit | None = None,
        nutrients: Nutrients | None = None,
        provenance: Provenance | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[NutritionCorrectResponse]:
        """POST /v1/nutrition/correct: recalculate items with corrected amounts. No model runs, 0 credits."""
        body = {"items": items, "lang": lang, "energy_unit": energy_unit, "mass_unit": mass_unit, "volume_unit": volume_unit, "nutrients": nutrients, "provenance": provenance, "profile": profile}
        return await self._c._call("nutritionCorrect", body=body, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class AsyncFoods:
    def __init__(self, client: AsyncFlexen) -> None:
        self._c = client

    @operation("foodsSearch")
    async def search(
        self,
        q: str,
        *,
        lang: Lang | None = None,
        energy_unit: EnergyUnit | None = None,
        nutrients: Nutrients | None = None,
        provenance: Provenance | None = None,
        sources: Sequence[SourceId] | None = None,
        exclude_sources: Sequence[SourceId] | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[FoodSearchResponse]:
        """GET /v1/foods/search: your catalog first, then open sources. sources and exclude_sources go comma-separated."""
        return await self._c._call("foodsSearch", params={"q": q, "lang": lang, "energy_unit": energy_unit, "nutrients": nutrients, "provenance": provenance, "sources": sources, "exclude_sources": exclude_sources, "profile": profile}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("foodsBarcode")
    async def barcode(
        self,
        code: str,
        *,
        lang: Lang | None = None,
        energy_unit: EnergyUnit | None = None,
        nutrients: Nutrients | None = None,
        provenance: Provenance | None = None,
        sources: Sequence[SourceId] | None = None,
        exclude_sources: Sequence[SourceId] | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[ProductResponse]:
        """GET /v1/foods/barcode/{code}: 8, 12, 13 or 14 digits. NotFoundError if no product is known."""
        return await self._c._call("foodsBarcode", params={"code": code, "lang": lang, "energy_unit": energy_unit, "nutrients": nutrients, "provenance": provenance, "sources": sources, "exclude_sources": exclude_sources, "profile": profile}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class AsyncGoals:
    def __init__(self, client: AsyncFlexen) -> None:
        self._c = client

    @operation("goalsCalculate")
    async def calculate(
        self,
        *,
        sex: Literal["male", "female", "other"],
        weight_kg: float,
        height_cm: float,
        age: int,
        activity_level: Literal["sedentary", "lightly_active", "active", "very_active"],
        goal: Literal["lose_weight", "build_muscle", "gain_weight", "endurance", "maintain"],
        lang: Lang | None = None,
        profile: str | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        extra_headers: Headers | None = None,
    ) -> FlexenResponse[GoalsResponse]:
        """POST /v1/goals/calculate."""
        body = {"sex": sex, "weight_kg": weight_kg, "height_cm": height_cm, "age": age, "activity_level": activity_level, "goal": goal, "lang": lang, "profile": profile}
        return await self._c._call("goalsCalculate", body=body, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class AsyncCatalogFoods:
    def __init__(self, client: AsyncFlexen) -> None:
        self._c = client

    @operation("catalogFoodsPut")
    async def upsert(
        self, foods: Sequence[CatalogFood | Mapping[str, Any]], *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None
    ) -> FlexenResponse[CatalogSaveResponse]:
        """POST /v1/catalog/foods."""
        return await self._c._call("catalogFoodsPut", body={"foods": foods}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("catalogFoodsList")
    async def list(
        self, *, q: str | None = None, cursor: str | None = None, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None
    ) -> FlexenResponse[CatalogFoodList]:
        """GET /v1/catalog/foods: one page."""
        return await self._c._call("catalogFoodsList", params={"q": q, "cursor": cursor}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    async def iterate(self, *, q: str | None = None, timeout: float | None = None) -> AsyncIterator[CatalogFood]:
        """All foods, page by page (one request per page)."""
        cursor: str | None = None
        while True:
            page = await self.list(q=q, cursor=cursor, timeout=timeout)
            for item in page.data.items:
                yield item
            cursor = page.data.next_cursor
            if not cursor:
                return

    @operation("catalogFoodsGet")
    async def get(self, id: str, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogFood]:
        """GET /v1/catalog/foods/{id}."""
        return await self._c._call("catalogFoodsGet", params={"id": id}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("catalogFoodsDelete")
    async def delete(self, id: str, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogDeleted]:
        """DELETE /v1/catalog/foods/{id}."""
        return await self._c._call("catalogFoodsDelete", params={"id": id}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class AsyncCatalogRecipes:
    def __init__(self, client: AsyncFlexen) -> None:
        self._c = client

    @operation("catalogRecipesPut")
    async def upsert(
        self, recipes: Sequence[CatalogRecipe | Mapping[str, Any]], *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None
    ) -> FlexenResponse[CatalogSaveResponse]:
        """POST /v1/catalog/recipes."""
        return await self._c._call("catalogRecipesPut", body={"recipes": recipes}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("catalogRecipesList")
    async def list(
        self, *, q: str | None = None, cursor: str | None = None, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None
    ) -> FlexenResponse[CatalogRecipeList]:
        """GET /v1/catalog/recipes: one page."""
        return await self._c._call("catalogRecipesList", params={"q": q, "cursor": cursor}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    async def iterate(self, *, q: str | None = None, timeout: float | None = None) -> AsyncIterator[CatalogRecipe]:
        """All recipes, page by page (one request per page)."""
        cursor: str | None = None
        while True:
            page = await self.list(q=q, cursor=cursor, timeout=timeout)
            for item in page.data.items:
                yield item
            cursor = page.data.next_cursor
            if not cursor:
                return

    @operation("catalogRecipesGet")
    async def get(self, id: str, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogRecipe]:
        """GET /v1/catalog/recipes/{id}."""
        return await self._c._call("catalogRecipesGet", params={"id": id}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("catalogRecipesDelete")
    async def delete(self, id: str, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogDeleted]:
        """DELETE /v1/catalog/recipes/{id}."""
        return await self._c._call("catalogRecipesDelete", params={"id": id}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class AsyncCatalog:
    def __init__(self, client: AsyncFlexen) -> None:
        self._c = client
        self.foods = AsyncCatalogFoods(client)
        self.recipes = AsyncCatalogRecipes(client)

    @operation("catalogDelete")
    async def delete_all(self, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogCleared]:
        """DELETE /v1/catalog: deletes the whole catalog, foods and recipes."""
        return await self._c._call("catalogDelete", opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("catalogExport")
    async def export(self, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[CatalogExport]:
        """GET /v1/catalog/export: all foods and recipes."""
        return await self._c._call("catalogExport", opts=_opts(idempotency_key, timeout, max_retries, extra_headers))


class AsyncAccount:
    def __init__(self, client: AsyncFlexen) -> None:
        self._c = client

    @operation("accountBalance")
    async def balance(self, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None) -> FlexenResponse[AccountBalance]:
        """GET /v1/account/balance. Free."""
        return await self._c._call("accountBalance", opts=_opts(idempotency_key, timeout, max_retries, extra_headers))

    @operation("accountUsage")
    async def usage(
        self, from_: str | date, to: str | date, *, idempotency_key: str | None = None, timeout: float | None = None, max_retries: int | None = None, extra_headers: Headers | None = None
    ) -> FlexenResponse[AccountUsage]:
        """GET /v1/account/usage (from_ and to inclusive, UTC). Free."""
        return await self._c._call("accountUsage", params={"from": _day(from_), "to": _day(to)}, opts=_opts(idempotency_key, timeout, max_retries, extra_headers))
