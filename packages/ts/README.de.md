# @flexen/api

Offizieller TypeScript-Client der Flexen API: Nährwerte aus Text und Fotos, Lebensmittelsuche, Barcode, Zielrechner, eigener Lebensmittelkatalog und Guthaben.

- Node 22+ und aktuelle Browser (nutzt `fetch`), nur ESM, keine Laufzeitabhängigkeiten
- Typen aus dem öffentlichen API-Vertrag erzeugt (`contract/snapshot.json` in diesem Repo)
- Fehlerklassen je Fehlercode, automatische Wiederholung bei 429 und 503, Abbruch, Credit-Kopfzeilen an jedem Ergebnis

English: [README.md](./README.md)

## Schnellstart

1. Installieren: `npm install @flexen/api`
2. Schlüssel setzen: `export FLEXEN_API_KEY=flx_live_…` (Schlüssel legst du in der Flexen-Konsole an; `flx_test_…`-Schlüssel liefern feste Beispiele und kosten nichts)
3. Aufrufen:

```ts
import { Flexen } from '@flexen/api'

const flexen = new Flexen() // liest FLEXEN_API_KEY
const { data, creditsCharged, creditsRemaining } = await flexen.nutrition.text({ text: '2 Scheiben Vollkornbrot mit Gouda und ein Apfel', lang: 'de' })
console.log(data.total.kcal.value, data.items[0].needs_review, creditsCharged, creditsRemaining)
```

## Beispiele

### Foto aus einer Datei

```ts
const res = await flexen.nutrition.photo({ file: './mittag.jpg', lang: 'de' }) // nur Node
console.log(res.data.dish, res.data.kcal, res.data.confidence)

// Browser: File/Blob, Bytes oder Base64 übergeben
await flexen.nutrition.photo({ image: fileInput.files[0] })
await flexen.nutrition.photo({ image_base64: 'data:image/jpeg;base64,/9j/…' })
```

Das Foto darf vor der Base64-Kodierung höchstens 8 MiB groß sein (`LIMITS.imageMaxMiB`). Größere Fotos lösen `InvalidInputError` aus, bevor etwas gesendet wird. Angenommen werden JPEG, PNG und WebP.

### Lebensmittelsuche und Barcode

```ts
const { data } = await flexen.foods.search({ q: 'Apfel', lang: 'de' })
for (const r of data.results) console.log(r.name, r.per_100g.kcal, r.source, r.license)

const produkt = await flexen.foods.barcode({ code: '4000000000000' })
```

Namen kommen so, wie die Quelle sie führt (USDA nur auf Englisch). Jedes Ergebnis nennt seine Quelle und bei freien Quellen Lizenz und Namensnennung, die du anzeigen musst.

### Zu wenig Guthaben

```ts
import { InsufficientCreditsError, DailyLimitReachedError, APIError } from '@flexen/api'

try {
  await flexen.nutrition.text({ text: 'Haferbrei mit Blaubeeren' })
} catch (e) {
  if (e instanceof InsufficientCreditsError) {
    console.log(`In der Konsole aufladen. Guthaben: ${e.creditsRemaining}, Aufruf ${e.requestId}`)
  } else if (e instanceof DailyLimitReachedError) {
    console.log('Tägliche Ausgabenobergrenze erreicht')
  } else if (e instanceof APIError) {
    console.log(e.status, e.code, e.apiMessage, e.requestId)
  } else {
    throw e
  }
}
```

## Einstellungen je Aufruf

Jeder Aufruf nimmt die Einstellungen des Vertrags: Sprache, Einheiten, Nährstoff-Umfang, Herkunft je Feld, Hinweis, bekanntes Gewicht, Kontext (Land, Mahlzeit, Ort), Spannen-Schwelle, Quellen, eigene Anweisung, Kettenfassung, Stufe und Profil.

```ts
const res = await flexen.nutrition.text({
  text: 'Skyr mit Heidelbeeren',
  lang: 'sv',                 // 12 Sprachen; auch die Sprache der Namen
  energy_unit: 'kj',          // kcal (Standard) oder kj
  mass_unit: 'oz',            // g (Standard) oder oz
  nutrients: 'eu7',           // macros (Standard), eu7 oder full
  provenance: 'field',        // Herkunft je Feld statt je Eintrag
  known_grams: 250,           // das Gewicht ist bekannt
  hint: 'ohne Zuckerzusatz',     // geht in den Prompt
  country: 'SE',
  meal: 'breakfast',
  sources: ['customer_catalog', 'usda_fdc', 'model'],
  profile: 'app-se',          // ein Profil aus der Konsole
})
console.log(res.data.measured, res.data.unmeasured_because)

// nur Datenbanken, ohne Modell (nur Text; braucht eine Menge)
await flexen.nutrition.text({ text: 'Skyr', model: false, known_grams: 150, sources: ['usda_fdc'] })
```

Hinweis, Anweisung, Kontext und bekanntes Gewicht verändern die gemessene Kette. Die Antwort trägt dann `measured: false` und nennt den Grund in `unmeasured_because`. `instructions` und `nutrients: "eu7"` aus dem Modell kosten je 1 Credit mehr. Die Quellen `bls`, `ciqual`, `fineli` und `livsmedelsverket` stehen im Vertrag, liefern aber erst Daten, wenn sie in der API eingeschaltet sind; bis dahin tragen sie nichts bei, und ein Aufruf ohne Modell, der sich auf sie stützt, bekommt `503 service_unavailable`.

## Endpunkte

