# HotelDash.ru

Сервис мониторинга цен на отели. Ежедневно парсит цены с 5 OTA (Яндекс Путешествия, Островок, Авито, Т-Банк, OneTwoTrip), находит самый дешёвый тариф и сохраняет в PostgreSQL.

**Стек:** Python + Playwright + PostgreSQL

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Скопируйте `.env.example` в `.env` и заполните параметры подключения к БД:

```bash
cp .env.example .env
```

## Инициализация БД

```bash
python scripts/init_db.py
```

## Запуск

Полный запуск всех отелей и источников:

```bash
python -m src.main
```

Тестовый запуск одного парсера:

```bash
python scripts/run_once.py --hotel metropol-moscow --source ostrovok --checkin 2026-03-20
```

## Cron

```bash
# Ежедневно в 06:00 МСК (03:00 UTC)
0 3 * * * /path/to/hoteldash.ru/cron/hoteldash_cron.sh
```

## Тесты

```bash
python -m pytest tests/
```

## Конфигурация отелей

Отели и URL-шаблоны настраиваются в `config/hotels.yaml`.
