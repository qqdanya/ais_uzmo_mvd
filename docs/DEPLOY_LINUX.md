# Production-развёртывание на Ubuntu

Этот документ описывает полную схему развёртывания АИС УЗМО на сервере
`193.168.46.149`. Он также подходит для восстановления сервера с нуля.

Эталонная конфигурация:

| Компонент | Значение |
|---|---|
| Репозиторий | `https://github.com/qqdanya/ais_uzmo_mvd.git` |
| Каталог приложения | `/srv/ais_uzmo` |
| Системный пользователь | `ais` |
| Django settings | `config.settings_prod` |
| PostgreSQL role | `ais_uzmo`, без `CREATEDB` |
| PostgreSQL database | `ais_uzmo` |
| Redis | только `127.0.0.1:6379`/`::1`, база 1, с паролем |
| Gunicorn | `127.0.0.1:8000` |
| systemd unit | `ais_uzmo.service` |
| Nginx | HTTP на `193.168.46.149:80` до появления домена |
| Загруженные файлы | `/srv/ais_uzmo/media` |
| Статика | `/srv/ais_uzmo/staticfiles` |
| Резервные копии | `/var/backups/ais_uzmo` |

> **Важно:** HTTP по IP — только временный режим. `DEBUG=False` защищает от
> публикации отладочной информации, но HTTP не шифрует пароли, cookie и
> загружаемые данные. До включения HTTPS допускайте к серверу только доверенных
> пользователей/сети и не считайте стенд полностью защищённым production.

## 1. Правила перед началом

1. Не закрывайте текущий рабочий SSH-сеанс до завершения всех smoke-проверок.
2. Все команды администрирования выполняются от `root`. Django и Git запускаются
   от `ais`.
3. Не удаляйте старые SQLite, `.env` и `media` до проверки PostgreSQL-версии.
4. Не меняйте существующий `SECRET_KEY` при переносе. Иначе сохранённые сессии и
   другие подписанные Django-данные станут недействительными.
5. Пароли PostgreSQL и Redis должны быть разными. Для URL удобно использовать
   64-символьные hex-значения, которым не требуется URL-кодирование:

~~~bash
umask 077
openssl rand -hex 32
openssl rand -hex 32
~~~

Сохраните результаты в менеджере паролей. Не публикуйте `.env` и не добавляйте
его в Git.

## 2. Пакеты и пользователь приложения

~~~bash
apt update
apt install -y \
  ca-certificates curl git nginx openssl sqlite3 \
  python3 python3-venv python3-pip build-essential libpq-dev \
  postgresql postgresql-contrib redis-server

systemctl enable --now postgresql
systemctl enable --now redis-server
systemctl enable --now nginx
~~~

Существующий пользователь `ais` сохраняется. Если сервер создаётся с нуля:

~~~bash
id ais >/dev/null 2>&1 || adduser --disabled-password --gecos "" ais
usermod -aG www-data ais
passwd -l ais
~~~

`ais` не должен входить в `sudo`: сервису административные права не нужны.
Для Git и Django root использует `sudo -u ais`.

## 3. Обязательная копия короткого тестового развёртывания

Этот раздел выполняется **до** изменения базы, `.env`, unit-файлов и Nginx.
Короткая конфигурация использовала SQLite и unit
`ais_uzmo-test.service`.

~~~bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PRE=/var/backups/ais_uzmo/pre-production-$STAMP

install -d -m 0700 /var/backups/ais_uzmo
install -d -m 0700 "$PRE"

systemctl stop ais_uzmo-test.service

sqlite3 /srv/ais_uzmo/db.sqlite3 \
  'PRAGMA wal_checkpoint(TRUNCATE); PRAGMA integrity_check;'

cp -a /srv/ais_uzmo/db.sqlite3 "$PRE/"
for file in /srv/ais_uzmo/db.sqlite3-wal /srv/ais_uzmo/db.sqlite3-shm; do
  [ ! -e "$file" ] || cp -a "$file" "$PRE/"
done

cp -a /srv/ais_uzmo/.env "$PRE/app.env"
tar -C /srv/ais_uzmo -czf "$PRE/media.tar.gz" media
runuser -u ais -- git -C /srv/ais_uzmo rev-parse HEAD \
  > "$PRE/git-head"

systemctl cat ais_uzmo-test.service > "$PRE/ais_uzmo-test.service.txt"
nginx -T > "$PRE/nginx-full.txt" 2>&1
if [ -f /etc/systemd/system/ais_uzmo-test.service ]; then
  cp -a /etc/systemd/system/ais_uzmo-test.service \
    "$PRE/ais_uzmo-test.service"
fi
if [ -f /etc/nginx/sites-available/ais_uzmo-test ]; then
  cp -a /etc/nginx/sites-available/ais_uzmo-test \
    "$PRE/nginx-site-ais_uzmo-test"
fi

