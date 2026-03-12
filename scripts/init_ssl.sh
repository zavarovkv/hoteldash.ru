#!/bin/bash
# Получение SSL-сертификата Let's Encrypt
# Запускать на сервере после настройки DNS: A-запись hoteldash.ru → IP сервера

set -e

DOMAIN="hoteldash.ru"
EMAIL="${1:?Usage: $0 your@email.com}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT_DIR"

mkdir -p nginx/certbot/conf nginx/certbot/www

# Временный nginx без SSL для прохождения challenge
cat > nginx/conf.d/default.conf << 'EOF'
server {
    listen 80;
    server_name hoteldash.ru www.hoteldash.ru;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 200 'Setting up SSL...';
        add_header Content-Type text/plain;
    }
}
EOF

# Запускаем nginx
docker compose up -d nginx

# Получаем сертификат
docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN" \
    -d "www.$DOMAIN"

# Возвращаем полный конфиг с SSL
cat > nginx/conf.d/default.conf << 'EOF'
server {
    listen 80;
    server_name hoteldash.ru www.hoteldash.ru;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name hoteldash.ru www.hoteldash.ru;

    ssl_certificate /etc/letsencrypt/live/hoteldash.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/hoteldash.ru/privkey.pem;

    location / {
        proxy_pass http://metabase:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# Перезапускаем всё
docker compose up -d

echo ""
echo "SSL настроен! Откройте https://$DOMAIN"
