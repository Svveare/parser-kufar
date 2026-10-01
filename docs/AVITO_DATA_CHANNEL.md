# Avito data channel

## Default prod path (zero-config)

```env
AVITO_ENABLED=true
```

Built-in live fetch (`avito_live.py` → `https://www.avito.ru/web/1/main/items`) runs automatically when `AVITO_LIVE_ENABLED` is true (default with `AVITO_ENABLED`). No `AVITO_SEARCH_URL`, feed URL, or mock required.

Optional overrides:

| Env | Role |
|-----|------|
| `AVITO_DEV_MOCK=true` | Local smoke with `geo/avito_mock_ads.json` |
| `AVITO_SEARCH_URL` | External per-key collector (overrides live) |
| `AVITO_FEED_URL` | Snapshot JSON fallback |
| `AVITO_LIVE_ENABLED=false` | Disable built-in live |

## Minimum fields per listing

- `id` — stable listing id
- `title`
- `price_rub` — integer, RUB
- `url` — canonical link
- `city` / `region` — match `avito_city_id` / `avito_region_id` in bot DB
- `photos` — list of URLs
- `description` — text (optional for matching; required for VIP cards)
- `published_at` — ISO timestamp
- `category` — mappable to bot `product_category`

The bot enables Avito by default. Set `AVITO_ENABLED=false` to disable it. Users must select a supported city and at least one model before polling starts.

## Operational requirements

- Documented rate limits and retry policy
- Feed freshness SLA (e.g. listings no older than N minutes)
- Incident contact and changelog for schema breaks
- Staging environment for smoke tests before production rollout

## Delivery checklist

1. Ensure the RU user has a supported city, selected models and notifications enabled
2. Staging: exercise an RU user through the complete city/model/notification flow
3. Logs: `avito live loaded ads=…`
4. Optional: `AVITO_SEARCH_URL` or `AVITO_FEED_URL` instead of live

## Config (Phase 4.0)

```env
AVITO_ENABLED=true
AVITO_CHECK_INTERVAL=420
AVITO_VIP_CHECK_INTERVAL=60
```

Set `AVITO_ENABLED=false` to turn off Avito polling.

## Как получить данные (API / фид)

**Публичного API Avito «слушать витрину» нет.** Официальный API Avito — для **своих** объявлений продавца (управление листингами), не для мониторинга каталога чужих телефонов.

Варианты для бота:

| Вариант | Что нужно |
|---------|-----------|
| **Built-in live** (default) | `AVITO_ENABLED=true` |
| External search API | `AVITO_SEARCH_URL` |
| Партнёрский JSON feed | `AVITO_FEED_URL` |
| Локальный тест | `AVITO_DEV_MOCK=true` |

```env
AVITO_ENABLED=true
# AVITO_LIVE_ENABLED=false   # отключить live, использовать external URL
# AVITO_SEARCH_URL=...
# AVITO_FEED_URL=...
FEED_REFRESH_SECONDS=30
```

Формат ответа feed — массив `[{...}]` или объект `{"ads": [...]}`. Пример записи: [`geo/avito_feed_sample.json`](geo/avito_feed_sample.json).

Если нужен smoke-тест без сетевых запросов — установите `AVITO_ENABLED=true` + `AVITO_DEV_MOCK=true`.

## Local dev mock (end-to-end без фида)

Для smoke-теста UI + poller + карточки «Открыть на Avito» без HTTP к avito.ru:

```env
AVITO_ENABLED=true
AVITO_DEV_MOCK=true
```

Данные: [`geo/avito_mock_ads.json`](geo/avito_mock_ads.json) — фильтрация по `FetchKey` (город, категория, модель, память), как catalog path на Kufar.

Шаги в боте:

1. Страна → Россия (возврат на главную; город — кнопка «Город»)
2. Город → Москва / Санкт-Петербург / Смоленск (текущий встроенный список)
3. Товары → модель (например iPhone 15), память
4. Включить уведомления

При старте бота в логах: `AVITO_DEV_MOCK=true — … mock_ads.json`.

## Search API (Фаза 4.2)

Per-key запрос, аналог Kufar `catalog_search_params` → search-api.

**Endpoint:** `AVITO_SEARCH_URL` (полный URL handler, например `https://collector.example/avito/search`).

**Method:** `GET`

**Query params** (из `FetchKey` через [`avito_catalog.search_params_from_key`](avito_catalog.py)):

| Param | Источник | Пример |
|-------|----------|--------|
| `city_id` | `geo_b` | `637640` |
| `region_id` | `geo_a` (если задан) | `637640` |
| `category` | категория | `phones` |
| `models` | models tuple, comma-separated | `iphone 15,iphone 15 pro` |
| `memory_gb` | memories (только phones) | `256` или `128,256` |

**Response:** как feed 4.1 — массив `[{...}]` или `{"ads": [...]}`. Поля — «Minimum fields».

**Auth:** `AVITO_FEED_AUTH` → `Authorization` header.

**Retry:** 5xx/429/network — `AVITO_FEED_RETRIES`, `AVITO_FEED_RETRY_DELAY`.

Collector отвечает **уже отфильтрованным** списком по ключу; бот только нормализует (`normalize_feed_ad`), без `filter_ads_for_key`.

Кэш per `FetchKey` в poller (`FEED_REFRESH_SECONDS`) — один HTTP search на уникальный ключ за TTL.

### Prod checklist (search)

```env
AVITO_ENABLED=true
AVITO_DEV_MOCK=false
AVITO_SEARCH_URL=https://collector.example/avito/search
# AVITO_FEED_AUTH=Bearer <token>
FEED_REFRESH_SECONDS=30
```

## JSON feed format (Фаза 4.1 — fallback)

Поддерживаются два корневых формата:

```json
[{ "id": "...", "title": "...", "price_rub": 75000, "url": "...", ... }]
```

```json
{ "ads": [ { "id": "...", ... } ] }
```

Поля записи — как в секции «Minimum fields» выше. При snapshot feed — фильтрация по `FetchKey` на стороне бота.

Пример: [`geo/avito_feed_sample.json`](geo/avito_feed_sample.json).

### Prod checklist (feed fallback)

```env
AVITO_ENABLED=true
AVITO_DEV_MOCK=false
# AVITO_SEARCH_URL=   # пуст — используется feed
AVITO_FEED_URL=https://partner.example/avito-feed.json
# AVITO_FEED_AUTH=Bearer <token>
FEED_REFRESH_SECONDS=30
```

- Один HTTP GET на снимок feed раз в `FEED_REFRESH_SECONDS`
- Retry на 5xx/429/network (`AVITO_FEED_RETRIES`)
- RU anti-junk: [`filters_avito.py`](filters_avito.py)