ln -sfn "$PRE" /var/backups/ais_uzmo/pre-production-current
sha256sum "$PRE/db.sqlite3" "$PRE/media.tar.gz" "$PRE/app.env" \
  > "$PRE/SHA256SUMS"
sha256sum -c "$PRE/SHA256SUMS"
~~~

`PRAGMA integrity_check` должен вывести `ok`, а проверка SHA-256 — `OK`.
Сервис пока оставляем остановленным: так SQLite не изменится между экспортом и
переключением.

## 4. Код и виртуальное окружение

На уже работающем сервере каталог существует. Убедитесь, что в нём нет ручных
изменений:

~~~bash
sudo -u ais git -C /srv/ais_uzmo status --short
sudo -u ais git -C /srv/ais_uzmo remote -v
~~~

`status --short` должен быть пустым, а `origin` должен указывать на
`https://github.com/qqdanya/ais_uzmo_mvd.git`. Не затирайте неизвестные изменения.
Для чистого существующего checkout:

~~~bash
chown -R ais:ais /srv/ais_uzmo
sudo -u ais git -C /srv/ais_uzmo switch main
sudo -u ais git -C /srv/ais_uzmo pull --ff-only
~~~

На новом сервере вместо этого:

~~~bash
install -d -o ais -g ais -m 0750 /srv/ais_uzmo
sudo -u ais git clone \
  https://github.com/qqdanya/ais_uzmo_mvd.git \
  /srv/ais_uzmo
~~~

Установите зависимости:

~~~bash
sudo -u ais python3 -m venv /srv/ais_uzmo/.venv
sudo -u ais /srv/ais_uzmo/.venv/bin/python -m pip install --upgrade pip
sudo -u ais /srv/ais_uzmo/.venv/bin/python -m pip install \
  -r /srv/ais_uzmo/requirements.txt
sudo -u ais /srv/ais_uzmo/.venv/bin/python -m pip check
~~~

## 5. PostgreSQL

### 5.1. Role и database

Подставьте отдельный сгенерированный пароль вместо
`POSTGRES_PASSWORD_HEX`:

~~~bash
sudo -u postgres psql --set ON_ERROR_STOP=1 --set HISTFILE=/dev/null
~~~

~~~sql
CREATE ROLE ais_uzmo
  LOGIN
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  PASSWORD 'POSTGRES_PASSWORD_HEX';

CREATE DATABASE ais_uzmo
  OWNER ais_uzmo
  ENCODING 'UTF8'
  TEMPLATE template0;

REVOKE ALL ON DATABASE ais_uzmo FROM PUBLIC;
\connect ais_uzmo
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO ais_uzmo;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
\quit
~~~

`pg_trgm` создаётся администратором заранее, потому что миграции приложения
строят GIN trigram-индексы.

Если role/database уже существуют, не повторяйте `CREATE` вслепую. Проверьте:

~~~bash
sudo -u postgres psql -c '\du+ ais_uzmo'
sudo -u postgres psql -c '\l+ ais_uzmo'
sudo -u postgres psql -d ais_uzmo -c '\dx pg_trgm'
~~~

У role не должно быть `Superuser`, `Create role` или `Create DB`. Production-role
намеренно не получает `CREATEDB`.

### 5.2. Не публиковать PostgreSQL

PostgreSQL должен слушать только loopback. Узнайте активные параметры:

~~~bash
sudo -u postgres psql -Atc "SHOW listen_addresses"
sudo ss -ltnp | grep ':5432'
~~~

Допустимы только `127.0.0.1:5432` и/или `[::1]:5432`. Если виден
`0.0.0.0` или внешний IP, исправьте `listen_addresses` в файле, который покажет:

~~~bash
sudo -u postgres psql -Atc "SHOW config_file"
~~~

После изменения:

~~~bash
systemctl restart postgresql
pg_isready -h 127.0.0.1 -p 5432
~~~

Порт 5432 в UFW не открывается.

## 6. Redis с аутентификацией

Откройте `/etc/redis/redis.conf` и убедитесь, что активны именно такие параметры:

~~~conf
bind 127.0.0.1 ::1
protected-mode yes
port 6379
requirepass REDIS_PASSWORD_HEX
~~~

Замените `REDIS_PASSWORD_HEX` вторым сгенерированным паролем. Не оставляйте
несколько конфликтующих активных `bind` или `requirepass`.

~~~bash
chown root:redis /etc/redis/redis.conf
chmod 0640 /etc/redis/redis.conf
systemctl restart redis-server
systemctl status redis-server --no-pager
sudo ss -ltnp | grep ':6379'
~~~

Должны быть только loopback-адреса. Проверка без помещения пароля в аргументы
процесса:

~~~bash
read -r -s -p 'Redis password: ' REDISCLI_AUTH
echo
export REDISCLI_AUTH
redis-cli -h 127.0.0.1 ping
unset REDISCLI_AUTH
~~~

Ожидаемый ответ — `PONG`. Порт 6379 в UFW не открывается.

