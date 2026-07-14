#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP=/srv/ais_uzmo
readonly RUNTIME_DIR="$APP/runtime"
readonly THRESHOLDS_FILE="$RUNTIME_DIR/dashboard_thresholds.json"
readonly THRESHOLDS_HELPER="$APP/deploy/thresholds.sh"

die() {
    printf 'ПРОВЕРКА НЕ ПРОЙДЕНА: %s\n' "$*" >&2
    exit 1
}

ok() {
    printf '  [OK] %s\n' "$*"
}

[[ -f "$THRESHOLDS_HELPER" && ! -L "$THRESHOLDS_HELPER" ]] || \
    die "не найден безопасный helper $THRESHOLDS_HELPER"
# shellcheck disable=SC1090
source "$THRESHOLDS_HELPER"

[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "запустите скрипт через sudo"
[[ -d "$APP" && ! -L "$APP" ]] || die "каталог приложения отсутствует или является ссылкой"
[[ -f "$APP/.env" && ! -L "$APP/.env" && -f "$APP/RELEASE" && ! -L "$APP/RELEASE" ]] || \
    die "не найдена установленная программа"
[[ -f /etc/ais_uzmo/deploy.env && ! -L /etc/ais_uzmo/deploy.env ]] || \
    die "не найден /etc/ais_uzmo/deploy.env"

server_name="$(sed -n 's/^ALLOWED_HOSTS=//p' "$APP/.env" | head -n 1)"
server_name="${server_name%%,*}"
[[ "$server_name" =~ ^[A-Za-z0-9.-]+$ ]] || die "не удалось прочитать SERVER_NAME из .env"

printf 'Проверяется АИС УЗМО, версия %s.\n' "$(tr -d '[:space:]' <"$APP/RELEASE")"

for service in postgresql redis-server nginx ais_uzmo; do
    systemctl is-active --quiet "$service" || die "служба $service не запущена"
done
systemctl is-active --quiet ais-uzmo-backup.timer || die "таймер резервного копирования не запущен"
[[ "$(systemctl show -p Result --value ais-uzmo-backup.service)" == success ]] || \
    die "последний запуск резервного копирования завершился ошибкой"
ok "службы запущены"

nginx -t >/dev/null 2>&1 || die "ошибка в конфигурации Nginx"
ok "конфигурация Nginx"

runuser -u ais -- env DJANGO_SETTINGS_MODULE=config.settings_prod \
    "$APP/.venv/bin/python" "$APP/manage.py" check >/dev/null || \
    die "внутренняя проверка Django завершилась ошибкой"
runuser -u ais -- env DJANGO_SETTINGS_MODULE=config.settings_prod \
    "$APP/.venv/bin/python" "$APP/manage.py" migrate --check >/dev/null || \
    die "не применены миграции базы данных"
ok "приложение и миграции"

thresholds_env_line="$(grep '^ADMIN_THRESHOLDS_FILE=' "$APP/.env" || true)"
[[ "$thresholds_env_line" == "ADMIN_THRESHOLDS_FILE=$THRESHOLDS_FILE" ]] || \
    die "в .env должен быть единственный ADMIN_THRESHOLDS_FILE=$THRESHOLDS_FILE"
[[ -d "$RUNTIME_DIR" && ! -L "$RUNTIME_DIR" ]] || \
    die "каталог runtime отсутствует или является символической ссылкой"
[[ "$(stat -c '%U:%G:%a' "$RUNTIME_DIR")" == ais:ais:2750 ]] || \
    die "небезопасные права runtime; ожидаются ais:ais и 2750"
if [[ -e "$THRESHOLDS_FILE" || -L "$THRESHOLDS_FILE" ]]; then
    [[ -f "$THRESHOLDS_FILE" && ! -L "$THRESHOLDS_FILE" ]] || \
        die "файл порогов должен быть обычным файлом без символической ссылки"
    [[ "$(stat -c '%U:%G:%a' "$THRESHOLDS_FILE")" == ais:ais:640 ]] || \
        die "небезопасные права файла порогов; ожидаются ais:ais и 640"
    thresholds_validate_json "$APP/.venv/bin/python" "$THRESHOLDS_FILE" >/dev/null || \
        die "файл порогов содержит некорректный JSON"
fi
if ! runuser -u ais -- env RUNTIME_DIR="$RUNTIME_DIR" /bin/bash -c '
    set -Eeuo pipefail
    probe="$(mktemp "$RUNTIME_DIR/.deployment-write-check.XXXXXX")"
    cleanup_probe() { rm -f -- "$probe"; }
    trap cleanup_probe EXIT
    printf "%s\n" "runtime-write-ok" >"$probe"
    [[ "$(cat "$probe")" == runtime-write-ok ]]
'; then
    die "пользователь ais не может безопасно записывать в runtime"
fi
ok "постоянные настройки панели"

runuser -u ais -- env DJANGO_SETTINGS_MODULE=config.settings_prod \
    "$APP/.venv/bin/python" "$APP/manage.py" shell -c \
    "from django.conf import settings; from django.db import connection; assert not settings.DEBUG; connection.ensure_connection(); assert connection.vendor == 'postgresql'; print('ok')" \
    >/dev/null || die "приложение не подключается к PostgreSQL"
ok "PostgreSQL"

runuser -u ais -- env DJANGO_SETTINGS_MODULE=config.settings_prod \
    "$APP/.venv/bin/python" "$APP/manage.py" shell -c \
    "from django.core.cache import cache; cache.set('deployment-check', 'ok', 30); assert cache.get('deployment-check') == 'ok'; cache.delete('deployment-check'); print('ok')" \
    >/dev/null || die "приложение не подключается к Redis"
ok "Redis"

check_loopback_port() {
    local port=$1 label=$2 lines local_address
    lines="$(ss -H -ltn "sport = :$port")"
    [[ -n "$lines" ]] || die "$label не слушает порт $port"
    while IFS= read -r line; do
        local_address="$(awk '{print $4}' <<<"$line")"
        if [[ ! "$local_address" =~ ^127\.0\.0\.1:${port}$ && \
              ! "$local_address" =~ ^\[::1\]:${port}$ ]]; then
            die "$label доступен не только локально: $local_address"
        fi
    done <<<"$lines"
}

check_loopback_port 8000 Gunicorn
check_loopback_port 5432 PostgreSQL
check_loopback_port 6379 Redis
ok "служебные порты доступны только локально"

http_code="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' \
    -H "Host: $server_name" http://127.0.0.1:8000/accounts/login/)"
[[ "$http_code" == 200 ]] || die "Gunicorn вернул HTTP $http_code вместо 200"

http_code="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' \
    -H "Host: $server_name" http://127.0.0.1/accounts/login/)"
[[ "$http_code" == 200 ]] || die "Nginx вернул HTTP $http_code вместо 200"

http_code="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' \
    -H "Host: $server_name" http://127.0.0.1/static/img/favicon.svg)"
[[ "$http_code" == 200 ]] || die "статические файлы недоступны (HTTP $http_code)"

http_code="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' \
    -H "Host: $server_name" http://127.0.0.1/media/deployment-check)"
[[ "$http_code" == 404 ]] || die "каталог media ошибочно открыт напрямую (HTTP $http_code)"
ok "HTTP, статические и закрытые media-файлы"

latest_backup="$(find /var/backups/ais_uzmo/daily -mindepth 1 -maxdepth 1 \
    -type d -name '????????T??????.?????????Z' | sort | tail -n 1)"
[[ -n "$latest_backup" && -f "$latest_backup/COMPLETE" ]] || \
    die "нет завершённой резервной копии"
backup_age_seconds=$(($(date +%s) - $(stat -c %Y "$latest_backup/COMPLETE")))
((backup_age_seconds >= 0 && backup_age_seconds <= 36 * 60 * 60)) || \
    die "последняя резервная копия старше 36 часов"
(
    cd "$latest_backup"
    sha256sum -c SHA256SUMS >/dev/null
    pg_restore --list database.dump >/dev/null
    tar -tzf media.tar.gz >/dev/null
    if [[ -f dashboard_thresholds.json && ! -L dashboard_thresholds.json && \
          ! -e dashboard_thresholds.absent && ! -L dashboard_thresholds.absent ]]; then
        thresholds_validate_json "$APP/.venv/bin/python" dashboard_thresholds.json >/dev/null
    elif [[ -f dashboard_thresholds.absent && ! -L dashboard_thresholds.absent && \
            ! -e dashboard_thresholds.json && ! -L dashboard_thresholds.json && \
            ! -s dashboard_thresholds.absent ]]; then
        :
    else
        exit 1
    fi
) || die "последняя резервная копия повреждена"
ok "резервная копия"

[[ "$(stat -c '%U:%G:%a' "$APP/.env")" == root:ais:640 ]] || \
    die "небезопасные права файла .env"
[[ "$(stat -c '%U:%G:%a' /etc/ais_uzmo/deploy.env)" == root:root:600 ]] || \
    die "небезопасные права файла /etc/ais_uzmo/deploy.env"
ok "права доступа к секретам"

printf '\nВсе проверки пройдены.\n'
