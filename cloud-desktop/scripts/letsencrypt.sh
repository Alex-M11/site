#!/usr/bin/env bash
# Безкоштовний сертифікат Let's Encrypt (потрібні публічний домен і відкритий порт 80).
# Перший запуск: bash scripts/selfsigned-cert.sh && docker compose up -d && bash scripts/letsencrypt.sh admin@college.edu.ua
# Автооновлення: додайте в crontab root:  17 3 * * 1  cd /opt/cloud-desktop && bash scripts/letsencrypt.sh renew
set -euo pipefail
cd "$(dirname "$0")/.."
DOMAIN="$(grep -E '^CD_DOMAIN=' .env | cut -d= -f2)"
mkdir -p certbot-www letsencrypt

if [ "${1:-}" = "renew" ]; then
  docker run --rm -v "$PWD/letsencrypt:/etc/letsencrypt" -v "$PWD/certbot-www:/var/www/certbot" \
    certbot/certbot renew --webroot -w /var/www/certbot --quiet
else
  EMAIL="${1:?Вкажіть email адміністратора: bash scripts/letsencrypt.sh admin@college.edu.ua}"
  docker run --rm -v "$PWD/letsencrypt:/etc/letsencrypt" -v "$PWD/certbot-www:/var/www/certbot" \
    certbot/certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" \
    --email "$EMAIL" --agree-tos --no-eff-email --non-interactive
fi

cp -L "letsencrypt/live/$DOMAIN/fullchain.pem" certs/fullchain.pem
cp -L "letsencrypt/live/$DOMAIN/privkey.pem" certs/privkey.pem
chmod 600 certs/privkey.pem
docker compose exec nginx nginx -s reload
echo "Сертифікат Let's Encrypt для $DOMAIN встановлено."