## 7. Production `.env`

Скопируйте старый `SECRET_KEY` **без изменений** из резервной копии
`/var/backups/ais_uzmo/pre-production-current/app.env`. Затем создайте
`/srv/ais_uzmo/.env`:

~~~dotenv
SECRET_KEY=ТОЧНОЕ_СТАРОЕ_ЗНАЧЕНИЕ
DEBUG=False
ALLOWED_HOSTS=193.168.46.149,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=http://193.168.46.149

DATABASE_URL=postgres://ais_uzmo:POSTGRES_PASSWORD_HEX@127.0.0.1:5432/ais_uzmo
DB_CONN_MAX_AGE=60

REDIS_URL=redis://:REDIS_PASSWORD_HEX@127.0.0.1:6379/1
CACHE_KEY_PREFIX=ais_uzmo
CACHE_DEFAULT_TIMEOUT=300

MEDIA_ROOT=/srv/ais_uzmo/media
LOG_DIR=/srv/ais_uzmo/logs

# Временно, пока доступ идёт по HTTP на IP:
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
~~~

Не переносите `SUPERUSER_PASSWORD` в production, если пользователи уже
существуют. Миграция сохранит пользователей и хеши их паролей.

Права:

~~~bash
chown ais:ais /srv/ais_uzmo/.env
chmod 0600 /srv/ais_uzmo/.env
~~~

Проверьте, не выводя секреты:

~~~bash
sudo -u ais test -r /srv/ais_uzmo/.env
grep -E '^(DEBUG|ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|MEDIA_ROOT|LOG_DIR|SECURE_)=' \
  /srv/ais_uzmo/.env
~~~

Временные HTTP-значения `False/0` обязательны: cookie с флагом `Secure`
браузер по HTTP не отправит, и вход будет выглядеть «сломанным». HSTS нельзя
включать до рабочего HTTPS.

## 8. Полная потоковая миграция SQLite → PostgreSQL

Процедура ниже:

- выгружает все зарегистрированные Django-модели в построчный JSONL;
- использует `--all`, поэтому не теряет строки, скрытые кастомными managers;
- сохраняет исходные primary key;
- переносит пользователей, права, audit log и `django_session`;
- сохраняет рабочие сессии при неизменном `SECRET_KEY`;
- отдельно сохраняет `media`, потому что в БД находятся только пути к файлам;
- сверяет количество строк и min/max PK каждой модели;
- отдельно учитывает автоматически созданные M2M-таблицы;
- сравнивает SHA-256 полного набора полей пользователей, не печатая эти поля.

Не используйте для этой миграции обычный JSON-файл, целиком собираемый в памяти,
и не запускайте запись в старую SQLite во время экспорта. JSONL-сериализатор и
десериализатор Django 5.2 обрабатывают объекты построчно. Не добавляйте
`--natural-foreign` или `--natural-primary`: здесь намеренно сохраняются
исходные PK.

### 8.1. Экспорт SQLite в JSONL

~~~bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
MIG=/var/tmp/ais-uzmo-migration-$STAMP
install -d -o ais -g ais -m 0700 "$MIG"

install -o ais -g ais -m 0600 /dev/null "$MIG/db_manifest.py"
cat > "$MIG/db_manifest.py" <<'PY'
import hashlib
import json

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Max, Min


def printable(value):
    return "" if value is None else str(value)


