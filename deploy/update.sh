#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

update_self_test=false
update_temp_root=/run
if [[ "${1:-}" == --self-test-reexec ]]; then
    [[ "$#" -eq 2 && -d "$2" && ! -L "$2" ]] || {
        printf 'SELF-TEST ERROR: укажите обычный временный каталог.\n' >&2
        exit 1
    }
    update_self_test=true
    update_temp_root="$(cd -- "$2" && pwd -P)"
fi
update_self_copy="${AIS_UZMO_UPDATE_TEMP_COPY:-}"

cleanup_update_self_copy() {
    local path=${update_self_copy:-}
    [[ -n "$path" ]] || return 0
    case "$path" in
        "$update_temp_root"/ais-uzmo-update.*.sh) ;;
        *)
            printf 'Отказ удалять неожиданный путь временной копии update.sh: %s\n' "$path" >&2
            return 1
            ;;
    esac
    if [[ -e "$path" || -L "$path" ]]; then
        [[ -f "$path" && ! -L "$path" ]] || {
            printf 'Временная копия update.sh имеет небезопасный тип: %s\n' "$path" >&2
            return 1
        }
        rm -f -- "$path"
    fi
}

trap cleanup_update_self_copy EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "${AIS_UZMO_UPDATE_REEXEC:-}" != 1 ]]; then
    [[ "$update_self_test" == true || "${EUID:-$(id -u)}" -eq 0 ]] || {
        printf 'ОШИБКА: запустите скрипт через sudo.\n' >&2
        exit 1
    }
    [[ -f "$0" && ! -L "$0" ]] || {
        printf 'ОШИБКА: update.sh должен быть обычным файлом без символической ссылки.\n' >&2
        exit 1
    }
    update_self_copy="$(mktemp "$update_temp_root/ais-uzmo-update.XXXXXX.sh")"
    if [[ "$update_self_test" == true ]]; then
        install -m 0700 "$0" "$update_self_copy"
    else
        install -o root -g root -m 0700 "$0" "$update_self_copy"
    fi
    exec env \
        AIS_UZMO_UPDATE_REEXEC=1 \
        AIS_UZMO_UPDATE_TEMP_COPY="$update_self_copy" \
        /bin/bash "$update_self_copy" "$@"
    status=$?
    printf 'ОШИБКА: не удалось запустить защищённую временную копию update.sh.\n' >&2
    exit "$status"
fi

case "$update_self_copy" in
    "$update_temp_root"/ais-uzmo-update.*.sh) ;;
    *)
        printf 'ОШИБКА: некорректный путь временной копии update.sh.\n' >&2
        exit 1
        ;;
esac
[[ "$0" == "$update_self_copy" && -f "$update_self_copy" && ! -L "$update_self_copy" ]] || {
    printf 'ОШИБКА: не подтверждён запуск временной копии update.sh.\n' >&2
    exit 1
}
update_self_stat="$(stat -c '%u:%g:%a' "$update_self_copy")"
if [[ "$update_self_test" == true ]]; then
    [[ "$update_self_stat" == "$(id -u):$(id -g):700" || \
       "$update_self_stat" == "$(id -u):$(id -g):750" || \
       "$update_self_stat" == "$(id -u):$(id -g):755" ]] || {
        printf 'SELF-TEST ERROR: небезопасные права временной копии update.sh: %s.\n' \
            "$update_self_stat" >&2
        exit 1
    }
else
    [[ "$update_self_stat" == 0:0:700 ]] || {
        printf 'ОШИБКА: небезопасные права временной копии update.sh.\n' >&2
        exit 1
    }
fi
unset AIS_UZMO_UPDATE_REEXEC AIS_UZMO_UPDATE_TEMP_COPY
if [[ "$update_self_test" == true ]]; then
    printf 'SELF-TEST OK: update.sh запущен из временной копии.\n'
    exit 0
fi

