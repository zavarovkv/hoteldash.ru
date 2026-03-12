#!/bin/bash
# HotelDash — ежедневный запуск парсера через cron
# 0 3 * * * /home/zavarov888/hoteldash.ru/cron/hoteldash_cron.sh >> /home/zavarov888/hoteldash.ru/logs/cron.log 2>&1

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

mkdir -p logs

echo "=== $(date) — Запуск ==="

docker compose run --rm app

echo "=== $(date) — Завершён ==="