models = sorted(
    apps.get_models(include_auto_created=True),
    key=lambda model: model._meta.label_lower,
)
for model in models:
    if model._meta.proxy or not model._meta.managed:
        continue
    manager = model._base_manager
    if model._meta.auto_created:
        # Auto-created through-table PK не сериализуется dumpdata. Проверяем
        # сами связи: отсортированные значения всех concrete non-PK полей.
        fields = [
            field.attname
            for field in model._meta.concrete_fields
            if not field.primary_key
        ]
        rows = list(
            manager.order_by(*fields).values_list(*fields)
        )
        payload = json.dumps(
            rows,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        print(
            "|".join(
                (
                    "M2M",
                    model._meta.label_lower,
                    str(len(rows)),
                    hashlib.sha256(payload).hexdigest(),
                )
            )
        )
        continue

    pk_name = model._meta.pk.attname
    bounds = manager.aggregate(min_pk=Min(pk_name), max_pk=Max(pk_name))
    print(
        "|".join(
            (
                "MODEL",
                model._meta.label_lower,
                str(manager.count()),
                printable(bounds["min_pk"]),
                printable(bounds["max_pk"]),
            )
        )
    )

User = get_user_model()
user_fields = [field.attname for field in User._meta.concrete_fields]
user_rows = list(
    User._base_manager.order_by(User._meta.pk.attname).values(*user_fields)
)
payload = json.dumps(
    user_rows,
    sort_keys=True,
    separators=(",", ":"),
    default=str,
).encode("utf-8")
print("USERS_SHA256|" + hashlib.sha256(payload).hexdigest())
PY
chown ais:ais "$MIG/db_manifest.py"
chmod 0600 "$MIG/db_manifest.py"

sudo -u ais env \
  DATABASE_URL=sqlite:////srv/ais_uzmo/db.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py shell \
  < "$MIG/db_manifest.py" > "$MIG/sqlite-manifest.txt"

sudo -u ais env \
  DATABASE_URL=sqlite:////srv/ais_uzmo/db.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py dumpdata \
  --all --format=jsonl --output="$MIG/sqlite-full.jsonl" --verbosity 1

test -s "$MIG/sqlite-full.jsonl"
wc -l "$MIG/sqlite-full.jsonl"
sha256sum "$MIG/sqlite-full.jsonl" > "$MIG/sqlite-full.jsonl.sha256"
sha256sum -c "$MIG/sqlite-full.jsonl.sha256"
~~~

Одна строка JSONL соответствует одному сериализованному объекту. В файл не
попадает содержимое фотографий — они уже сохранены в `media.tar.gz`.

### 8.2. Создание схемы PostgreSQL

~~~bash
install -d -o ais -g ais -m 0750 /srv/ais_uzmo/logs

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py migrate \
  --noinput
~~~

`migrate` сначала создаёт служебные content types и permissions. Чтобы затем
загрузить **точные** строки и PK из SQLite, очистите все таблицы, кроме
`django_migrations`. Сама схема, индексы и история применённых миграций останутся:

~~~bash
sudo -u postgres psql --dbname=ais_uzmo --set ON_ERROR_STOP=1 <<'SQL'
DO $block$
DECLARE
    table_list text;
BEGIN
    SELECT string_agg(format('%I.%I', schemaname, tablename), ', ')
      INTO table_list
      FROM pg_tables
     WHERE schemaname = 'public'
       AND tablename <> 'django_migrations';

    IF table_list IS NOT NULL THEN
        EXECUTE 'TRUNCATE TABLE ' || table_list || ' RESTART IDENTITY CASCADE';
    END IF;
END
$block$;
SQL
~~~

### 8.3. Загрузка, sequences и сверка

~~~bash
sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py loaddata \
  "$MIG/sqlite-full.jsonl" --verbosity 1

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py sqlsequencereset \
  accounts directory requests_app audit auth admin contenttypes sessions \
  > "$MIG/reset-sequences.sql"

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py dbshell \
  < "$MIG/reset-sequences.sql"

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py shell \
  < "$MIG/db_manifest.py" > "$MIG/postgres-manifest.txt"

diff -u "$MIG/sqlite-manifest.txt" "$MIG/postgres-manifest.txt"

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py shell \
  -c "from django.db import connection; connection.check_constraints(); print('constraints: ok')"
~~~

Строки `MODEL` содержат label, count, min PK и max PK. Скрытый surrogate PK
автоматической M2M-таблицы не входит в `dumpdata`, поэтому строка `M2M`
сравнивает count и SHA-256 отсортированных наборов всех concrete non-PK полей,
то есть сами связи. `USERS_SHA256` — контрольный хеш всех concrete-полей
пользователей, включая сохранённые password hashes. `diff` не должен вывести
различий. Затем выполните проверки целостности:

~~~bash
sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py check

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py makemigrations \
  --check --dry-run

sudo -u postgres psql -d ais_uzmo -c \
  "SELECT COUNT(*) AS sessions FROM django_session;"
~~~

Сохраните экспорт рядом с pre-production backup:

~~~bash
PRE=$(readlink -f /var/backups/ais_uzmo/pre-production-current)
mv "$MIG" "$PRE/migration"
~~~

Не удаляйте этот backup после переключения.

## 9. Каталоги, static и media

~~~bash
install -d -o ais -g www-data -m 2750 /srv/ais_uzmo/media
install -d -o ais -g ais -m 0750 /srv/ais_uzmo/logs

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py collectstatic \
  --noinput

chown ais:www-data /srv/ais_uzmo
chmod 2750 /srv/ais_uzmo

chown -R ais:www-data /srv/ais_uzmo/staticfiles /srv/ais_uzmo/media
find /srv/ais_uzmo/staticfiles /srv/ais_uzmo/media \
  -type d -exec chmod 2750 {} +
find /srv/ais_uzmo/staticfiles /srv/ais_uzmo/media \
  -type f -exec chmod 0640 {} +

chown -R ais:ais /srv/ais_uzmo/logs
chmod 0750 /srv/ais_uzmo/logs
chown ais:ais /srv/ais_uzmo/.env
chmod 0600 /srv/ais_uzmo/.env

sudo -u ais touch /srv/ais_uzmo/media/.write-test
sudo -u ais rm /srv/ais_uzmo/media/.write-test
~~~

Не заменяйте `/media/` в Nginx публичным `alias`: фотографии выдаются Django
через защищённые маршруты с проверкой прав пользователя.

## 10. Hardened systemd unit

Создайте `/etc/systemd/system/ais_uzmo.service`:

~~~ini
[Unit]
Description=AIS UZMO production application
Wants=network-online.target
Requires=postgresql.service redis-server.service
After=network-online.target postgresql.service redis-server.service

[Service]
Type=simple
User=ais
Group=www-data
WorkingDirectory=/srv/ais_uzmo
Environment="DJANGO_SETTINGS_MODULE=config.settings_prod"
Environment="PYTHONUNBUFFERED=1"
Environment="PYTHONDONTWRITEBYTECODE=1"
ExecStart=/srv/ais_uzmo/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 --access-logfile - --error-logfile - --capture-output --no-control-socket
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure
RestartSec=5
TimeoutStartSec=60
TimeoutStopSec=45
KillSignal=SIGTERM
UMask=0027

NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=full
ProtectHome=true
ProtectHostname=true
ProtectClock=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictRealtime=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
~~~

`--no-control-socket` обязателен вместе с `ProtectHome=true`: Gunicorn 26 не
пытается создать control socket в недоступном `/home/ais/.gunicorn`. Параметры
`max-requests` и jitter периодически обновляют workers и не дают одному worker
бесконечно накапливать память.

Проверка unit:

~~~bash
systemd-analyze verify /etc/systemd/system/ais_uzmo.service
systemctl daemon-reload
systemctl enable ais_uzmo.service
~~~

Пока не запускайте новый unit, если старый `ais_uzmo-test.service` ещё занимает
`127.0.0.1:8000`.

## 11. Nginx

Создайте `/etc/nginx/sites-available/ais_uzmo`:

~~~nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name 193.168.46.149 _;
    server_tokens off;

    client_max_body_size 250M;
    client_body_timeout 180s;
    send_timeout 180s;

    location ^~ /static/ {
        alias /srv/ais_uzmo/staticfiles/;
        access_log off;
        expires 30d;
    }

    # Media не публикуется напрямую. Просмотр/скачивание идёт через
    # защищённые Django endpoints, которые попадают в location /.
    location ^~ /media/ {
        return 404;
    }

    location ~ /\.(?!well-known/) {
        return 404;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Не доверяем присланной клиентом цепочке X-Forwarded-For:
        # Nginx — единственный доверенный reverse proxy.
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";

        proxy_connect_timeout 10s;
        proxy_read_timeout 180s;
        proxy_send_timeout 180s;
        proxy_redirect off;
    }
}
~~~

