#!/usr/bin/env bash
# Підготовка чистого Ubuntu Server 22.04/24.04 до запуску порталу (тиждень 1).
# Запуск: sudo bash scripts/install-server.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "Запустіть через sudo"; exit 1; fi
cd "$(dirname "$0")/.."
STORAGE_ROOT="${CD_STORAGE_ROOT:-/srv/cloud-desktop}"

echo "==> Оновлення системи"
apt-get update && apt-get -y upgrade
apt-get install -y ca-certificates curl gnupg ufw openssl iptables

if ! command -v docker >/dev/null; then
  echo "==> Встановлення Docker Engine (офіційний репозиторій)"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

echo "==> Налаштування Docker: ротація логів, більше мереж"
if [ ! -f /etc/docker/daemon.json ]; then
  cat > /etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "default-address-pools": [{ "base": "172.20.0.0/14", "size": 24 }]
}
JSON
  systemctl restart docker
fi

echo "==> Папка для файлів студентів: $STORAGE_ROOT"
mkdir -p "$STORAGE_ROOT/home" "$STORAGE_ROOT/submissions" "$STORAGE_ROOT/backups"
# Портал працює від uid 1000 (як і користувач усередині столів) — йому належать файли студентів.
chown 1000:1000 "$STORAGE_ROOT/home" "$STORAGE_ROOT/submissions"
chown root:1000 "$STORAGE_ROOT" && chmod 750 "$STORAGE_ROOT"
chmod 700 "$STORAGE_ROOT/backups"

echo "==> Мережа для столів (контейнери не бачать один одного)"
bash scripts/firewall.sh

echo "==> Брандмауер сервера: відкрито лише SSH, HTTP, HTTPS"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

if [ ! -f .env ]; then
  cp .env.example .env
  sed -i "s|^CD_SECRET_KEY=.*|CD_SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n/+=')|" .env
  sed -i "s|^MYSQL_PASSWORD=.*|MYSQL_PASSWORD=$(openssl rand -base64 24 | tr -d '\n/+=')|" .env
  sed -i "s|^MYSQL_ROOT_PASSWORD=.*|MYSQL_ROOT_PASSWORD=$(openssl rand -base64 24 | tr -d '\n/+=')|" .env
  sed -i "s|^GRAFANA_PASSWORD=.*|GRAFANA_PASSWORD=$(openssl rand -base64 18 | tr -d '\n/+=')|" .env
  sed -i "s|^DOCKER_GID=.*|DOCKER_GID=$(getent group docker | cut -d: -f3)|" .env
  chmod 600 .env
  echo "Створено .env з випадковими паролями. Відредагуйте CD_DOMAIN і CD_ADMIN_PASSWORD: nano .env"
fi

cat <<'TXT'

Готово. Далі:
  1. nano .env                          — домен і пароль адміністратора
  2. bash scripts/build-images.sh       — зібрати образи столів (10–30 хв)
  3. bash scripts/selfsigned-cert.sh    — тимчасовий сертифікат (або scripts/letsencrypt.sh)
  4. docker compose up -d --build       — запустити портал
TXT
