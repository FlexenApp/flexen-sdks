# flexen

Offizieller Python-Client der Flexen API: Nährwerte aus Text und Fotos, Lebensmittelsuche, Barcode, Zielrechner, eigener Lebensmittelkatalog und Guthaben.

- Python 3.10+, auf httpx und Pydantic v2
- `Flexen` (synchron) und `AsyncFlexen` (asynchron, asyncio)
- Modelle aus dem öffentlichen API-Vertrag erzeugt (`contract/snapshot.json` in diesem Repo)
- Fehlerklassen je Fehlercode, automatische Wiederholung bei 429 und 503, Fristen, Credit-Kopfzeilen an jedem Ergebnis

English: [README.md](./README.md)

## Schnellstart

1. Installieren: `pip install flexen`
2. Schlüssel setzen: `export FLEXEN_API_KEY=flx_live_…` (Schlüssel legst du in der Flexen-Konsole an; `flx_test_…`-Schlüssel liefern feste Beispiele und kosten nichts)
3. Aufrufen:

```python
from flexen import Flexen

client = Flexen()  # liest FLEXEN_API_KEY
res = client.nutrition.text("2 Scheiben Vollkornbrot mit Gouda und ein Apfel", lang="de")
print(res.data.total.kcal.value, res.data.items[0].needs_review, res.credits_charged, res.credits_remaining)
```

## Beispiele

### Foto aus einer Datei

```python
res = client.nutrition.photo(image_path="mittag.jpg", lang="de")
print(res.data.dish, res.data.kcal, res.data.confidence)

# oder Bytes (auch ein binär geöffnetes Dateiobjekt) / Base64
client.nutrition.photo(image_bytes=Path("mittag.jpg").read_bytes())  # from pathlib import Path
client.nutrition.photo(image_base64="data:image/jpeg;base64,/9j/…")
```

Das Foto darf vor der Base64-Kodierung höchstens 8 MiB groß sein (`LIMITS["imageMaxMiB"]`). Größere Fotos lösen `InvalidInputError` aus, bevor etwas gesendet wird. Angenommen werden JPEG, PNG und WebP.

### Lebensmittelsuche und Barcode

```python
res = client.foods.search("Apfel", lang="de")
for r in res.data.results:
    print(r.name, r.per_100g.kcal, r.source, r.license)

produkt = client.foods.barcode("4000000000000")
```

Namen kommen so, wie die Quelle sie führt (USDA nur auf Englisch). Jedes Ergebnis nennt seine Quelle und bei freien Quellen Lizenz und Namensnennung, die du anzeigen musst.

### Zu wenig Guthaben

```python
from flexen import APIError, DailyLimitReachedError, InsufficientCreditsError

try:
    client.nutrition.text("Haferbrei mit Blaubeeren")
except InsufficientCreditsError as e:
    print(f"In der Konsole aufladen. Guthaben: {e.credits_remaining}, Aufruf {e.request_id}")
except DailyLimitReachedError:
    print("Tägliche Ausgabenobergrenze erreicht")
except APIError as e:
    print(e.status_code, e.code, e.message, e.request_id)
```

### Asynchron

```python
import asyncio
from flexen import AsyncFlexen

async def main() -> None:
    async with AsyncFlexen() as client:
        res = await client.nutrition.text("Banane", timeout=30)
        async for food in client.catalog.foods.iterate():
            print(food.id, food.name)

asyncio.run(main())
```

Einen asynchronen Aufruf brichst du ab, indem du seinen Task abbrichst (etwa mit `asyncio.wait_for` oder `anyio.move_on_after`). Ein Aufruf, der vor der Antwort abgebrochen wird, kostet nichts.

## Einstellungen je Aufruf

Jeder Aufruf nimmt die Einstellungen des Vertrags: Sprache, Einheiten, Nährstoff-Umfang, Herkunft je Feld, Hinweis, bekanntes Gewicht, Kontext (Land, Mahlzeit, Ort), Spannen-Schwelle, Quellen, eigene Anweisung, Kettenfassung, Stufe und Profil.