Лимит `250M` относится ко всему HTTP-запросу. Само приложение дополнительно
ограничивает одну фотографию 8 МБ и разрешает JPG/JPEG, PNG и WEBP.

Активируйте конфигурацию:

~~~bash
ln -sfn /etc/nginx/sites-available/ais_uzmo \
  /etc/nginx/sites-enabled/ais_uzmo
rm -f /etc/nginx/sites-enabled/default
rm -f /etc/nginx/sites-enabled/ais_uzmo-test
nginx -t
systemctl reload nginx
~~~

Если upload возвращает `413 Request Entity Too Large`, сначала проверьте
активную конфигурацию:

~~~bash
nginx -T 2>/dev/null | grep -n client_max_body_size
~~~

`404` на прямом URL `/media/...`, напротив, является ожидаемой защитой и не
означает ошибку загрузки.

## 12. Переключение на production

~~~bash
systemctl disable --now ais_uzmo-test.service
systemctl start ais_uzmo.service
systemctl status ais_uzmo.service --no-pager
journalctl -u ais_uzmo.service -n 100 --no-pager
~~~

Когда новый сервис прошёл все проверки, старый unit можно убрать; его копия уже
находится в pre-production backup:

~~~bash
rm -f /etc/systemd/system/ais_uzmo-test.service
systemctl daemon-reload
systemctl reset-failed
~~~

Не удаляйте старый SQLite-файл и PostgreSQL backup во время первичной проверки.

## 13. Firewall

Сначала разрешите реальный SSH-порт, иначе можно потерять доступ:

~~~bash
ufw allow 22/tcp
ufw allow 80/tcp
ufw status verbose
~~~

Если UFW ещё не включён:

~~~bash
ufw enable
~~~

При нестандартном SSH-порте вместо 22 разрешите именно его **до** `ufw enable`.
Не открывайте наружу 5432, 6379 или 8000. После появления HTTPS добавится
`ufw allow 443/tcp`.

## 14. Smoke-проверки

### 14.1. Сервисы и порты

~~~bash
systemctl is-active ais_uzmo postgresql redis-server nginx
ss -ltnp | grep -E ':(80|8000|5432|6379)\b'
~~~

Ожидается:

- 80 — Nginx на внешних адресах;
- 8000 — Gunicorn только на `127.0.0.1`;
- 5432 — PostgreSQL только loopback;
- 6379 — Redis только loopback.

### 14.2. Django, PostgreSQL и Redis

