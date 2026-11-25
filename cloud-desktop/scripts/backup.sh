#!/usr/bin/env bash
# Резервна копія бази даних і файлів студентів. Зберігаються останні KEEP_DAYS днів.
# Cron (щоночі о 02:30):  30 2 * * *  cd /opt/cloud-desktop && bash scripts/backup.sh >> /var/log/cd-backup.log 2>&1
# Скопіюйте каталог backups на інший диск або сервер — копія на тому ж диску не врятує від його поломки.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
STORAGE_ROOT="${CD_STORAGE_ROOT:-/srv/cloud-desktop}"
DEST="${BACKUP_DIR:-$STORAGE_ROOT/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y-%m-%d_%H%M)"
mkdir -p "$DEST"

echo "[$(date)] База даних…"
docker compose exec -T db sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines cloud_desktop' \
  | gzip > "$DEST/db_$STAMP.sql.gz"

echo "[$(date)] Файли студентів і здані роботи…"
tar --exclude='*/.cache' -C "$STORAGE_ROOT" -czf "$DEST/files_$STAMP.tar.gz" home submissions

find "$DEST" -name 'db_*.sql.gz' -mtime +"$KEEP_DAYS" -delete
find "$DEST" -name 'files_*.tar.gz' -mtime +"$KEEP_DAYS" -delete
echo "[$(date)] Готово: $(du -sh "$DEST" | cut -f1) у $DEST"

# Відновлення:
#   gunzip -c db_ДАТА.sql.gz | docker compose exec -T db sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" cloud_desktop'
#   tar -C /srv/cloud-desktop -xzf files_ДАТА.tar.gz
