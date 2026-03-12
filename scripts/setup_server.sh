#!/bin/bash
# Первичная настройка VPS (запускать один раз)
# ssh hoteldash 'bash -s' < scripts/setup_server.sh

set -e

echo "=== Установка Docker ==="
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker установлен. Перелогинься (exit + ssh) для применения группы docker, затем запусти скрипт снова."
    exit 0
fi

echo "=== Клонирование репозитория ==="
if [ ! -d ~/hoteldash.ru ]; then
    git clone https://github.com/zavarovkv/hoteldash.ru.git ~/hoteldash.ru
fi

cd ~/hoteldash.ru

echo "=== Настройка .env ==="
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Создан .env — отредактируй пароль: nano ~/hoteldash.ru/.env"
fi

echo "=== Запуск БД ==="
docker compose up -d db

echo "=== Сборка приложения ==="
docker compose build app

echo "=== Миграция БД ==="
docker compose run --rm app python scripts/init_db.py

echo "=== Настройка cron ==="
CRON_LINE="0 3 * * * /home/$USER/hoteldash.ru/cron/hoteldash_cron.sh >> /home/$USER/hoteldash.ru/logs/cron.log 2>&1"
(crontab -l 2>/dev/null | grep -v hoteldash_cron; echo "$CRON_LINE") | crontab -

mkdir -p ~/hoteldash.ru/logs

echo ""
echo "=== Готово! ==="
echo "БД:    docker compose -f ~/hoteldash.ru/docker-compose.yml logs db"
echo "Тест:  cd ~/hoteldash.ru && docker compose run --rm app python scripts/run_once.py --hotel metropol-moscow --source ostrovok --checkin 2026-03-20"
echo "Cron:  crontab -l"