~~~bash
sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py shell \
  -c "from django.conf import settings; from django.db import connection; connection.ensure_connection(); print('DEBUG=', settings.DEBUG, 'DB=', connection.vendor)"

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py shell \
  -c "from django.core.cache import cache; cache.set('deploy-smoke', 'ok', 30); print(cache.get('deploy-smoke'))"
~~~

Ожидается `DEBUG=False DB=postgresql` и `ok`.

`check --deploy` в текущем временном HTTP-режиме закономерно предупредит об
отключённых HTTPS/HSTS-флагах. Не игнорируйте остальные ошибки:

~~~bash
sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py check --deploy
~~~

### 14.3. HTTP

~~~bash
curl -I -H 'Host: 193.168.46.149' \
  http://127.0.0.1:8000/accounts/login/

curl -I -H 'Host: 193.168.46.149' \
  http://127.0.0.1/accounts/login/

curl -I http://193.168.46.149/accounts/login/
curl -I http://193.168.46.149/media/not-public.jpg
~~~

Login должен отвечать без 400/500, а последний запрос — 404.

В браузере обязательно проверьте:

1. вход существующего пользователя;
2. роли администратора, оператора и наблюдателя;
3. создание и изменение записи;
4. загрузку JPG/PNG/WEBP, создание миниатюры и защищённый просмотр;
5. массовую загрузку нескольких фотографий;
6. экспорт;
7. журнал действий;
8. повторный вход после перезапуска `ais_uzmo.service`.

Логи:

~~~bash
journalctl -u ais_uzmo.service -f
tail -f /srv/ais_uzmo/logs/app.log
tail -f /var/log/nginx/error.log
~~~

## 15. Ежедневный backup PostgreSQL + media + `.env`

Backup содержит персональные данные и `SECRET_KEY`, поэтому каталог доступен
только root. Скрипт ниже ненадолго останавливает приложение, чтобы снимок БД и
`media` был согласованным. Nginx в эти секунды может вернуть 502; таймер
запускается ночью.

Создайте `/usr/local/sbin/ais-uzmo-backup`:

~~~bash
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

APP=/srv/ais_uzmo
BACKUP_ROOT=/var/backups/ais_uzmo/daily
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST=$BACKUP_ROOT/$STAMP

exec 9>/run/lock/ais-uzmo-backup.lock
flock -n 9 || exit 0

install -d -m 0700 "$BACKUP_ROOT"
install -d -m 0700 "$DEST"

service_was_active=0
restart_application() {
    if [ "$service_was_active" -eq 1 ]; then
        systemctl start ais_uzmo.service
    fi
}
trap restart_application EXIT

if systemctl is-active --quiet ais_uzmo.service; then
    service_was_active=1
    systemctl stop ais_uzmo.service
fi

runuser -u postgres -- \
    pg_dump --format=custom --no-owner --no-acl ais_uzmo \
    > "$DEST/database.dump"

tar -C "$APP" -czf "$DEST/media.tar.gz" media
cp --preserve=mode,timestamps "$APP/.env" "$DEST/app.env"
chmod 0600 "$DEST/app.env"

runuser -u ais -- git -C "$APP" rev-parse HEAD > "$DEST/git-head"
sha256sum "$DEST/database.dump" "$DEST/media.tar.gz" \
    "$DEST/app.env" > "$DEST/SHA256SUMS"

trap - EXIT
restart_application
touch "$DEST/COMPLETE"

# Храним 14 суток. Удаляются только каталоги первого уровня внутри
# фиксированного BACKUP_ROOT.
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +14 \
    -exec rm -rf -- {} +
~~~

Права:

~~~bash
chown root:root /usr/local/sbin/ais-uzmo-backup
chmod 0700 /usr/local/sbin/ais-uzmo-backup
install -d -o root -g root -m 0700 /var/backups/ais_uzmo/daily
~~~

Создайте `/etc/systemd/system/ais-uzmo-backup.service`:

~~~ini
[Unit]
Description=Consistent AIS UZMO PostgreSQL and media backup
Requires=postgresql.service
After=postgresql.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/ais-uzmo-backup
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
~~~

Создайте `/etc/systemd/system/ais-uzmo-backup.timer`:

~~~ini
[Unit]
Description=Daily AIS UZMO backup

[Timer]
OnCalendar=*-*-* 03:30:00
RandomizedDelaySec=10m
Persistent=true
Unit=ais-uzmo-backup.service

[Install]
WantedBy=timers.target
~~~

Включите и сразу проверьте первый backup:

~~~bash
systemctl daemon-reload
systemctl enable --now ais-uzmo-backup.timer
systemctl start ais-uzmo-backup.service
systemctl status ais-uzmo-backup.service --no-pager
systemctl is-active ais_uzmo.service
systemctl list-timers ais-uzmo-backup.timer

LATEST=$(find /var/backups/ais_uzmo/daily -mindepth 1 -maxdepth 1 \
  -type d -name '*T*Z' | sort | tail -n 1)
