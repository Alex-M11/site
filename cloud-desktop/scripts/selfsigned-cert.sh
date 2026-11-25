#!/usr/bin/env bash
# Тимчасовий самопідписаний сертифікат: для тесту вдома або в локальній мережі коледжу.
# Браузер покаже попередження — для справжнього домену використовуйте scripts/letsencrypt.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
DOMAIN="${1:-$(grep -E '^CD_DOMAIN=' .env | cut -d= -f2)}"
mkdir -p certs certbot-www
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -subj "/CN=${DOMAIN}" -addext "subjectAltName=DNS:${DOMAIN}" \
  -keyout certs/privkey.pem -out certs/fullchain.pem
chmod 600 certs/privkey.pem
echo "Сертифікат для ${DOMAIN} створено в certs/"
