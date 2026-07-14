#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SOURCE_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
readonly APP=/srv/ais_uzmo
readonly CONFIG_PATH="${1:-$SCRIPT_DIR/install.env}"

die() {
    printf 'ОШИБКА: %s\n' "$*" >&2
    exit 1
}

step() {
    printf '\n==> %s\n' "$*"
}

require_root() {
    [[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Запустите скрипт через sudo."
}

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

parse_install_config() {
    local raw_line line_number=0 key value
    declare -A seen_keys=()

    SERVER_NAME=""
    TRUSTED_CIDR=""
    ADMIN_USERNAME=""
    ADMIN_EMAIL=""
    ENABLE_UFW=true
    SSH_PORT=22

    while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
        ((line_number += 1))
        raw_line=${raw_line%$'\r'}
        [[ "$raw_line" =~ ^[[:space:]]*$ ]] && continue
        [[ "$raw_line" =~ ^[[:space:]]*# ]] && continue
        [[ "$raw_line" =~ ^([A-Z_][A-Z0-9_]*)=(.*)$ ]] || \
            die "Некорректная строка $line_number в install.env: ожидается KEY=value без кавычек и пробелов."

        key=${BASH_REMATCH[1]}
        value=${BASH_REMATCH[2]}
        case "$key" in
            SERVER_NAME|TRUSTED_CIDR|ADMIN_USERNAME|ADMIN_EMAIL|ENABLE_UFW|SSH_PORT) ;;
            *) die "Неизвестный параметр $key в строке $line_number файла install.env." ;;
        esac
        [[ -z "${seen_keys[$key]+x}" ]] || \
            die "Параметр $key повторяется в install.env."
        seen_keys[$key]=1
        printf -v "$key" '%s' "$value"
    done <"$CONFIG_PATH"
}

validate_packaged_nginx_default() {
    local default_site=/etc/nginx/sites-enabled/default

    [[ -e "$default_site" || -L "$default_site" ]] || return 0
    [[ -L "$default_site" ]] || \
        die "$default_site не является стандартной ссылкой Nginx. Удалите или перенастройте его вручную."
    [[ "$(readlink -- "$default_site")" == /etc/nginx/sites-available/default ]] || \
        die "$default_site указывает на нестандартный файл. Удалите или перенастройте его вручную."
}

remove_packaged_nginx_default() {
    local default_site=/etc/nginx/sites-enabled/default

    validate_packaged_nginx_default
    [[ -e "$default_site" || -L "$default_site" ]] || return 0
    rm -- "$default_site"
}

normalize_venv_permissions() {
    chown -R root:ais "$APP/.venv"
    chmod -R u=rwX,g=rX,o= "$APP/.venv"
}

install_python_requirements() {
    local release_root=$1
    local archive_parent=${2:-}
    local wheelhouse=""
    local candidate

    for candidate in \
        "$release_root/wheelhouse" \
        "$release_root/deploy/wheelhouse" \
        "${archive_parent:+$archive_parent/wheelhouse}"; do
        [[ -n "$candidate" && -d "$candidate" ]] || continue
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
        "$APP/.venv/bin/python" -m pip check
        normalize_venv_permissions
        return
    fi

    if ! "$APP/.venv/bin/python" -m pip install \
        --disable-pip-version-check -r "$APP/requirements.txt"; then
        die "Python-пакеты недоступны. Настройте внутренний PyPI или положите каталог wheelhouse рядом с релизом и повторите установку на чистом сервере."
    fi
    "$APP/.venv/bin/python" -m pip check
    normalize_venv_permissions
}

require_root
[[ -f "$CONFIG_PATH" ]] || die "Не найден файл настроек $CONFIG_PATH. Скопируйте install.env.example в install.env и заполните его."
[[ -f "$SOURCE_ROOT/manage.py" && -f "$SOURCE_ROOT/requirements.txt" ]] || \
    die "Скрипт нужно запускать из распакованного полного релиза."
[[ -f "$SCRIPT_DIR/VERSION" ]] || die "В релизе нет deploy/VERSION."
for required in \
    config/settings_prod.py \
    deploy/check.sh deploy/update.sh deploy/backup.sh deploy/release.sh deploy/thresholds.sh \
    deploy/ais_uzmo.service deploy/nginx.conf.template \
    deploy/ais-uzmo-backup.service deploy/ais-uzmo-backup.timer; do
    [[ -f "$SOURCE_ROOT/$required" ]] || die "В релизе нет обязательного файла $required."
done
if find "$SOURCE_ROOT" ! -type f ! -type d -print -quit | grep -q .; then
    die "Релиз содержит неподдерживаемые специальные файлы; запросите новый комплект исходников."
fi

parse_install_config

: "${SERVER_NAME:?В install.env не заполнен SERVER_NAME}"
: "${TRUSTED_CIDR:?В install.env не заполнен TRUSTED_CIDR}"
: "${ADMIN_USERNAME:?В install.env не заполнен ADMIN_USERNAME}"
: "${ADMIN_EMAIL:=}"
: "${ENABLE_UFW:=true}"
: "${SSH_PORT:=22}"

[[ "$SERVER_NAME" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$ ]] || \
    die "SERVER_NAME должен быть IP-адресом или внутренним DNS-именем без http:// и порта."
validate_ipv4_cidr "$TRUSTED_CIDR" || die "TRUSTED_CIDR должен быть IPv4-сетью, например 10.0.0.0/8."
[[ "$ADMIN_USERNAME" =~ ^[A-Za-z0-9@.+_-]{1,150}$ ]] || die "Недопустимый ADMIN_USERNAME."
if [[ -n "$ADMIN_EMAIL" && ! "$ADMIN_EMAIL" =~ ^[^[:space:]]+@[^[:space:]]+$ ]]; then
    die "Недопустимый ADMIN_EMAIL. Оставьте поле пустым или укажите адрес электронной почты."
fi
[[ "$ENABLE_UFW" == true || "$ENABLE_UFW" == false ]] || die "ENABLE_UFW должен быть true или false."
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] && ((10#$SSH_PORT >= 1 && 10#$SSH_PORT <= 65535)) || \
    die "SSH_PORT должен быть числом от 1 до 65535."

if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    [[ "${ID:-}" == ubuntu && "${VERSION_ID:-}" == 24.04 ]] || \
        die "Этот установщик рассчитан только на чистую Ubuntu 24.04."
else
    die "Не удалось определить версию Ubuntu."
fi

for target in \
    "$APP" \
    /etc/systemd/system/ais_uzmo.service \
    /etc/systemd/system/ais-uzmo-backup.service \
    /etc/systemd/system/ais-uzmo-backup.timer \
    /usr/local/sbin/ais-uzmo-backup \
    /etc/nginx/sites-available/ais_uzmo \
    /etc/nginx/sites-enabled/ais_uzmo \
    /etc/ais_uzmo \
    /var/backups/ais_uzmo \
    /etc/redis/ais_uzmo.conf \
    /etc/redis/redis.conf.before-ais-uzmo; do
    [[ ! -e "$target" && ! -L "$target" ]] || \
        die "Найден существующий путь $target. install.sh предназначен только для чистого сервера и ничего не будет перезаписывать."
done
validate_packaged_nginx_default
if id ais >/dev/null 2>&1 || getent group ais >/dev/null 2>&1; then
    die "Системный пользователь или группа ais уже существуют. Для безопасности установка остановлена без изменений."
fi

readonly RELEASE_VERSION="$(tr -d '[:space:]' <"$SCRIPT_DIR/VERSION")"
[[ "$RELEASE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || \
    die "Некорректная версия в deploy/VERSION."

printf 'Устанавливается АИС УЗМО, версия %s.\n' "$RELEASE_VERSION"
printf 'Скрипт предназначен только для чистого сервера Ubuntu 24.04.\n'

read -r -s -p 'Придумайте пароль первого администратора (не менее 12 символов): ' ADMIN_PASSWORD </dev/tty
printf '\n'
[[ ${#ADMIN_PASSWORD} -ge 12 ]] || die "Пароль администратора должен содержать не менее 12 символов."
read -r -s -p 'Повторите пароль: ' ADMIN_PASSWORD_CONFIRM </dev/tty
printf '\n'
[[ "$ADMIN_PASSWORD" == "$ADMIN_PASSWORD_CONFIRM" ]] || die "Пароли не совпадают."
unset ADMIN_PASSWORD_CONFIRM
INSTALL_SERVICES_TOUCHED=false
cleanup_secrets() {
    local status=$?

    trap - EXIT
    set +e
    unset ADMIN_PASSWORD ADMIN_PASSWORD_CONFIRM DB_PASSWORD REDIS_PASSWORD DJANGO_SECRET_KEY
    if [[ -n "${PG_ERROR_FILE:-}" ]]; then
        rm -f -- "$PG_ERROR_FILE"
    fi
    if ((status != 0)) && [[ "${INSTALL_SERVICES_TOUCHED:-false}" == true ]]; then
        systemctl disable --now ais-uzmo-backup.timer >/dev/null 2>&1
        systemctl disable --now ais_uzmo.service >/dev/null 2>&1
    fi
    exit "$status"
}
trap cleanup_secrets EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

step "Установка системных пакетов"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    ca-certificates curl nginx openssl postgresql postgresql-contrib \
    python3 python3-pip python3-venv redis-server rsync tar ufw
unset DEBIAN_FRONTEND

systemctl enable --now postgresql nginx

if ! pg_role_exists="$(runuser -u postgres -- psql -d postgres -tAc \
    "SELECT 1 FROM pg_roles WHERE rolname='ais_uzmo'")"; then
    die "Не удалось проверить PostgreSQL. Установка остановлена до копирования приложения."
fi
if ! pg_database_exists="$(runuser -u postgres -- psql -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='ais_uzmo'")"; then
    die "Не удалось проверить PostgreSQL. Установка остановлена до копирования приложения."
fi
if [[ "$pg_role_exists" == 1 || "$pg_database_exists" == 1 ]]; then
    die "В PostgreSQL уже есть роль или база ais_uzmo. install.sh работает только с чистой установкой."
fi
for target in /etc/redis/ais_uzmo.conf /etc/redis/redis.conf.before-ais-uzmo; do
    [[ ! -e "$target" && ! -L "$target" ]] || \
        die "Найден существующий файл $target. Настройка Redis не будет перезаписана."
done

step "Копирование приложения"
groupadd --system ais
useradd --system --gid ais --home-dir "$APP" --no-create-home --shell /usr/sbin/nologin ais
install -d -o root -g root -m 0755 "$APP"
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
    "$SOURCE_ROOT/" "$APP/"
chmod 0755 "$APP"
printf '%s\n' "$RELEASE_VERSION" >"$APP/RELEASE"
chown -R root:root "$APP"
chmod 0755 "$APP/deploy/install.sh" "$APP/deploy/check.sh" \
    "$APP/deploy/update.sh" "$APP/deploy/backup.sh" "$APP/deploy/release.sh"

install -d -o ais -g ais -m 2750 "$APP/media" "$APP/logs" "$APP/runtime"
install -d -o root -g root -m 0755 "$APP/staticfiles"

python3 -m venv "$APP/.venv"
install_python_requirements "$SOURCE_ROOT" "$(dirname "$SOURCE_ROOT")"

step "Настройка PostgreSQL и Redis"
DJANGO_SECRET_KEY="$(openssl rand -hex 64)"
DB_PASSWORD="$(openssl rand -hex 32)"
REDIS_PASSWORD="$(openssl rand -hex 32)"

PG_ERROR_FILE="$(mktemp /run/ais-uzmo-postgresql.XXXXXX.err)"
chmod 0600 "$PG_ERROR_FILE"
if ! printf "CREATE ROLE ais_uzmo LOGIN PASSWORD '%s';\n" "$DB_PASSWORD" | \
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d postgres \
        >/dev/null 2>"$PG_ERROR_FILE"; then
    rm -f -- "$PG_ERROR_FILE"
    PG_ERROR_FILE=""
    die "Не удалось создать закрытую роль PostgreSQL. Секрет не показан; проверьте журнал PostgreSQL."
fi
rm -f -- "$PG_ERROR_FILE"
PG_ERROR_FILE=""
runuser -u postgres -- createdb --owner=ais_uzmo ais_uzmo
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d ais_uzmo >/dev/null <<'SQL'
CREATE EXTENSION IF NOT EXISTS pg_trgm;
REVOKE ALL ON DATABASE ais_uzmo FROM PUBLIC;
GRANT CONNECT, TEMPORARY, CREATE ON DATABASE ais_uzmo TO ais_uzmo;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO ais_uzmo;
SQL
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d postgres \
    -c "ALTER SYSTEM SET listen_addresses = 'localhost';" >/dev/null
systemctl restart postgresql

readonly REDIS_MAIN=/etc/redis/redis.conf
readonly REDIS_SECRET_FILE=/etc/redis/ais_uzmo.conf
[[ -f "$REDIS_MAIN" ]] || die "Не найден $REDIS_MAIN."
cp -a "$REDIS_MAIN" "$REDIS_MAIN.before-ais-uzmo"
sed -Ei \
    -e '/^[[:space:]]*#?[[:space:]]*bind[[:space:]]/d' \
    -e '/^[[:space:]]*#?[[:space:]]*protected-mode[[:space:]]/d' \
    -e '\|^[[:space:]]*include[[:space:]]+/etc/redis/ais_uzmo\.conf[[:space:]]*$|d' \
    "$REDIS_MAIN"
printf '\nbind 127.0.0.1 -::1\nprotected-mode yes\ninclude /etc/redis/ais_uzmo.conf\n' \
    >>"$REDIS_MAIN"
(
    umask 077
    printf 'requirepass %s\n' "$REDIS_PASSWORD" >"$REDIS_SECRET_FILE"
)
chown root:redis "$REDIS_SECRET_FILE"
chmod 0640 "$REDIS_SECRET_FILE"
systemctl enable redis-server
systemctl restart redis-server
export REDISCLI_AUTH="$REDIS_PASSWORD"
[[ "$(redis-cli -h 127.0.0.1 ping)" == PONG ]] || die "Redis не отвечает."
unset REDISCLI_AUTH

step "Создание закрытого файла настроек"
(
    umask 077
    cat >"$APP/.env" <<ENV
SECRET_KEY=$DJANGO_SECRET_KEY
DEBUG=False
ALLOWED_HOSTS=$SERVER_NAME,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=http://$SERVER_NAME

DATABASE_URL=postgresql://ais_uzmo:$DB_PASSWORD@127.0.0.1:5432/ais_uzmo
DB_CONN_MAX_AGE=60

REDIS_URL=redis://:$REDIS_PASSWORD@127.0.0.1:6379/1
CACHE_KEY_PREFIX=ais_uzmo
CACHE_DEFAULT_TIMEOUT=300

MEDIA_ROOT=/srv/ais_uzmo/media
LOG_DIR=/srv/ais_uzmo/logs
ADMIN_THRESHOLDS_FILE=/srv/ais_uzmo/runtime/dashboard_thresholds.json

SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
ENV
)
chown root:ais "$APP/.env"
chmod 0640 "$APP/.env"

step "Подготовка базы данных"
cd "$APP"
runuser -u ais -- env DJANGO_SETTINGS_MODULE=config.settings_prod \
    "$APP/.venv/bin/python" manage.py migrate --noinput

export SUPERUSER_USERNAME="$ADMIN_USERNAME"
export SUPERUSER_EMAIL="$ADMIN_EMAIL"
export SUPERUSER_PASSWORD="$ADMIN_PASSWORD"
export DJANGO_SETTINGS_MODULE=config.settings_prod
runuser --whitelist-environment=DJANGO_SETTINGS_MODULE,SUPERUSER_USERNAME,SUPERUSER_EMAIL,SUPERUSER_PASSWORD \
    -u ais -- \
    "$APP/.venv/bin/python" manage.py seed_initial_data
unset SUPERUSER_USERNAME SUPERUSER_EMAIL SUPERUSER_PASSWORD ADMIN_PASSWORD DJANGO_SETTINGS_MODULE

env DJANGO_SETTINGS_MODULE=config.settings_prod \
    "$APP/.venv/bin/python" manage.py collectstatic --noinput --clear
chown -R root:root "$APP/staticfiles"
find "$APP/staticfiles" -type d -exec chmod 0755 {} +
find "$APP/staticfiles" -type f -exec chmod 0644 {} +

step "Установка служб"
install -d -o root -g root -m 0700 /etc/ais_uzmo
(
    umask 077
    printf 'SERVER_NAME=%s\nTRUSTED_CIDR=%s\n' "$SERVER_NAME" "$TRUSTED_CIDR" \
        >/etc/ais_uzmo/deploy.env
)
chown root:root /etc/ais_uzmo/deploy.env
chmod 0600 /etc/ais_uzmo/deploy.env

install -o root -g root -m 0644 "$APP/deploy/ais_uzmo.service" \
    /etc/systemd/system/ais_uzmo.service
install -o root -g root -m 0700 "$APP/deploy/backup.sh" \
    /usr/local/sbin/ais-uzmo-backup
install -o root -g root -m 0644 "$APP/deploy/ais-uzmo-backup.service" \
    /etc/systemd/system/ais-uzmo-backup.service
install -o root -g root -m 0644 "$APP/deploy/ais-uzmo-backup.timer" \
    /etc/systemd/system/ais-uzmo-backup.timer

nginx_tmp="$(mktemp)"
sed -e "s|__SERVER_NAME__|$SERVER_NAME|g" \
    -e "s|__TRUSTED_CIDR__|$TRUSTED_CIDR|g" \
    "$APP/deploy/nginx.conf.template" >"$nginx_tmp"
install -o root -g root -m 0644 "$nginx_tmp" /etc/nginx/sites-available/ais_uzmo
rm -f -- "$nginx_tmp"
ln -sfn /etc/nginx/sites-available/ais_uzmo /etc/nginx/sites-enabled/ais_uzmo
remove_packaged_nginx_default

systemd-analyze verify /etc/systemd/system/ais_uzmo.service
nginx -t
systemctl daemon-reload
INSTALL_SERVICES_TOUCHED=true
systemctl enable --now ais_uzmo.service
systemctl reload nginx

step "Создание первой резервной копии"
install -d -o root -g root -m 0700 /var/backups/ais_uzmo/daily
systemctl start ais-uzmo-backup.service
[[ "$(systemctl show -p Result --value ais-uzmo-backup.service)" == success ]] || \
    die "Не удалось создать первую резервную копию."
systemctl enable --now ais-uzmo-backup.timer

if [[ "$ENABLE_UFW" == true ]]; then
    step "Включение сетевого экрана"
    ufw allow from "$TRUSTED_CIDR" to any port "$SSH_PORT" proto tcp \
        comment 'SSH administration network' >/dev/null
    if [[ -n "${SSH_CONNECTION:-}" ]]; then
        read -r -a ssh_connection_fields <<<"$SSH_CONNECTION"
        ((${#ssh_connection_fields[@]} == 4)) || \
            die "Не удалось безопасно определить текущий SSH-сеанс; сетевой экран не включён."
        ssh_client_ip=${ssh_connection_fields[0]}
        current_ssh_port=${ssh_connection_fields[3]}
        python3 -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' \
            "$ssh_client_ip" >/dev/null 2>&1 || \
            die "Не удалось проверить адрес текущего SSH-сеанса; сетевой экран не включён."
        [[ "$current_ssh_port" =~ ^[0-9]+$ ]] && \
            ((10#$current_ssh_port >= 1 && 10#$current_ssh_port <= 65535)) || \
            die "Не удалось проверить порт текущего SSH-сеанса; сетевой экран не включён."
        ufw allow from "$ssh_client_ip" to any port "$current_ssh_port" proto tcp \
            comment 'Current SSH client' >/dev/null
    fi
    ufw allow from "$TRUSTED_CIDR" to any port 80 proto tcp \
        comment 'AIS UZMO HTTP' >/dev/null
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    ufw --force enable >/dev/null
fi

step "Итоговая проверка"
"$APP/deploy/check.sh"

trap - EXIT HUP INT TERM
unset DB_PASSWORD REDIS_PASSWORD DJANGO_SECRET_KEY
printf '\nУстановка завершена. Откройте: http://%s/\n' "$SERVER_NAME"
printf 'Имя первого администратора: %s\n' "$ADMIN_USERNAME"
