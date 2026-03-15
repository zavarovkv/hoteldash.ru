# HotelDash

Мониторинг цен на отели. Ежедневно парсит цены с 5 OTA (Островок, Ozon Travel, Яндекс Путешествия, Otello, сайт отеля через TravelLine API), сохраняет в PostgreSQL, визуализирует через Metabase.

## Стек

- **Парсинг:** Playwright (Chromium) + Camoufox (Firefox, антибот) + httpx (прямой API)
- **БД:** PostgreSQL 16
- **Дашборд:** Metabase (embedded, JWT)
- **Деплой:** Docker Compose + Nginx + Let's Encrypt
- **CI/CD:** GitHub Actions (auto-deploy on push to master)

## Архитектура парсеров

| Источник | Метод | Браузер | Прокси |
|----------|-------|---------|--------|
| Островок | Перехват API `/hp/search` | Playwright | Нет |
| Ozon Travel | DOM-парсинг «от XX XXX ₽» | Camoufox | Да |
| Яндекс Путешествия | CSS-селекторы + title fallback | Camoufox | Да |
| Otello | Перехват API `/offers` + DOM fallback | Playwright | Нет |
| Сайт отеля (TravelLine) | Прямой HTTP POST к API | Нет | Нет |

## Быстрый старт

```bash
# 1. Конфигурация
cp .env.example .env
cp config/hotels.yaml.example config/hotels.yaml
# Отредактировать .env (пароль БД) и hotels.yaml (ваши отели)

# 2. Запуск
docker compose up -d db
docker compose build app
docker compose run --rm app python scripts/init_db.py

# 3. Первый прогон
docker compose run --rm app
```

## Настройка отелей

Отели и URL-шаблоны настраиваются в `config/hotels.yaml` (см. `hotels.yaml.example`).

Плейсхолдеры в URL: `{checkin}`, `{checkout}`, `{checkin_dot}`, `{checkout_dot}`, `{nights}`, `{adults}`.

Расписание (смещения дат, количество гостей) — в секции `schedule`.

## Использование

```bash
# Полный прогон (все отели, все источники)
docker compose run --rm app

# Один отель, один источник, конкретная дата
docker compose run --rm app python -m src.main \
  --hotel example-hotel --source ostrovok --checkin 2026-03-20
```

## Деплой на сервер

```bash
# Одна команда — Docker, клон репо, БД, крон
ssh your-server 'bash -s' < scripts/setup_server.sh
```

Крон запускается ежедневно в 01:00 МСК:
```
0 22 * * * ~/hoteldash.ru/cron/hoteldash_cron.sh >> ~/hoteldash.ru/logs/cron.log 2>&1
```

## CI/CD

Авто-деплой через GitHub Actions при пуше в `master`. Секреты:
- `SSH_HOST` — IP сервера
- `SSH_USERNAME` — SSH-пользователь
- `SSH_PRIVATE_KEY` — приватный ключ

## Тесты

```bash
python -m unittest discover tests/
```

## Структура проекта

```
config/
  hotels.yaml.example  — шаблон конфигурации отелей
  settings.py           — таймауты, задержки, ретраи
src/
  main.py               — оркестрация (3 пути: API, Camoufox, Playwright)
  db.py                 — SQLAlchemy сессии
  models.py             — Hotel, Price, ScrapeRun
  config_loader.py      — загрузка YAML, построение URL
  web.py                — JWT-embed Metabase дашборда
  parsers/
    base.py             — BaseParser (retry, captcha detection, parse_price_text)
    ostrovok.py         — Островок (API interception)
    ozon_travel.py      — Ozon Travel (Camoufox + DOM polling)
    yandex_travel.py    — Яндекс Путешествия (Camoufox + SmartCaptcha retry)
    otello.py           — Otello (API interception + DOM fallback)
    hotel_site.py       — TravelLine (прямой HTTP API, без браузера)
  utils/
    browser.py          — Playwright + stealth-скрипт
    antibot.py          — рандомные задержки, шаффл
    notifications.py    — Telegram-алерты (опционально)
```