| Methode | Endpunkt | Preis (vorläufig, Credits) |
| --- | --- | --- |
| `nutrition.text(body)` | POST /v1/nutrition/text | 1 |
| `nutrition.photo(params)` | POST /v1/nutrition/photo (Beta) | 2 |
| `nutrition.correct(body)` | POST /v1/nutrition/correct | 0 |
| `foods.search(params)` | GET /v1/foods/search | 1 |
| `foods.barcode(params)` | GET /v1/foods/barcode/{code} | 1 |
| `goals.calculate(body)` | POST /v1/goals/calculate | 1 |
| `catalog.foods.upsert / list / iterate / get / delete` | /v1/catalog/foods | kostenlos |
| `catalog.recipes.upsert / list / iterate / get / delete` | /v1/catalog/recipes | kostenlos |
| `catalog.deleteAll()` / `catalog.export()` | DELETE /v1/catalog, GET /v1/catalog/export | kostenlos |
| `account.balance()` / `account.usage({ from, to })` | /v1/account/… | kostenlos |

1 Credit = 0,1 Cent netto. Preise und Feldnamen der Antworten sind im Vertrag vorläufig. `OPERATIONS` nennt Methode, Pfad, Stand und Preis jedes Endpunkts.

- `nutrition/correct` rechnet nur neu, ohne Modell, und kostet nichts.
- Die Stufe `max` gibt es noch nicht: Die API antwortet `422 tier_unavailable` (`TierUnavailableError`). Ohne `tier` gilt `light`. Mit einem Testschlüssel liefert `max` dasselbe feste Beispiel wie `light`. `TIERS` nennt den Stand je Endpunkt.
- Nicht verfügbar (im Vertrag als „kommt später“ angekündigt, ohne Methoden in diesem SDK): `NOT_AVAILABLE` listet sie (Kühlschrankfoto, Rezeptideen, Mikronährstoffe, Trainingsplan).

## Ergebnisse

Jede Methode liefert ein `FlexenResponse<T>`:

| Feld | Kopfzeile / Bedeutung |
| --- | --- |
| `data` | Antwort als JSON, typisiert |
| `creditsCharged` | `X-Credits-Charged` (0 mit Testschlüsseln und bei kostenlosen Endpunkten) |
| `creditsRemaining` | `X-Credits-Remaining`; für laufende Aufrufe reservierte Credits sind noch nicht abgezogen |
| `requestId` | `X-Request-Id`; bei Rückfragen nennen |
| `idempotentReplayed` | `Idempotent-Replayed`: `true`, wenn die Antwort aus einem früheren Aufruf mit demselben `Idempotency-Key` stammt |
| `status`, `headers` | HTTP-Status und alle Kopfzeilen |

## Fehler

Alle Fehler erben von `FlexenError`. Antworten mit Fehlerstatus werfen eine Unterklasse von `APIError` mit `status`, `code`, `apiMessage`, `requestId`, `creditsCharged`, `creditsRemaining` und `retryAfterSeconds`:

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

Auf Seite des Clients: `InvalidInputError` (vor dem Senden abgelehnt), `APIConnectionError`, `RequestTimeoutError`, `UserAbortError`.

## Wiederholung, Frist, Abbruch, Idempotenz

- Wiederholt werden nur 429 und 503, höchstens dreimal (`maxRetries`), mit exponentieller Wartezeit und Zufallsanteil. `Retry-After` wird eingehalten; verlangt es mehr als `retry.maxRetryAfterMs` (60 s), kommt stattdessen der Fehler. Alles andere (übrige 4xx, 500, 504, Netzfehler) wird nie wiederholt. Laut Vertrag buchen 429 und 503 nichts ab.
- `timeoutMs` (Standard 60 s) ist die Gesamtzeit eines Aufrufs samt Wartezeiten. Läuft sie ab, kommt `RequestTimeoutError`.
- Mit `{ signal }` brichst du einen Aufruf ab und bekommst `UserAbortError`. Ein Aufruf, der vor der Antwort abgebrochen wird, kostet nichts.
- `{ idempotencyKey }` geht als `Idempotency-Key` mit, bei jeder Wiederholung derselbe. Die API hält die Antwort 24 Stunden: Dieselbe Anfrage mit demselben Schlüssel liefert dieselbe Antwort, bucht nichts ab und ist am Ergebnis als wiederholt markiert (`idempotentReplayed`). Läuft der erste Aufruf noch, kommt `409 idempotency_in_progress` (`IdempotencyInProgressError`, wird nicht automatisch wiederholt).

```ts
const ac = new AbortController()
const res = await flexen.nutrition.text({ text: 'Banane' }, { signal: ac.signal, timeoutMs: 30_000, idempotencyKey: crypto.randomUUID() })
```

## Einstellungen

```ts
new Flexen({
  apiKey: 'flx_live_…',              // Standard: process.env.FLEXEN_API_KEY
  baseUrl: 'https://api.flexen.co',  // Standard
  timeoutMs: 60_000,
  maxRetries: 3,
  retry: { baseDelayMs: 500, maxDelayMs: 8000, maxRetryAfterMs: 60_000 },
  fetch: eigenesFetch,               // optional
})
```

Der Schlüssel liegt in einem privaten Feld und wird nie protokolliert; `JSON.stringify(client)` zeigt nur seinen Anfang. Liefere keinen Live-Schlüssel in Browser-Code aus, den andere öffnen können: Dort kann ihn jeder lesen. Ruf die API stattdessen von deinem Server auf.

## Entwicklung

Im Wurzelverzeichnis des Repos: `npm install`, `npm run test:ts`, `npm run build:ts`, `npm run check:contract`. Die Typen in `src/generated/contract.ts` sind erzeugt (`npm run generate`); nicht von Hand ändern.
