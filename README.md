# HotelDash.ru

Hotel price monitoring service. Scrapes prices daily from 5 OTAs (Yandex Travel, Ostrovok, Avito, T-Bank, OneTwoTrip), finds the cheapest rate and saves it to PostgreSQL.

**Stack:** Python + Playwright + PostgreSQL + Docker

## Quick Start (Docker)

```bash
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD

docker compose up -d db
docker compose build app
docker compose run --rm app python scripts/init_db.py
```

## Server Setup

One-command bootstrap for a fresh VPS:

```bash
ssh your-server 'bash -s' < scripts/setup_server.sh
```

Installs Docker, clones the repo, starts PostgreSQL, builds the app image, creates DB tables, and sets up a daily cron job.

## Usage

Full scraping run (all hotels, all sources, all dates):

```bash
docker compose run --rm app
```

Test a single parser:

```bash
docker compose run --rm app python scripts/run_once.py \
  --hotel metropol-moscow --source ostrovok --checkin 2026-03-20
```

## Configuration

Hotels and URL templates are configured in `config/hotels.yaml`.

Schedule parameters (`checkin_offsets_days`, `nights`, `adults`) are also in `hotels.yaml` and automatically substituted into URL templates via `{checkin}`, `{checkout}`, `{adults}`, `{nights}` placeholders.

## Cron

The setup script configures a daily cron job at 03:00 UTC (06:00 MSK):

```
0 3 * * * ~/hoteldash.ru/cron/hoteldash_cron.sh >> ~/hoteldash.ru/logs/cron.log 2>&1
```

## Deploy

Auto-deploy via GitHub Actions on push to `master`. Requires repository secrets:

- `SSH_HOST` — server IP
- `SSH_USERNAME` — SSH user
- `SSH_PRIVATE_KEY` — private key for SSH access

## Tests

```bash
python -m unittest discover tests/
```

## Project Structure

```
config/hotels.yaml      — hotel list with OTA URLs
config/settings.py      — timeouts, delays, retries
src/main.py             — orchestration
src/parsers/            — OTA parsers (Ostrovok, TBank, OneTwoTrip, Yandex, Avito)
src/utils/browser.py    — Playwright with anti-detect
src/utils/antibot.py    — delays, UA rotation
src/utils/notifications.py — Telegram alerts (optional)
```
