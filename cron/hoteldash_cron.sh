#!/bin/bash
# HotelDash — обёртка для crontab
# Использование в crontab:
# 0 3 * * * /path/to/hoteldash.ru/cron/hoteldash_cron.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_DIR/hoteldash_$(date +%Y%m%d_%H%M%S).log"

cd "$PROJECT_DIR"

# Активируем виртуальное окружение если есть
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
elif [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

echo "=== HotelDash запуск: $(date) ===" >> "$LOG_FILE"

python -m src.main >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "=== HotelDash завершён: $(date), код: $EXIT_CODE ===" >> "$LOG_FILE"

exit $EXIT_CODE