```python
res = client.nutrition.text(
    "Skyr mit Heidelbeeren",
    lang="sv",                  # 12 Sprachen; auch die Sprache der Namen
    energy_unit="kj",           # kcal (Standard) oder kj
    mass_unit="oz",             # g (Standard) oder oz
    nutrients="eu7",            # macros (Standard), eu7 oder full
    provenance="field",         # Herkunft je Feld statt je Eintrag
    known_grams=250,            # das Gewicht ist bekannt
    hint="ohne Zuckerzusatz",      # geht in den Prompt
    country="SE", meal="breakfast",
    sources=["customer_catalog", "usda_fdc", "model"],
    profile="app-se",           # ein Profil aus der Konsole
)
print(res.data.measured, res.data.unmeasured_because)

# nur Datenbanken, ohne Modell (nur Text; braucht eine Menge)
client.nutrition.text("Skyr", model=False, known_grams=150, sources=["usda_fdc"])
```

Hinweis, Anweisung, Kontext und bekanntes Gewicht verändern die gemessene Kette. Die Antwort trägt dann `measured: false` und nennt den Grund in `unmeasured_because`. `instructions` und `nutrients: "eu7"` aus dem Modell kosten je 1 Credit mehr. Die Quellen `bls`, `ciqual`, `fineli` und `livsmedelsverket` stehen im Vertrag, liefern aber erst Daten, wenn sie in der API eingeschaltet sind; bis dahin tragen sie nichts bei, und ein Aufruf ohne Modell, der sich auf sie stützt, bekommt `503 service_unavailable`.

## Endpunkte

| Methode | Endpunkt | Preis (vorläufig, Credits) |
| --- | --- | --- |
| `nutrition.text(text, ...)` | POST /v1/nutrition/text | 1 |
| `nutrition.photo(image_path= / image_bytes= / image_base64=, ...)` | POST /v1/nutrition/photo (Beta) | 2 |
| `nutrition.correct(items, ...)` | POST /v1/nutrition/correct | 0 |
| `foods.search(q, lang=, nutrients=, sources=, ...)` | GET /v1/foods/search | 1 |
| `foods.barcode(code, lang=, nutrients=, sources=, ...)` | GET /v1/foods/barcode/{code} | 1 |
| `goals.calculate(sex=, weight_kg=, height_cm=, age=, activity_level=, goal=, lang=, profile=)` | POST /v1/goals/calculate | 1 |
| `catalog.foods.upsert / list / iterate / get / delete` | /v1/catalog/foods | kostenlos |
| `catalog.recipes.upsert / list / iterate / get / delete` | /v1/catalog/recipes | kostenlos |
| `catalog.delete_all()` / `catalog.export()` | DELETE /v1/catalog, GET /v1/catalog/export | kostenlos |
| `account.balance()` / `account.usage(from_, to)` | /v1/account/… | kostenlos |

1 Credit = 0,1 Cent netto. Preise und Feldnamen der Antworten sind im Vertrag vorläufig. `flexen.OPERATIONS` nennt Methode, Pfad, Stand und Preis jedes Endpunkts; alle Modelle des Vertrags liegen in `flexen.types`.

- `nutrition/correct` rechnet nur neu, ohne Modell, und kostet nichts.
- Die Stufe `max` gibt es noch nicht: Die API antwortet `422 tier_unavailable` (`TierUnavailableError`). Ohne `tier` gilt `light`. Mit einem Testschlüssel liefert `max` dasselbe feste Beispiel wie `light`. `TIERS` nennt den Stand je Endpunkt.
- Nicht verfügbar (im Vertrag als „kommt später“ angekündigt, ohne Methoden in diesem SDK): `flexen.NOT_AVAILABLE` listet sie (Kühlschrankfoto, Rezeptideen, Mikronährstoffe, Trainingsplan).

## Ergebnisse

Jede Methode liefert ein `FlexenResponse`:

| Attribut | Kopfzeile / Bedeutung |
| --- | --- |
| `data` | die Antwort als Pydantic-Modell |
| `credits_charged` | `X-Credits-Charged` (0 mit Testschlüsseln und bei kostenlosen Endpunkten) |
| `credits_remaining` | `X-Credits-Remaining`; für laufende Aufrufe reservierte Credits sind noch nicht abgezogen |
| `request_id` | `X-Request-Id`; bei Rückfragen nennen |
| `idempotent_replayed` | `Idempotent-Replayed`: `True`, wenn die Antwort aus einem früheren Aufruf mit demselben `Idempotency-Key` stammt |
| `status_code`, `headers` | HTTP-Status und alle Kopfzeilen |

