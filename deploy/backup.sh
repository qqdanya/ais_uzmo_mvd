#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly APP=/srv/ais_uzmo
readonly RUNTIME_DIR="$APP/runtime"
readonly THRESHOLDS_FILE="$RUNTIME_DIR/dashboard_thresholds.json"
readonly LEGACY_THRESHOLDS_FILE="$APP/dashboard_thresholds.json"
readonly THRESHOLDS_HELPER="$APP/deploy/thresholds.sh"
readonly BACKUP_ROOT=/var/backups/ais_uzmo/daily
readonly STAMP="$(date -u +%Y%m%dT%H%M%S.%NZ)"
readonly STAGING="$BACKUP_ROOT/.staging-$STAMP-$$"
readonly DEST="$BACKUP_ROOT/$STAMP"
readonly LOCK_FILE=/run/lock/ais-uzmo-backup.lock

was_active=false
complete=false

exec 9>"$LOCK_FILE"
flock -n 9 || {
    printf 'Резервное копирование уже выполняется.\n' >&2
    exit 75
}

cleanup() {
    local status=$?
    trap - EXIT HUP INT TERM
    set +e
    if [[ "$was_active" == true ]]; then
        systemctl start ais_uzmo.service
    fi
    if [[ "$complete" != true ]]; then
        rm -rf -- "$STAGING"
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

[[ -f "$THRESHOLDS_HELPER" && ! -L "$THRESHOLDS_HELPER" ]] || {
    printf 'Не найден безопасный helper %s.\n' "$THRESHOLDS_HELPER" >&2
    exit 1
}
# shellcheck disable=SC1090
source "$THRESHOLDS_HELPER"

[[ -d "$APP" && ! -L "$APP" && -d "$APP/media" && ! -L "$APP/media" ]] || {
    printf 'Каталоги приложения или media отсутствуют либо являются ссылками.\n' >&2
    exit 1
}
if [[ -e "$RUNTIME_DIR" || -L "$RUNTIME_DIR" ]]; then
    [[ -d "$RUNTIME_DIR" && ! -L "$RUNTIME_DIR" ]] || {
        printf 'Каталог runtime является символической ссылкой или не является каталогом.\n' >&2
        exit 1
    }
    [[ "$(stat -c '%U:%G:%a' "$RUNTIME_DIR")" == ais:ais:2750 ]] || {
        printf 'Небезопасные права каталога runtime; ожидаются ais:ais и 2750.\n' >&2
        exit 1
    }
fi
for required in "$APP/.env" "$APP/RELEASE"; do
    [[ -f "$required" && ! -L "$required" ]] || {
        printf 'Не найден обязательный обычный файл: %s\n' "$required" >&2
        exit 1
    }
done

install -d -o root -g root -m 0700 "$BACKUP_ROOT"
install -d -o root -g root -m 0700 "$STAGING"
[[ ! -e "$DEST" ]]

if systemctl is-active --quiet ais_uzmo.service; then
    was_active=true
    systemctl stop ais_uzmo.service
fi

runuser -u postgres -- pg_dump --format=custom --no-owner --no-privileges \
    ais_uzmo >"$STAGING/database.dump"
tar -C "$APP" -czf "$STAGING/media.tar.gz" media
thresholds_backup_entry=dashboard_thresholds.absent
thresholds_source="$(thresholds_select_source "$THRESHOLDS_FILE" "$LEGACY_THRESHOLDS_FILE")" || exit 1
if [[ -n "$thresholds_source" ]]; then
    if [[ "$thresholds_source" == "$THRESHOLDS_FILE" && \
          "$(stat -c '%U:%G:%a' "$THRESHOLDS_FILE")" != ais:ais:640 ]]; then
        printf 'Небезопасные права файла порогов; ожидаются ais:ais и 640.\n' >&2
        exit 1
    fi
    thresholds_validate_json "$APP/.venv/bin/python" "$thresholds_source"
    cp --preserve=mode,timestamps "$thresholds_source" "$STAGING/dashboard_thresholds.json"
    thresholds_backup_entry=dashboard_thresholds.json
else
    : >"$STAGING/dashboard_thresholds.absent"
fi
cp --preserve=mode,timestamps "$APP/.env" "$STAGING/app.env"
cp --preserve=mode,timestamps "$APP/RELEASE" "$STAGING/RELEASE"
cp -a /etc/systemd/system/ais_uzmo.service "$STAGING/"
cp -a /etc/nginx/sites-available/ais_uzmo "$STAGING/"
cp -a /etc/ais_uzmo/deploy.env "$STAGING/deploy.env"
cp -a /etc/redis/ais_uzmo.conf "$STAGING/redis-ais_uzmo.conf"

pg_restore --list "$STAGING/database.dump" >/dev/null
pg_restore --exit-on-error --file=/dev/null "$STAGING/database.dump"
tar -tzf "$STAGING/media.tar.gz" >/dev/null
if [[ "$thresholds_backup_entry" == dashboard_thresholds.json ]]; then
    thresholds_validate_json "$APP/.venv/bin/python" "$STAGING/dashboard_thresholds.json"
else
    [[ -f "$STAGING/dashboard_thresholds.absent" && \
       ! -s "$STAGING/dashboard_thresholds.absent" ]]
fi
(
    cd "$STAGING"
    sha256sum database.dump media.tar.gz "$thresholds_backup_entry" app.env \
        RELEASE ais_uzmo.service ais_uzmo deploy.env redis-ais_uzmo.conf \
        >SHA256SUMS
    sha256sum -c SHA256SUMS >/dev/null
)
touch "$STAGING/COMPLETE"
mv "$STAGING" "$DEST"
complete=true

if [[ "$was_active" == true ]]; then
    systemctl start ais_uzmo.service
    systemctl is-active --quiet ais_uzmo.service
    was_active=false
fi

# Only timestamped daily backups are removed. Other directories are untouched.
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d \
    -name '????????T??????.?????????Z' -mtime +14 -exec rm -rf -- {} +

trap - EXIT HUP INT TERM
printf 'Резервная копия создана: %s\n' "$DEST"
