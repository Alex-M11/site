#!/usr/bin/env bash
# Запуск MySQL усередині столу. Kasm викликає цей скрипт після старту робочого столу
# і перезапускає його, якщо він завершився, тому:
#  * flock гарантує, що працює лише одна копія (друга чекає);
#  * файл .initialized з'являється лише після успішної ініціалізації — інакше починаємо з нуля.
set -u
DATADIR=/var/lib/mysql-desktop/data

exec 9>/tmp/custom_startup.lock
flock 9

if [ ! -f "$DATADIR/.initialized" ]; then
  rm -rf "$DATADIR"
  mkdir -p "$DATADIR"
  mysqld --initialize-insecure --datadir="$DATADIR" || exit 1
  mysqld --datadir="$DATADIR" &
  pid=$!
  for _ in $(seq 1 60); do mysqladmin ping --silent 2>/dev/null && break; sleep 1; done
  mysql -uroot <<'SQL' || { kill "$pid"; exit 1; }
CREATE USER IF NOT EXISTS 'student'@'localhost' IDENTIFIED BY 'student';
CREATE USER IF NOT EXISTS 'student'@'127.0.0.1' IDENTIFIED BY 'student';
GRANT ALL PRIVILEGES ON *.* TO 'student'@'localhost' WITH GRANT OPTION;
GRANT ALL PRIVILEGES ON *.* TO 'student'@'127.0.0.1' WITH GRANT OPTION;
CREATE DATABASE IF NOT EXISTS college CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
FLUSH PRIVILEGES;
SQL
  touch "$DATADIR/.initialized"
  wait "$pid"
else
  exec mysqld --datadir="$DATADIR"
fi
