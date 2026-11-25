#!/usr/bin/env bash
# Завантажити базові образи Kasm і зібрати власні образи коледжу (тиждень 2).
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${CD_KASM_TAG:-$(grep -E '^CD_KASM_TAG=' .env 2>/dev/null | cut -d= -f2)}"
TAG="${TAG:-1.17.0}"

echo "==> Базові образи kasmweb (тег $TAG; перевірте актуальний на Docker Hub)"
for img in ubuntu-jammy-desktop kali-rolling-desktop vs-code; do
  docker pull "kasmweb/$img:$TAG"
done

echo "==> college/dev-desktop"
docker build -t college/dev-desktop:latest --build-arg KASM_TAG="$TAG" images/dev-desktop
echo "==> college/mysql-desktop"
docker build -t college/mysql-desktop:latest --build-arg KASM_TAG="$TAG" images/mysql-desktop

docker images | grep -E 'kasmweb|college'