## Fehler

Alle Fehler erben von `FlexenError`. Antworten mit Fehlerstatus lösen eine Unterklasse von `APIError` aus, mit `status_code`, `code`, `message`, `request_id`, `credits_charged`, `credits_remaining` und `retry_after_seconds`:

| Status | Code | Klasse |
| --- | --- | --- |
| 400 | invalid_json | `BadRequestError` |
| 401 | invalid_key | `AuthenticationError` |
| 402 | insufficient_credits | `InsufficientCreditsError` |
| 402 | daily_limit_reached | `DailyLimitReachedError` |
| 402 | monthly_budget_reached | `MonthlyBudgetReachedError` |
| 402 | key_budget_reached | `KeyBudgetReachedError` |
| 403 | account_suspended | `AccountSuspendedError` |
| 403 | key_expired | `KeyExpiredError` |
| 403 | key_scope_denied | `KeyScopeDeniedError` |
| 403 | ip_not_allowed | `IpNotAllowedError` |
| 404 | not_found | `NotFoundError` |
| 409 | idempotency_in_progress | `IdempotencyInProgressError` |
| 422 | invalid_request | `InvalidRequestError` |
| 422 | tier_unavailable | `TierUnavailableError` |
| 429 | rate_limited | `RateLimitError` |
| 500 | internal_error | `InternalServerError` |
| 503 | service_unavailable | `ServiceUnavailableError` |
| 504 | timeout | `ServerTimeoutError` |

Auf Seite des Clients: `InvalidInputError` (vor dem Senden abgelehnt, auch Pydantic-Prüfung der Anfrage), `APIConnectionError`, `RequestTimeoutError`, `UnexpectedResponseError` (eine 2xx-Antwort, die nicht zum Vertrag passt).

## Wiederholung, Frist, Idempotenz

- Wiederholt werden nur 429 und 503, höchstens dreimal (`max_retries`), mit exponentieller Wartezeit und Zufallsanteil. `Retry-After` wird eingehalten; verlangt es mehr als `RetryConfig.max_retry_after` (60 s), kommt stattdessen der Fehler. Alles andere (übrige 4xx, 500, 504, Netzfehler) wird nie wiederholt. Laut Vertrag buchen 429 und 503 nichts ab.
- `timeout` (Sekunden, Standard 60) ist das Zeitbudget eines Aufrufs samt Wartezeiten; läuft es ab, kommt `RequestTimeoutError`.
- `idempotency_key="…"` geht als `Idempotency-Key` mit, bei jeder Wiederholung derselbe. Die API hält die Antwort 24 Stunden: Dieselbe Anfrage mit demselben Schlüssel liefert dieselbe Antwort, bucht nichts ab und ist am Ergebnis als wiederholt markiert (`idempotent_replayed`). Läuft der erste Aufruf noch, kommt `409 idempotency_in_progress` (`IdempotencyInProgressError`, wird nicht automatisch wiederholt).

```python
client.nutrition.text("Banane", timeout=30, max_retries=1, idempotency_key="bestellung-4711-mahlzeit-2")
```

## Einstellungen

```python
from flexen import Flexen, RetryConfig

client = Flexen(
    api_key="flx_live_…",              # Standard: FLEXEN_API_KEY
    base_url="https://api.flexen.co",  # Standard
    timeout=60.0,
    max_retries=3,
    retry=RetryConfig(base_delay=0.5, max_delay=8.0, max_retry_after=60.0),
)
```

Der Schlüssel wird nie protokolliert; `repr(client)` zeigt nur seinen Anfang. Nutze den Client als Kontextmanager (`with Flexen() as client:`) oder ruf `close()` bzw. `await aclose()` auf.

## Entwicklung

```bash
cd packages/python
uv venv --python 3.12 .venv            # oder: python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.lock
.venv/bin/python -m pytest -q
```

`src/flexen/_generated.py` ist aus dem Vertrag erzeugt (`npm run generate` im Wurzelverzeichnis); nicht von Hand ändern. `npm run check:contract` schlägt fehl, wenn das SDK vom Vertrag abweicht.