test -f "$LATEST/COMPLETE"
cd "$LATEST"
sha256sum -c SHA256SUMS
pg_restore --list database.dump >/dev/null
tar -tzf media.tar.gz >/dev/null
~~~

Копию нужно регулярно переносить на другой сервер/носитель. Backup на том же
диске не защищает от потери самого сервера. Периодически выполняйте тестовое
восстановление.

## 16. Восстановление из ежедневного backup

Ниже `BACKUP_DIR` — каталог, содержащий `COMPLETE`:

~~~bash
BACKUP_DIR=/var/backups/ais_uzmo/daily/YYYYMMDDTHHMMSSZ
test -f "$BACKUP_DIR/COMPLETE"
cd "$BACKUP_DIR"
sha256sum -c SHA256SUMS

systemctl stop ais_uzmo.service

sudo -u postgres psql -d postgres --set ON_ERROR_STOP=1 -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='ais_uzmo' AND pid <> pg_backend_pid();"
sudo -u postgres dropdb ais_uzmo
sudo -u postgres createdb --owner=ais_uzmo --encoding=UTF8 \
  --template=template0 ais_uzmo
sudo -u postgres psql -d ais_uzmo -c \
  'CREATE EXTENSION IF NOT EXISTS pg_trgm;'
sudo -u postgres pg_restore --exit-on-error --no-owner --no-acl \
  --dbname=ais_uzmo < "$BACKUP_DIR/database.dump"

RESTORE_STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mv /srv/ais_uzmo/media \
  "/srv/ais_uzmo/media.before-restore-$RESTORE_STAMP"
tar -C /srv/ais_uzmo -xzf "$BACKUP_DIR/media.tar.gz"

chown -R ais:www-data /srv/ais_uzmo/media
find /srv/ais_uzmo/media -type d -exec chmod 2750 {} +
find /srv/ais_uzmo/media -type f -exec chmod 0640 {} +

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py migrate --noinput

systemctl start ais_uzmo.service
systemctl status ais_uzmo.service --no-pager
~~~

Восстанавливайте `app.env` только если одновременно восстанавливается весь
сервер или потерян рабочий `.env`. В нём находятся пароли и `SECRET_KEY`.

## 17. Обновление приложения

Production-сервер не является рабочей копией разработчика: в Git checkout не
должно быть ручных правок. Перед каждым обновлением:

~~~bash
sudo -u ais git -C /srv/ais_uzmo status --short
~~~

Если вывод не пустой, остановитесь и выясните происхождение файлов.

Обычное обновление:

~~~bash
# 1. Проверенный backup; команда завершится только после его создания.
systemctl start ais-uzmo-backup.service
systemctl is-active ais_uzmo.service
systemctl stop ais_uzmo.service

# 2. Только fast-forward, без случайного merge-коммита на сервере.
sudo -u ais git -C /srv/ais_uzmo fetch origin
sudo -u ais git -C /srv/ais_uzmo pull --ff-only origin main

# 3. Зависимости и проверки, не требующие тестовой БД.
sudo -u ais /srv/ais_uzmo/.venv/bin/python -m pip install \
  -r /srv/ais_uzmo/requirements.txt
sudo -u ais /srv/ais_uzmo/.venv/bin/python -m pip check

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py check
sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py makemigrations \
  --check --dry-run
sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py migrate --noinput
sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py collectstatic \
  --noinput
chown -R ais:www-data /srv/ais_uzmo/staticfiles
find /srv/ais_uzmo/staticfiles -type d -exec chmod 2750 {} +
find /srv/ais_uzmo/staticfiles -type f -exec chmod 0640 {} +

# 4. Перезапуск и smoke-check.
systemctl start ais_uzmo.service
nginx -t
systemctl reload nginx
systemctl status ais_uzmo.service --no-pager
curl -I -H 'Host: 193.168.46.149' \
  http://127.0.0.1/accounts/login/
~~~

Не выдавайте role `ais_uzmo` право `CREATEDB` ради `manage.py test`.
Полный набор тестов запускается в CI или локальном изолированном окружении с
отдельной тестовой role/database. Production-role остаётся
`NOSUPERUSER NOCREATEDB NOCREATEROLE`.

## 18. Аварийный rollback к старой SQLite-конфигурации

Rollback нужен, если новый сервис не проходит smoke-проверки. Он возвращает
состояние на момент pre-production backup; новые записи, созданные после
переключения, в SQLite отсутствуют. Перед rollback сохраните текущие PostgreSQL
и `media` отдельной копией.

~~~bash
PRE=$(readlink -f /var/backups/ais_uzmo/pre-production-current)
ROLLBACK_STAMP=$(date -u +%Y%m%dT%H%M%SZ)

systemctl stop ais_uzmo.service

install -d -m 0700 \
  "/var/backups/ais_uzmo/failed-production-$ROLLBACK_STAMP"