readonly APP=/srv/ais_uzmo
readonly RUNTIME_DIR="$APP/runtime"
readonly THRESHOLDS_FILE="$RUNTIME_DIR/dashboard_thresholds.json"
readonly LEGACY_THRESHOLDS_FILE="$APP/dashboard_thresholds.json"
readonly THRESHOLDS_HELPER="$APP/deploy/thresholds.sh"
readonly LOCK_FILE=/run/lock/ais-uzmo-update.lock
readonly ARCHIVE_INPUT="${1:-}"
readonly CHECKSUM_INPUT="${2:-}"

die() {
    printf 'ОШИБКА: %s\n' "$*" >&2
    exit 1
}

step() {
    printf '\n==> %s\n' "$*"
}

[[ -f "$THRESHOLDS_HELPER" && ! -L "$THRESHOLDS_HELPER" ]] || \
    die "Не найден безопасный helper $THRESHOLDS_HELPER."
# shellcheck disable=SC1090
source "$THRESHOLDS_HELPER"

validate_ipv4_cidr() {
    local value=$1 a b c d prefix
    [[ "$value" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]] || return 1
    IFS='./' read -r a b c d prefix <<<"$value"
    for octet in "$a" "$b" "$c" "$d"; do
        [[ "$octet" == 0 || "$octet" != 0* ]] || return 1
        ((10#$octet >= 0 && 10#$octet <= 255)) || return 1
    done
    [[ "$prefix" != 0* ]] || return 1
    ((10#$prefix >= 1 && 10#$prefix <= 32))
}

normalize_venv_permissions() {
    chown -R root:ais "$APP/.venv"
    chmod -R u=rwX,g=rX,o= "$APP/.venv"
}

wait_for_backup_service() {
    local waited=0
    while systemctl is-active --quiet ais-uzmo-backup.service; do
        ((waited < 900)) || die "Резервное копирование не завершилось за 15 минут. Обновление не начато."
        sleep 1
        waited=$((waited + 1))
    done
}

install_python_requirements() {
    local release_root=$1 archive_parent=$2 wheelhouse="" candidate
    for candidate in \
        "$release_root/wheelhouse" \
        "$release_root/deploy/wheelhouse" \
        "$archive_parent/wheelhouse"; do
        [[ -d "$candidate" ]] || continue
        if compgen -G "$candidate/*.whl" >/dev/null; then
            wheelhouse=$candidate
            break
        fi
    done

    if [[ -n "$wheelhouse" ]]; then
        printf 'Используется локальный набор Python-пакетов: %s\n' "$wheelhouse"
        [[ -f "$wheelhouse/SHA256SUMS" ]] || \
            die "В локальном wheelhouse нет SHA256SUMS. Запросите проверенный комплект зависимостей."
        (cd "$wheelhouse" && sha256sum -c SHA256SUMS >/dev/null) || \
            die "Контрольная сумма wheelhouse не совпала. Комплект зависимостей использовать нельзя."
        "$APP/.venv/bin/python" -m pip install \
            --disable-pip-version-check --no-index --find-links="$wheelhouse" \
            -r "$APP/requirements.txt"
    elif ! "$APP/.venv/bin/python" -m pip install \
        --disable-pip-version-check -r "$APP/requirements.txt"; then
        die "Python-пакеты недоступны. Настройте внутренний PyPI или положите каталог wheelhouse рядом с архивом."
    fi
    "$APP/.venv/bin/python" -m pip check
    normalize_venv_permissions
}

[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Запустите скрипт через sudo."
exec 8>"$LOCK_FILE"
flock -n 8 || die "Другое обновление уже выполняется. Дождитесь его завершения."

[[ -n "$ARCHIVE_INPUT" ]] || \
    die "Укажите архив релиза: sudo bash $APP/deploy/update.sh /путь/ais_uzmo-X.Y.Z.tar.gz"
[[ -f "$ARCHIVE_INPUT" ]] || die "Архив не найден: $ARCHIVE_INPUT"
for directory in "$APP" "$APP/.venv" "$APP/media" "$APP/logs" "$APP/staticfiles"; do
    [[ -d "$directory" && ! -L "$directory" ]] || \
        die "Ожидался обычный каталог без символической ссылки: $directory"
done
if [[ -e "$RUNTIME_DIR" || -L "$RUNTIME_DIR" ]]; then
    [[ -d "$RUNTIME_DIR" && ! -L "$RUNTIME_DIR" ]] || \
        die "Ожидался обычный каталог без символической ссылки: $RUNTIME_DIR"
fi
thresholds_source="$(thresholds_select_source "$THRESHOLDS_FILE" "$LEGACY_THRESHOLDS_FILE")" || \
    die "Не удалось безопасно выбрать файл порогов."
for file in "$APP/.env" "$APP/RELEASE" /etc/nginx/sites-available/ais_uzmo; do
    [[ -f "$file" && ! -L "$file" ]] || \
        die "Ожидался обычный файл без символической ссылки: $file"
done
thresholds_env_line="$(grep '^ADMIN_THRESHOLDS_FILE=' "$APP/.env" || true)"
thresholds_env_missing=true
if [[ -n "$thresholds_env_line" ]]; then
    [[ "$thresholds_env_line" == "ADMIN_THRESHOLDS_FILE=$THRESHOLDS_FILE" ]] || \
        die "В .env должен быть единственный ADMIN_THRESHOLDS_FILE=$THRESHOLDS_FILE"
    thresholds_env_missing=false
fi
[[ -x "$APP/.venv/bin/python" ]] || die "Не найден рабочий Python в $APP/.venv."
thresholds_validate_json "$APP/.venv/bin/python" "$thresholds_source" || \
    die "Файл порогов содержит некорректный JSON."
[[ -f /etc/ais_uzmo/deploy.env && ! -L /etc/ais_uzmo/deploy.env ]] || \
    die "Не найден /etc/ais_uzmo/deploy.env. Обновление остановлено: нужны сохранённые SERVER_NAME и TRUSTED_CIDR."
[[ "$(stat -c '%U:%G:%a' /etc/ais_uzmo/deploy.env)" == root:root:600 ]] || \
    die "Небезопасные права /etc/ais_uzmo/deploy.env; ожидаются root:root и 600."

# This root-only file was generated by install.sh from validated values.
# shellcheck disable=SC1091
source /etc/ais_uzmo/deploy.env
: "${SERVER_NAME:?В /etc/ais_uzmo/deploy.env нет SERVER_NAME}"
: "${TRUSTED_CIDR:?В /etc/ais_uzmo/deploy.env нет TRUSTED_CIDR}"
[[ "$SERVER_NAME" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$ ]] || \
    die "Некорректный SERVER_NAME в /etc/ais_uzmo/deploy.env."
validate_ipv4_cidr "$TRUSTED_CIDR" || \
    die "Некорректный TRUSTED_CIDR в /etc/ais_uzmo/deploy.env."

readonly ARCHIVE="$(readlink -f -- "$ARCHIVE_INPUT")"
readonly ARCHIVE_DIR="$(dirname -- "$ARCHIVE")"
readonly ARCHIVE_NAME="$(basename -- "$ARCHIVE")"

checksum_file=$CHECKSUM_INPUT
if [[ -z "$checksum_file" ]]; then
    if [[ -f "$ARCHIVE_DIR/SHA256SUMS" ]]; then
        checksum_file="$ARCHIVE_DIR/SHA256SUMS"
    elif [[ -f "$ARCHIVE.sha256" ]]; then
        checksum_file="$ARCHIVE.sha256"
    else
        die "Рядом с архивом нет SHA256SUMS или $ARCHIVE_NAME.sha256."
    fi
fi
[[ -f "$checksum_file" ]] || die "Не найден файл контрольной суммы: $checksum_file"

expected_hash="$(awk -v target="$ARCHIVE_NAME" '
    {
        name=$2
        sub(/^\*/, "", name)
        sub(/^\.\//, "", name)
        if (name == target) { print tolower($1); exit }
    }
' "$checksum_file")"
if [[ -z "$expected_hash" ]]; then
    expected_hash="$(awk 'NR == 1 { print tolower($1) }' "$checksum_file")"
fi
[[ "$expected_hash" =~ ^[0-9a-f]{64}$ ]] || \
    die "В файле контрольной суммы нет записи для $ARCHIVE_NAME."
actual_hash="$(sha256sum -- "$ARCHIVE" | awk '{print tolower($1)}')"
[[ "$actual_hash" == "$expected_hash" ]] || die "Контрольная сумма архива не совпала. Архив использовать нельзя."

tar -tzf "$ARCHIVE" >/dev/null || die "Архив повреждён или имеет неверный формат."
while IFS= read -r entry; do
    [[ "$entry" != /* && "$entry" != ../* && "$entry" != *'/../'* && "$entry" != *'/..' ]] || \
        die "В архиве найден небезопасный путь: $entry"
done < <(tar -tzf "$ARCHIVE")
while read -r mode _; do
    case "${mode:0:1}" in
        -|d) ;;
        *) die "Архив содержит неподдерживаемый специальный файл." ;;
    esac
done < <(tar -tvzf "$ARCHIVE")

extract_dir="$(mktemp -d /var/tmp/ais-uzmo-release.XXXXXX)"
timer_was_active=false
timer_was_enabled=false
timer_stopped=false
app_was_active=false
mutation_started=false
update_complete=false
pre_update_backup=""
source_backup=""

cleanup() {
    local status=$?
    trap - EXIT HUP INT TERM
    set +e
    rm -rf -- "$extract_dir"
    if [[ "$update_complete" != true && "$mutation_started" == true ]]; then
        systemctl stop ais-uzmo-backup.service
        systemctl disable --now ais-uzmo-backup.timer
        systemctl disable --now ais_uzmo.service
        printf '\nОбновление остановилось после изменения файлов или базы.\n' >&2
        printf 'Приложение и резервное копирование оставлены остановленными, чтобы не запустить несовместимое состояние.\n' >&2
        printf 'Резервная копия до обновления: %s\n' "$pre_update_backup" >&2
        printf 'Копия предыдущего исходного кода: %s\n' "$source_backup" >&2
        printf 'Передайте этот вывод разработчику; не запускайте службы вручную.\n' >&2
    elif [[ "$update_complete" != true ]]; then
        if [[ "$app_was_active" == true ]]; then
            systemctl start ais_uzmo.service
        fi
        if [[ "$timer_was_active" == true && "$timer_stopped" == true ]]; then
            systemctl start ais-uzmo-backup.timer
        fi
    fi
    cleanup_update_self_copy || true
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

tar -xzf "$ARCHIVE" --no-same-owner --no-same-permissions -C "$extract_dir"
if find "$extract_dir" -type l -print -quit | grep -q .; then
    die "Архив содержит символические ссылки; такой релиз не устанавливается."
fi

if [[ -f "$extract_dir/manage.py" ]]; then
    release_root=$extract_dir
else
    mapfile -t top_entries < <(find "$extract_dir" -mindepth 1 -maxdepth 1 -print)
    [[ ${#top_entries[@]} -eq 1 && -d "${top_entries[0]}" ]] || \
        die "В архиве должен быть один каталог релиза."
    release_root=${top_entries[0]}
fi

[[ -f "$release_root/manage.py" && -f "$release_root/requirements.txt" ]] || \
    die "В архиве нет полного приложения."
[[ -f "$release_root/deploy/VERSION" ]] || die "В архиве нет deploy/VERSION."
for required in \
    config/settings_prod.py \
    deploy/check.sh deploy/update.sh deploy/backup.sh deploy/release.sh deploy/thresholds.sh \
    deploy/ais_uzmo.service deploy/nginx.conf.template \
    deploy/ais-uzmo-backup.service deploy/ais-uzmo-backup.timer; do
    [[ -f "$release_root/$required" ]] || die "В архиве нет обязательного файла $required."
done
new_version="$(tr -d '[:space:]' <"$release_root/deploy/VERSION")"
current_version="$(tr -d '[:space:]' <"$APP/RELEASE")"
[[ "$new_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || \
    die "Некорректная версия релиза: $new_version"
[[ "$current_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || \
    die "Некорректная текущая версия: $current_version"

printf 'Обновление АИС УЗМО: %s -> %s.\n' "$current_version" "$new_version"
[[ "$new_version" != "$current_version" ]] || \
    die "Эта версия уже установлена: $new_version. Повторная установка запрещена."
highest_version="$(printf '%s\n%s\n' "$current_version" "$new_version" | LC_ALL=C sort -V | tail -n 1)"
[[ "$highest_version" == "$new_version" ]] || \
    die "Понижение версии запрещено: $current_version -> $new_version."

step "Резервная копия перед обновлением"
if systemctl is-enabled --quiet ais-uzmo-backup.timer; then
    timer_was_enabled=true
fi
if systemctl is-active --quiet ais-uzmo-backup.timer; then
    timer_was_active=true
fi
systemctl stop ais-uzmo-backup.timer
timer_stopped=true

# A timer job may already have started the oneshot service. Let it finish before
# taking the dedicated pre-update backup, now that the timer cannot race us.
wait_for_backup_service
backup_before="$(find /var/backups/ais_uzmo/daily -mindepth 1 -maxdepth 1 \
    -type d -name '????????T??????.?????????Z' | sort | tail -n 1)"
systemctl reset-failed ais-uzmo-backup.service || true
systemctl start ais-uzmo-backup.service
wait_for_backup_service
[[ "$(systemctl show -p Result --value ais-uzmo-backup.service)" == success ]] || \
    die "Не удалось создать резервную копию. Обновление не начато."
pre_update_backup="$(find /var/backups/ais_uzmo/daily -mindepth 1 -maxdepth 1 \
    -type d -name '????????T??????.?????????Z' | sort | tail -n 1)"
[[ -n "$pre_update_backup" && "$pre_update_backup" != "$backup_before" ]] || \
    die "Не удалось подтвердить создание новой резервной копии. Обновление не начато."
[[ -f "$pre_update_backup/COMPLETE" ]] || die "Резервная копия не завершена."

if systemctl is-active --quiet ais_uzmo.service; then
    app_was_active=true
    systemctl stop ais_uzmo.service
fi

thresholds_source="$(thresholds_select_source "$THRESHOLDS_FILE" "$LEGACY_THRESHOLDS_FILE")" || \
    die "Файлы порогов изменились и больше не могут быть выбраны безопасно."
thresholds_validate_json "$APP/.venv/bin/python" "$thresholds_source" || \
    die "Файл порогов содержит некорректный JSON."

step "Сохранение предыдущего исходного кода"
source_backup_root=/var/backups/ais_uzmo/releases
install -d -o root -g root -m 0700 "$source_backup_root"
source_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
source_backup="$source_backup_root/source-$current_version-$source_stamp.tar.gz"
tar -C "$APP" \
    --exclude='./.env' --exclude='./.venv' --exclude='./media' \
    --exclude='./logs' --exclude='./runtime' --exclude='./staticfiles' \
    -czf "$source_backup" .
find "$source_backup_root" -mindepth 1 -maxdepth 1 -type f \
    -name 'source-*.tar.gz' -mtime +30 -delete

step "Установка нового исходного кода"
mutation_started=true
install -d -o ais -g ais -m 2750 "$RUNTIME_DIR"
if [[ ! -e "$THRESHOLDS_FILE" && "$thresholds_source" == "$LEGACY_THRESHOLDS_FILE" ]]; then
    install -o ais -g ais -m 0640 "$thresholds_source" "$THRESHOLDS_FILE"
fi
rsync -a --delete --chown=root:root --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
    --exclude '/.git/' \
    --exclude '/.env' \
    --exclude '/.venv/' \
    --exclude '/db.sqlite3' \
    --exclude '*.sqlite3' \
    --exclude '/media/' \
    --exclude '/logs/' \
    --exclude '/runtime/' \
    --exclude '/staticfiles/' \
    --exclude '/RELEASE' \
    --exclude '/wheelhouse/' \
    --exclude '/deploy/wheelhouse/' \
    --exclude '/deploy/install.env' \
    "$release_root/" "$APP/"
chmod 0755 "$APP"
if [[ "$thresholds_env_missing" == true ]]; then
    printf '\nADMIN_THRESHOLDS_FILE=%s\n' "$THRESHOLDS_FILE" >>"$APP/.env"
fi
chown root:ais "$APP/.env"
chmod 0640 "$APP/.env"
chown -R ais:ais "$APP/media" "$APP/logs" "$RUNTIME_DIR"
find "$APP/media" "$APP/logs" "$RUNTIME_DIR" -type d -exec chmod 2750 {} +
find "$APP/media" "$APP/logs" "$RUNTIME_DIR" -type f -exec chmod 0640 {} +
chmod 0755 "$APP/deploy/install.sh" "$APP/deploy/check.sh" \
    "$APP/deploy/update.sh" "$APP/deploy/backup.sh" "$APP/deploy/release.sh"

install_python_requirements "$release_root" "$ARCHIVE_DIR"

step "Миграции и статические файлы"
runuser -u ais -- env DJANGO_SETTINGS_MODULE=config.settings_prod \
    "$APP/.venv/bin/python" "$APP/manage.py" migrate --noinput
env DJANGO_SETTINGS_MODULE=config.settings_prod \
    "$APP/.venv/bin/python" "$APP/manage.py" collectstatic --noinput --clear
chown -R root:root "$APP/staticfiles"
find "$APP/staticfiles" -type d -exec chmod 0755 {} +
find "$APP/staticfiles" -type f -exec chmod 0644 {} +
printf '%s\n' "$new_version" >"$APP/RELEASE"
chown root:root "$APP/RELEASE"
chmod 0644 "$APP/RELEASE"

nginx_candidate="$extract_dir/ais_uzmo.nginx"
nginx_previous="$extract_dir/ais_uzmo.nginx.previous"
sed -e "s|__SERVER_NAME__|$SERVER_NAME|g" \
    -e "s|__TRUSTED_CIDR__|$TRUSTED_CIDR|g" \
    "$APP/deploy/nginx.conf.template" >"$nginx_candidate"
cp -a /etc/nginx/sites-available/ais_uzmo "$nginx_previous"
install -o root -g root -m 0644 "$nginx_candidate" \
    /etc/nginx/sites-available/ais_uzmo
if ! nginx -t; then
    cp -a "$nginx_previous" /etc/nginx/sites-available/ais_uzmo
    nginx -t || true
    die "Новая конфигурация Nginx не прошла проверку; предыдущая конфигурация возвращена."
fi

step "Перезапуск служб"
install -o root -g root -m 0644 "$APP/deploy/ais_uzmo.service" \
    /etc/systemd/system/ais_uzmo.service
install -o root -g root -m 0700 "$APP/deploy/backup.sh" \
    /usr/local/sbin/ais-uzmo-backup
install -o root -g root -m 0644 "$APP/deploy/ais-uzmo-backup.service" \
    /etc/systemd/system/ais-uzmo-backup.service
install -o root -g root -m 0644 "$APP/deploy/ais-uzmo-backup.timer" \
    /etc/systemd/system/ais-uzmo-backup.timer
systemd-analyze verify /etc/systemd/system/ais_uzmo.service
systemctl daemon-reload
systemctl start ais_uzmo.service
systemctl is-active --quiet ais_uzmo.service || die "Приложение не запустилось после обновления."
systemctl reload nginx

step "Резервная копия после обновления"
systemctl start ais-uzmo-backup.service
[[ "$(systemctl show -p Result --value ais-uzmo-backup.service)" == success ]] || \
    die "После обновления не удалось создать резервную копию."
if [[ "$timer_was_enabled" == true ]]; then
    systemctl enable ais-uzmo-backup.timer
else
    systemctl disable ais-uzmo-backup.timer
fi
if [[ "$timer_was_active" == true ]]; then
    systemctl start ais-uzmo-backup.timer
fi
timer_stopped=false

step "Итоговая проверка"
"$APP/deploy/check.sh"

update_complete=true
rm -rf -- "$extract_dir"
cleanup_update_self_copy
trap - EXIT HUP INT TERM
printf '\nОбновление до версии %s завершено.\n' "$new_version"
printf 'Резервная копия до обновления: %s\n' "$pre_update_backup"
printf 'Копия предыдущего исходного кода: %s\n' "$source_backup"