sudo -u postgres pg_dump --format=custom --no-owner --no-acl ais_uzmo \
  > "/var/backups/ais_uzmo/failed-production-$ROLLBACK_STAMP/database.dump"
tar -C /srv/ais_uzmo -czf \
  "/var/backups/ais_uzmo/failed-production-$ROLLBACK_STAMP/media.tar.gz" \
  media

cp -a "$PRE/app.env" /srv/ais_uzmo/.env
cp -a "$PRE/db.sqlite3" /srv/ais_uzmo/db.sqlite3
chown ais:www-data /srv/ais_uzmo/db.sqlite3
chmod 0640 /srv/ais_uzmo/db.sqlite3
chown ais:ais /srv/ais_uzmo/.env
chmod 0600 /srv/ais_uzmo/.env

mv /srv/ais_uzmo/media \
  "/srv/ais_uzmo/media.failed-production-$ROLLBACK_STAMP"
tar -C /srv/ais_uzmo -xzf "$PRE/media.tar.gz"
chown -R ais:www-data /srv/ais_uzmo/media

OLD_HEAD=$(cat "$PRE/git-head")
sudo -u ais git -C /srv/ais_uzmo switch --detach "$OLD_HEAD"
sudo -u ais /srv/ais_uzmo/.venv/bin/python -m pip install \
  -r /srv/ais_uzmo/requirements.txt
sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py collectstatic \
  --noinput
chown -R ais:www-data /srv/ais_uzmo/staticfiles

cp -a "$PRE/ais_uzmo-test.service" \
  /etc/systemd/system/ais_uzmo-test.service
systemctl daemon-reload
systemctl disable ais_uzmo.service
systemctl enable --now ais_uzmo-test.service
~~~

Перед rollback проверьте наличие
`/var/backups/ais_uzmo/pre-production-current/ais_uzmo-test.service`. Файл
`ais_uzmo-test.service.txt` от `systemctl cat` оставлен только для аудита и не
используется как unit, потому что содержит служебные заголовки.

## 19. Переход на домен и HTTPS

После появления домена:

1. направьте DNS A-запись на `193.168.46.149`;
2. замените `server_name` на домен;
3. добавьте `ufw allow 443/tcp`;
4. установите Certbot и получите сертификат;
5. только после успешной проверки HTTPS включите secure cookies и redirect.

~~~bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d example.ru
~~~

Production `.env` после перехода:

~~~dotenv
ALLOWED_HOSTS=example.ru
CSRF_TRUSTED_ORIGINS=https://example.ru
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# Сначала небольшой срок; после проверки можно увеличить до 31536000.
SECURE_HSTS_SECONDS=3600
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
~~~

~~~bash
systemctl restart ais_uzmo.service
curl -I https://example.ru/accounts/login/
~~~

Не включайте `SECURE_HSTS_INCLUDE_SUBDOMAINS` и `SECURE_HSTS_PRELOAD` без
осознанного решения для всего домена и его поддоменов. После стабильной работы
HTTPS `SECURE_HSTS_SECONDS` можно увеличить до `31536000`.

## 20. Удаление временного SSH-ключа Codex

Удаляйте временный ключ только после успешного развёртывания, проверки
автоматического backup и подтверждения, что у администратора остаётся другой
рабочий способ входа.

Текущий временный ключ помечен комментарием
`codex-ais-uzmo-production-2026-07-14`:

~~~bash
cp -a /root/.ssh/authorized_keys \
  /root/.ssh/authorized_keys.before-codex-removal
sed -i '/codex-ais-uzmo-production-2026-07-14/d' \
  /root/.ssh/authorized_keys
chown root:root /root/.ssh/authorized_keys
chmod 0600 /root/.ssh/authorized_keys
~~~

Откройте **новый** SSH-сеанс своим постоянным ключом и только после успешного
входа закройте старый. В дальнейшем рекомендуется запретить парольный вход root
и оставить `PermitRootLogin prohibit-password`, но это делается лишь после
создания и проверки постоянного административного пользователя с `sudo`.

## Краткий operational checklist

- `DEBUG=False`;
- `SECRET_KEY` сохранён и не публикуется;
- приложение работает от `ais`, не от root;
- `ais_uzmo.service` активен, `ais_uzmo-test.service` отключён;
- PostgreSQL и Redis доступны только с loopback;
- Redis требует пароль;
- production PostgreSQL role не имеет `CREATEDB`;
- Gunicorn слушает только `127.0.0.1:8000`;
- Nginx публикует `/static/`, но возвращает 404 для прямого `/media/`;
- `X-Forwarded-For` перезаписывается адресом клиента, а не дополняется
  недоверенной цепочкой;
- лимит запроса Nginx — 250 МБ;
- ежедневный backup имеет маркер `COMPLETE` и проходит SHA-256-проверку;
- копия backup хранится вне этого сервера;
- HTTP по IP считается временным, переход на HTTPS остаётся обязательным;
- временный SSH-ключ удалён после завершения работ.
