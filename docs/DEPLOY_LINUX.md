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

> **Важно:** HTTP по IP — только временный режим. Адрес `193.168.46.149`
> публичный: если открыть порт 80 для всех, форма входа, session cookie и
> загружаемые данные пойдут через Интернет без шифрования. `DEBUG=False` от
> перехвата трафика не защищает. До включения HTTPS безопасный вариант —
> разрешить порт 80 только от доверенного IP/CIDR, VPN или внутренней сети.
> Глобальный `ufw allow 80/tcp` ниже выделен как отдельный, явно небезопасный
> режим и не должен использоваться для конфиденциальных production-данных.

## 0. Фактическое состояние сервера после миграции 14.07.2026

Развёртывание на `193.168.46.149` выполнено по этой схеме и проверено. Это
текущее состояние, от которого следует отталкиваться при обновлении или
диагностике:

- приложение доступно по `http://193.168.46.149/`;
- `ais_uzmo.service`, PostgreSQL 16, Redis, Nginx и
  `ais-uzmo-backup.timer` активны; старый `ais_uzmo-test.service` сохранён для
  аварийного возврата, но отключён и не запущен;
- в финальный JSONL перенесено и побайтово/построчно сверено `849069` Django-
  объектов; smoke-проверка после открытия сайта увидела `849071` объектов,
  включая новые служебные записи;
- проверены 71 Django-миграция, 24 PostgreSQL trigram GIN-индекса, constraints,
  sequences, Redis cache, все 5 оригиналов фотографий и 10 миниатюр;
- финальный recovery-набор находится в
  `/var/backups/ais_uzmo/pre-production-final-20260714-044047`, первый
  ежедневный backup — в
  `/var/backups/ais_uzmo/daily/20260714T045726.940520238Z`; оба имеют маркер
  завершения, проходят SHA-256 и полностью читаются `pg_restore`/`tar`;
- снаружи слушают только 22 и 80; PostgreSQL, Redis и Gunicorn привязаны к
  loopback; UFW запрещает остальные входящие соединения;
- на момент развёртывания UFW разрешает порт 80 всем адресам. Это временный
  небезопасный режим: до HTTPS не вводите через публичную сеть реальные пароли
  и персональные данные. Ограничьте порт доверенным CIDR/VPN по разделу 13 либо
  как можно скорее выполните раздел 19.

`manage.py check --deploy` в этом HTTP-режиме выдаёт только ожидаемые
`security.W004`, `W008`, `W012` и `W016`. Они устраняются не подавлением, а
переходом на HTTPS.

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
`ais_uzmo-test.service`. Сначала сохраняется старая конфигурация, затем Nginx
переключается на явный `503`; только после проверки maintenance-страницы
останавливается SQLite-приложение.

~~~bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PRE=/var/backups/ais_uzmo/pre-production-$STAMP

install -d -m 0700 /var/backups/ais_uzmo
install -d -m 0700 "$PRE"

systemctl cat ais_uzmo-test.service > "$PRE/ais_uzmo-test.service.txt"
nginx -T > "$PRE/nginx-full.txt" 2>&1
cp -a /etc/systemd/system/ais_uzmo-test.service \
  "$PRE/ais_uzmo-test.service"
cp -a /etc/nginx/sites-available/ais_uzmo-test \
  "$PRE/nginx-site-ais_uzmo-test"

cat > /etc/nginx/sites-available/ais_uzmo-maintenance <<'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name 193.168.46.149 _;
    server_tokens off;
    default_type text/plain;

    location / {
        add_header Retry-After 900 always;
        return 503 "AIS UZMO maintenance in progress. Please try again later.\n";
    }
}
NGINX

ln -sfn /etc/nginx/sites-available/ais_uzmo-maintenance \
  /etc/nginx/sites-enabled/ais_uzmo-maintenance
rm -f /etc/nginx/sites-enabled/ais_uzmo \
  /etc/nginx/sites-enabled/ais_uzmo-test \
  /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
maintenance_ready=false
for attempt in $(seq 1 30); do
  maintenance_code=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' \
    -H 'Host: 193.168.46.149' \
    http://127.0.0.1/accounts/login/ 2>/dev/null || true)
  if [ "$maintenance_code" = "503" ]; then
    maintenance_ready=true
    break
  fi
  sleep 1
done
test "$maintenance_ready" = "true"

systemctl stop ais_uzmo-test.service

sqlite3 /srv/ais_uzmo/db.sqlite3 'PRAGMA wal_checkpoint(TRUNCATE);' \
  > "$PRE/sqlite-wal-checkpoint.txt"
test "$(cat "$PRE/sqlite-wal-checkpoint.txt")" = '0|0|0'
test ! -s /srv/ais_uzmo/db.sqlite3-wal
test "$(sqlite3 /srv/ais_uzmo/db.sqlite3 'PRAGMA integrity_check;')" = "ok"
test -z "$(sqlite3 /srv/ais_uzmo/db.sqlite3 'PRAGMA foreign_key_check;')"
sqlite3 /srv/ais_uzmo/db.sqlite3 ".backup '$PRE/db.sqlite3'"
test "$(sqlite3 "$PRE/db.sqlite3" 'PRAGMA integrity_check;')" = "ok"
test -z "$(sqlite3 "$PRE/db.sqlite3" 'PRAGMA foreign_key_check;')"

cp -a /srv/ais_uzmo/.env "$PRE/app.env"
tar -C /srv/ais_uzmo -czf "$PRE/media.tar.gz" media
runuser -u ais -- git -C /srv/ais_uzmo rev-parse HEAD \
  > "$PRE/git-head"

ln -sfn "$PRE" /var/backups/ais_uzmo/pre-production-current
sha256sum "$PRE/db.sqlite3" "$PRE/media.tar.gz" "$PRE/app.env" \
  > "$PRE/SHA256SUMS"
sha256sum -c "$PRE/SHA256SUMS"
~~~

Все `test` и SHA-256-проверка должны завершиться успешно. Nginx оставляем на
maintenance `503`, а сервис — остановленным: так SQLite не изменится между
экспортом и переключением, и клиенты не увидят случайный `502`.

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

Запустите интерактивный `psql` без history-файла. Сам пароль не помещайте в
командную строку или SQL-текст: `\password` запросит его дважды без эха и не
оставит открытым текстом в shell/psql history:

~~~bash
sudo -u postgres psql -X --set ON_ERROR_STOP=1 --set HISTFILE=/dev/null
~~~

~~~sql
CREATE ROLE ais_uzmo
  LOGIN
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE;

\password ais_uzmo

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
grep -E '^(DEBUG|ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|MEDIA_ROOT|LOG_DIR|SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE|SECURE_[A-Z_]+)=' \
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
- сверяет точное число строк, min/max PK и SHA-256 всех concrete-полей каждой
  обычной модели;
- отдельно учитывает автоматически созданные M2M-таблицы;
- не печатает значения полей, включая password hashes и персональные данные;
- до очистки сравнивает точный упорядоченный набор применённых миграций
  `(app, name)` в SQLite и PostgreSQL.

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
import datetime
import json

from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder


class ExactDjangoJSONEncoder(DjangoJSONEncoder):
    """Preserve all six microsecond digits during the database transfer."""

    def default(self, value):
        if isinstance(value, datetime.datetime):
            result = value.isoformat(timespec="microseconds")
            if result.endswith("+00:00"):
                result = result.removesuffix("+00:00") + "Z"
            return result
        if isinstance(value, datetime.time):
            if value.utcoffset() is not None:
                raise ValueError("JSON cannot represent timezone-aware times")
            return value.isoformat(timespec="microseconds")
        return super().default(value)


models = sorted(
    (
        model
        for model in apps.get_models(include_auto_created=True)
        if model._meta.managed and not model._meta.proxy
    ),
    key=lambda model: (model._meta.db_table, model._meta.label_lower),
)
for model in models:
    manager = model._base_manager
    if model._meta.auto_created:
        # Auto-created through-table PK не сериализуется dumpdata. Проверяем
        # сами связи: отсортированные значения всех concrete non-PK полей.
        fields = [
            field.attname
            for field in model._meta.concrete_fields
            if not field.primary_key
        ]
        digest = hashlib.sha256()
        count = 0
        queryset = manager.order_by(*fields).values_list(*fields)
        for values in queryset.iterator(chunk_size=5000):
            payload = json.dumps(
                values,
                cls=ExactDjangoJSONEncoder,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            digest.update(payload)
            digest.update(b"\n")
            count += 1
        print(
            "|".join(
                (
                    "M2M",
                    model._meta.label_lower,
                    str(count),
                    digest.hexdigest(),
                )
            )
        )
        continue

    pk_name = model._meta.pk.attname
    fields = [field.attname for field in model._meta.concrete_fields]
    primary_key_index = fields.index(pk_name)
    digest = hashlib.sha256()
    count = 0
    minimum = None
    maximum = None
    queryset = manager.order_by(pk_name).values_list(*fields)
    for values in queryset.iterator(chunk_size=5000):
        primary_key = values[primary_key_index]
        minimum = primary_key if minimum is None else min(minimum, primary_key)
        maximum = primary_key if maximum is None else max(maximum, primary_key)
        payload = json.dumps(
            values,
            cls=ExactDjangoJSONEncoder,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(payload)
        digest.update(b"\n")
        count += 1
    print(
        "|".join(
            (
                "MODEL",
                model._meta.label_lower,
                str(count),
                "" if minimum is None else str(minimum),
                "" if maximum is None else str(maximum),
                digest.hexdigest(),
            )
        )
    )
PY
chown ais:ais "$MIG/db_manifest.py"
chmod 0600 "$MIG/db_manifest.py"

sudo -u ais env \
  DATABASE_URL=sqlite:////srv/ais_uzmo/db.sqlite3 \
  DEBUG=False \
  DJANGO_SETTINGS_MODULE=config.settings \
  MANIFEST_SCRIPT="$MIG/db_manifest.py" \
  /srv/ais_uzmo/.venv/bin/python -c \
  'import os; import django; django.setup(); exec(open(os.environ["MANIFEST_SCRIPT"], encoding="utf-8").read())' \
  > "$MIG/sqlite-manifest.txt"

sudo -u ais env \
  DATABASE_URL=sqlite:////srv/ais_uzmo/db.sqlite3 \
  DEBUG=False \
  DJANGO_SETTINGS_MODULE=config.settings \
  FIXTURE_OUTPUT="$MIG/sqlite-full.jsonl" \
  /srv/ais_uzmo/.venv/bin/python - <<'PY'
import datetime
import os

import django
from django.core.management import call_command
from django.core.serializers.json import DjangoJSONEncoder


class ExactDjangoJSONEncoder(DjangoJSONEncoder):
    """Preserve all six microsecond digits instead of truncating to milliseconds."""

    def default(self, value):
        if isinstance(value, datetime.datetime):
            result = value.isoformat(timespec="microseconds")
            if result.endswith("+00:00"):
                result = result.removesuffix("+00:00") + "Z"
            return result
        if isinstance(value, datetime.time):
            if value.utcoffset() is not None:
                raise ValueError("JSON cannot represent timezone-aware times")
            return value.isoformat(timespec="microseconds")
        return super().default(value)


django.setup()
from django.core.serializers import jsonl

jsonl.DjangoJSONEncoder = ExactDjangoJSONEncoder
call_command(
    "dumpdata",
    format="jsonl",
    output=os.environ["FIXTURE_OUTPUT"],
    use_base_manager=True,
    verbosity=1,
)
PY

test -s "$MIG/sqlite-full.jsonl"
expected_lines=$(awk -F '|' '$1 == "MODEL" { total += $3 } END { print total + 0 }' \
  "$MIG/sqlite-manifest.txt")
actual_lines=$(wc -l < "$MIG/sqlite-full.jsonl")
test "$actual_lines" -eq "$expected_lines"
printf 'JSONL objects: %s\n' "$actual_lines"

sqlite3 -separator $'\t' /srv/ais_uzmo/db.sqlite3 \
  'SELECT app, name FROM django_migrations ORDER BY app, name;' \
  > "$MIG/sqlite-migrations.tsv"
sha256sum "$MIG/sqlite-full.jsonl" > "$MIG/sqlite-full.jsonl.sha256"
sha256sum -c "$MIG/sqlite-full.jsonl.sha256"
~~~

Одна строка JSONL соответствует одному сериализованному объекту. В файл не
попадает содержимое фотографий — они уже сохранены в `media.tar.gz`. Команда
`test` не даст продолжить миграцию, если число строк JSONL не равно сумме строк
обычных моделей из исходного manifest.

### 8.2. Создание схемы PostgreSQL

~~~bash
install -d -o ais -g ais -m 0750 /srv/ais_uzmo/logs

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py migrate \
  --noinput

sudo -u postgres psql -X -d ais_uzmo -At -F $'\t' \
  -c 'SELECT app, name FROM django_migrations ORDER BY app, name;' \
  > "$MIG/postgres-migrations-before-import.tsv"
diff -u "$MIG/sqlite-migrations.tsv" \
  "$MIG/postgres-migrations-before-import.tsv"

# До первого TRUNCATE обязательно сохраняем текущее состояние PostgreSQL.
# Это важно и после репетиционного импорта, и при повторном запуске процедуры.
PRE=$(readlink -f /var/backups/ais_uzmo/pre-production-current)
test -d "$PRE"
sudo -u postgres pg_dump --format=custom --no-owner --no-acl ais_uzmo \
  > "$PRE/postgresql-before-import.dump"
chmod 0600 "$PRE/postgresql-before-import.dump"
pg_restore --list "$PRE/postgresql-before-import.dump" >/dev/null
pg_restore --exit-on-error --file=/dev/null \
  "$PRE/postgresql-before-import.dump"
sha256sum "$PRE/postgresql-before-import.dump" \
  > "$PRE/postgresql-before-import.dump.sha256"
chmod 0600 "$PRE/postgresql-before-import.dump.sha256"
sha256sum -c "$PRE/postgresql-before-import.dump.sha256"
~~~

`diff` должен быть пустым: перед переносом схема PostgreSQL обязана иметь точно
тот же упорядоченный набор `(app, name)`, что и SQLite. Поле `applied` здесь
намеренно не сравнивается — время применения одной и той же миграции на двух БД
закономерно различается. `pg_restore --list` должен завершиться успешно.

`migrate` сначала создаёт служебные content types и permissions. Только после
сверки миграций и проверенного PostgreSQL backup можно загрузить **точные** строки
и PK из SQLite: очистите все таблицы, кроме `django_migrations`. Сама схема,
индексы и история применённых миграций останутся:

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

sudo -u ais env \
  DJANGO_SETTINGS_MODULE=config.settings_prod \
  MANIFEST_SCRIPT="$MIG/db_manifest.py" \
  /srv/ais_uzmo/.venv/bin/python -c \
  'import os; import django; django.setup(); exec(open(os.environ["MANIFEST_SCRIPT"], encoding="utf-8").read())' \
  > "$MIG/postgres-manifest.txt"

diff -u "$MIG/sqlite-manifest.txt" "$MIG/postgres-manifest.txt"

sudo -u postgres psql -X -d ais_uzmo -At -F $'\t' \
  -c 'SELECT app, name FROM django_migrations ORDER BY app, name;' \
  > "$MIG/postgres-migrations-after-import.tsv"
diff -u "$MIG/sqlite-migrations.tsv" \
  "$MIG/postgres-migrations-after-import.tsv"

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py shell \
  -c "from django.db import connection; connection.check_constraints(); print('constraints: ok')"
~~~

Строки `MODEL` содержат label, count, min PK, max PK и SHA-256 всех concrete-полей
в порядке PK. Значения, включая персональные данные и password hashes, в manifest
не печатаются. Один и тот же `ExactDjangoJSONEncoder` используется в manifest и
JSONL, сохраняя все шесть цифр микросекунд; временные поля не теряют точность и
тоже участвуют в сравнении SQLite с PostgreSQL. Скрытый surrogate PK
автоматической M2M-таблицы не входит в `dumpdata`, поэтому строка `M2M`
сравнивает count и SHA-256 отсортированных наборов всех concrete non-PK полей,
то есть сами связи. Оба `diff` не должны вывести различий. Затем выполните
проверки целостности:

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

# Импорт не изменяет media, поэтому исходный media.tar.gz остаётся точной парой
# к PostgreSQL после импорта. Миниатюры в критическом cutover не генерируем.
PRE=$(readlink -f /var/backups/ais_uzmo/pre-production-current)
sudo -u postgres pg_dump --format=custom --no-owner --no-acl ais_uzmo \
  > "$PRE/postgresql-after-import.dump"
install -o root -g root -m 0600 /srv/ais_uzmo/.env \
  "$PRE/app-production.env"
chmod 0600 "$PRE/postgresql-after-import.dump"
sha256sum "$PRE/postgresql-after-import.dump" \
  "$PRE/media.tar.gz" "$PRE/app-production.env" \
  > "$PRE/SHA256SUMS-after-import"
sha256sum -c "$PRE/SHA256SUMS-after-import"
pg_restore --list "$PRE/postgresql-after-import.dump" >/dev/null
pg_restore --exit-on-error --file=/dev/null \
  "$PRE/postgresql-after-import.dump"
tar -tzf "$PRE/media.tar.gz" >/dev/null
~~~

Не заменяйте `/media/` в Nginx публичным `alias`: фотографии выдаются Django
через защищённые маршруты с проверкой прав пользователя. Файлы
`postgresql-after-import.dump`, исходный `media.tar.gz` и `app-production.env`
образуют один согласованный recovery-set. `db.sqlite3` с тем же `media.tar.gz`
остаётся отдельным набором для rollback. Не запускайте между экспортом SQLite и
созданием recovery-set команды, меняющие файлы media или ссылки на них в БД.

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
~~~

Пока не запускайте и не включайте новый unit: при перезагрузке сервера два
enabled-unit будут конкурировать за `127.0.0.1:8000`. Включение выполняется
только внутри защищённого переключения в разделе 12.

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

Maintenance-site `/etc/nginx/sites-available/ais_uzmo-maintenance` уже создан и
включён в разделе 3. Он удерживает публичную границу на `503` во время импорта и
первого backup; production-site нельзя включать раньше точки commit раздела 12.

Лимит `250M` относится ко всему HTTP-запросу. Само приложение дополнительно
ограничивает одну фотографию 8 МБ и разрешает JPG/JPEG, PNG и WEBP.

Пока только проверьте наличие файла. Не включайте новый site и не удаляйте
старый: фактическая смена symlink выполняется внутри rollback-защищённого блока
раздела 12.

~~~bash
test -f /etc/nginx/sites-available/ais_uzmo
test -f /etc/nginx/sites-available/ais_uzmo-maintenance
nginx -t  # проверяет пока ещё действующую конфигурацию
~~~

Если upload возвращает `413 Request Entity Too Large`, сначала проверьте
активную конфигурацию:

~~~bash
nginx -T 2>/dev/null | grep -n client_max_body_size
~~~

`404` на прямом URL `/media/...`, напротив, является ожидаемой защитой и не
означает ошибку загрузки.

## 12. Переключение на production

**До запуска блока** настройте безопасное CIDR/VPN-правило из раздела 13 и
убедитесь, что глобального разрешения порта 80 нет. Reload Nginx внутри блока
сразу делает сайт доступным через все источники, которые пропускает firewall.
Также заранее создайте backup script, service и timer из раздела 15, но пока не
включайте timer: первый проверенный backup выполняется до публичного commit.

До публичного commit следующий блок при любой ошибке, `SIGHUP`, `SIGINT` или
`SIGTERM` отключает новый unit, возвращает старый `.env`, старый unit и старый
Nginx site. После reload production-site автоматический rollback намеренно
запрещён: он мог бы потерять уже принятые PostgreSQL-записи. `SIGKILL`
перехватить невозможно, поэтому текущий SSH-сеанс до smoke-проверок не
закрывайте.

На фактическом сервере полный cutover-сценарий был сохранён в
`/root/final_cutover.sh`, проверен через `bash -n` и запущен как отдельный
transient unit. Это защищает длительную миграцию от обрыва SSH и от стандартного
90-секундного start-timeout systemd:

~~~bash
bash -n /root/final_cutover.sh
systemd-run --no-block \
  --unit=ais-uzmo-final-cutover \
  --property=Type=oneshot \
  --property=TimeoutStartSec=infinity \
  --property=TimeoutStopSec=5min \
  --property=StandardOutput=journal \
  --property=StandardError=journal \
  /root/final_cutover.sh

systemctl show ais-uzmo-final-cutover.service \
  -p ActiveState -p SubState -p Result -p ExecMainStatus
journalctl -fu ais-uzmo-final-cutover.service
~~~

`--no-block` обязателен для фонового запуска: без него `systemd-run` ждёт
завершения `Type=oneshot`. Сам `/root/final_cutover.sh` не является частью Git и
содержит серверно-специфичный оркестратор; эталонные действия приведены ниже и в
разделах 3/8/15.

~~~bash
set -Eeuo pipefail

APP=/srv/ais_uzmo
OLD_SERVICE=ais_uzmo-test.service
NEW_SERVICE=ais_uzmo.service
PRE=$(readlink -f /var/backups/ais_uzmo/pre-production-current)
cutover_committed=0

rollback_cutover() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$cutover_committed" -eq 0 ]; then
    set +e
    printf 'Cutover failed; restoring SQLite service.\n' >&2

    # Важно не только остановить, но и disable новый unit: иначе после reboot
    # оба сервиса будут конкурировать за 127.0.0.1:8000.
    systemctl disable --now ais-uzmo-backup.timer
    # Дожидаемся остановки уже выполняющегося oneshot: иначе его EXIT-trap
    # позже снова запустит production unit поверх восстановленного SQLite.
    systemctl stop ais-uzmo-backup.service
    systemctl disable --now "$NEW_SERVICE"

    cp -a "$PRE/app.env" "$APP/.env"
    chown ais:ais "$APP/.env"
    chmod 0600 "$APP/.env"

    systemctl unmask --runtime "$OLD_SERVICE"
    systemctl enable "$OLD_SERVICE"
    systemctl start "$OLD_SERVICE"

    rm -f /etc/nginx/sites-enabled/ais_uzmo \
      /etc/nginx/sites-enabled/ais_uzmo-maintenance
    ln -sfn /etc/nginx/sites-available/ais_uzmo-test \
      /etc/nginx/sites-enabled/ais_uzmo-test
    if nginx -t; then
      systemctl reload nginx
    fi
  fi
  exit "$status"
}

trap rollback_cutover EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

test -f "$PRE/app.env"
test -f /etc/systemd/system/ais_uzmo-test.service
test -f /etc/systemd/system/ais_uzmo.service
test -f /etc/nginx/sites-available/ais_uzmo-test
test -f /etc/nginx/sites-available/ais_uzmo
test -f /etc/nginx/sites-available/ais_uzmo-maintenance
test -f /etc/systemd/system/ais-uzmo-backup.service
test -f /etc/systemd/system/ais-uzmo-backup.timer

ln -sfn /etc/nginx/sites-available/ais_uzmo-maintenance \
  /etc/nginx/sites-enabled/ais_uzmo-maintenance
rm -f /etc/nginx/sites-enabled/ais_uzmo \
  /etc/nginx/sites-enabled/ais_uzmo-test \
  /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
maintenance_ready=false
for attempt in $(seq 1 30); do
  maintenance_code=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' \
    -H 'Host: 193.168.46.149' \
    http://127.0.0.1/accounts/login/ 2>/dev/null || true)
  if [ "$maintenance_code" = "503" ]; then
    maintenance_ready=true
    break
  fi
  sleep 1
done
test "$maintenance_ready" = "true"

systemctl disable --now "$OLD_SERVICE"
systemctl mask --runtime "$OLD_SERVICE"
systemctl enable "$NEW_SERVICE"
systemctl start "$NEW_SERVICE"
systemctl is-active --quiet "$NEW_SERVICE"

gunicorn_ready=false
for attempt in $(seq 1 30); do
  gunicorn_code=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' \
    -H 'Host: 193.168.46.149' \
    http://127.0.0.1:8000/accounts/login/ 2>/dev/null || true)
  if [ "$gunicorn_code" = "200" ]; then
    gunicorn_ready=true
    break
  fi
  sleep 1
done
test "$gunicorn_ready" = "true"

# Проверяем Redis до объявления cutover успешным; секреты остаются только в
# защищённом .env и не попадают в аргументы процесса или вывод.
sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py shell \
  -c "from django.core.cache import cache; cache.set('cutover-smoke', 'ok', 30); assert cache.get('cutover-smoke') == 'ok'"

# Первый backup выполняется вручную при закрытом public traffic. Удаление
# persistent-state исключает отложенный второй запуск старого timer.
systemctl disable --now ais-uzmo-backup.timer
systemctl stop ais-uzmo-backup.service
systemctl clean --what=state ais-uzmo-backup.timer || true
systemctl reset-failed ais-uzmo-backup.service ais-uzmo-backup.timer || true
systemctl start ais-uzmo-backup.service
test "$(systemctl show -p Result --value ais-uzmo-backup.service)" = "success"
systemctl is-active --quiet "$NEW_SERVICE"
post_backup_ready=false
for attempt in $(seq 1 60); do
  post_backup_code=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' \
    -H 'Host: 193.168.46.149' \
    http://127.0.0.1:8000/accounts/login/ 2>/dev/null || true)
  if [ "$post_backup_code" = "200" ]; then
    post_backup_ready=true
    break
  fi
  sleep 1
done
test "$post_backup_ready" = "true"
systemctl enable ais-uzmo-backup.timer
systemctl is-enabled --quiet ais-uzmo-backup.timer
systemctl unmask --runtime "$OLD_SERVICE"

ln -sfn /etc/nginx/sites-available/ais_uzmo \
  /etc/nginx/sites-enabled/ais_uzmo
rm -f /etc/nginx/sites-enabled/ais_uzmo-test \
  /etc/nginx/sites-enabled/ais_uzmo-maintenance \
  /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# Reload выше — публичная точка commit. Сначала запрещаем автоматический
# rollback, и только потом выполняем внешние/post-commit проверки.
cutover_committed=1
trap - EXIT HUP INT TERM

nginx_ready=false
for attempt in $(seq 1 30); do
  nginx_code=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' \
    -H 'Host: 193.168.46.149' \
    http://127.0.0.1/accounts/login/ 2>/dev/null || true)
  if [ "$nginx_code" = "200" ]; then
    nginx_ready=true
    break
  fi
  sleep 1
done
test "$nginx_ready" = "true"
touch "$PRE/CUTOVER_COMPLETE"
systemctl start ais-uzmo-backup.timer
systemctl is-active --quiet ais-uzmo-backup.timer

systemctl status ais_uzmo.service --no-pager
journalctl -u ais_uzmo.service -n 100 --no-pager
~~~

Только когда новый сервис прошёл также браузерные проверки раздела 14 и создан
первый ежедневный backup, старый unit можно убрать; его копия уже находится в
pre-production backup:

~~~bash
rm -f /etc/systemd/system/ais_uzmo-test.service
systemctl daemon-reload
systemctl reset-failed
~~~

Не удаляйте старый SQLite-файл и PostgreSQL backup во время первичной проверки.

## 13. Firewall

Сначала разрешите реальный SSH-порт, иначе можно потерять доступ. Для HTTP без
TLS рекомендуемый вариант — открыть порт 80 только от доверенного адреса или
сети. Замените placeholder реальным IP/CIDR администратора, VPN или внутренней
сети **до** выполнения команды:

~~~bash
ufw allow 22/tcp
TRUSTED_CIDR='ЗАМЕНИТЬ_НА_ДОВЕРЕННЫЙ_IP_ИЛИ_CIDR'
ufw allow from "$TRUSTED_CIDR" to any port 80 proto tcp \
  comment 'AIS UZMO temporary HTTP from trusted network'
ufw status verbose
~~~

Проверьте аналогичное ограничение во внешнем firewall/security group
хостинг-провайдера. Если ранее уже было глобальное правило, найдите его через
`ufw status numbered` и удалите `ufw delete allow 80/tcp` либо соответствующий
номер только после добавления доверенного CIDR.

Глобально публичный временный режим технически включается так:

~~~bash
ufw allow 80/tcp comment 'AIS UZMO TEMPORARY PUBLIC INSECURE HTTP'
~~~

Эта команда открывает форму входа на публичном IP всему Интернету. Используйте
её только после явного принятия риска: по HTTP нельзя вводить production-пароли,
передавать session cookie, персональные данные или файлы. Для реальной работы
нужны HTTPS, VPN либо ограничение источника предыдущим правилом.

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
STAMP=$(date -u +%Y%m%dT%H%M%S.%NZ)
STAGING="$BACKUP_ROOT/.staging-$STAMP-$$"
DEST="$BACKUP_ROOT/$STAMP"
LOCK_FILE=/run/lock/ais-uzmo-backup.lock
was_active=false
complete=false

exec 9>"$LOCK_FILE"
flock -n 9 || {
  printf 'Another AIS UZMO backup is already running.\n' >&2
  exit 75
}

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  set +e
  if [ "$was_active" = true ]; then
    systemctl start ais_uzmo.service
  fi
  if [ "$complete" != true ]; then
    rm -rf -- "$STAGING"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

install -d -m 0700 "$BACKUP_ROOT"
install -d -m 0700 "$STAGING"
test ! -e "$DEST"

if systemctl is-active --quiet ais_uzmo.service; then
  was_active=true
  systemctl stop ais_uzmo.service
fi

runuser -u postgres -- pg_dump --format=custom --no-owner --no-privileges \
  ais_uzmo > "$STAGING/database.dump"
runuser -u postgres -- pg_dumpall --globals-only \
  > "$STAGING/postgresql-globals.sql"
tar -C "$APP" -czf "$STAGING/media.tar.gz" media
cp --preserve=mode,timestamps "$APP/.env" "$STAGING/app.env"
cp -a /etc/systemd/system/ais_uzmo.service "$STAGING/"
cp -a /etc/nginx/sites-available/ais_uzmo "$STAGING/"
runuser -u ais -- git -C "$APP" rev-parse HEAD \
  > "$STAGING/git-commit.txt"

pg_restore --list "$STAGING/database.dump" >/dev/null
pg_restore --exit-on-error --file=/dev/null "$STAGING/database.dump"
tar -tzf "$STAGING/media.tar.gz" >/dev/null
(
  cd "$STAGING"
  sha256sum database.dump media.tar.gz app.env postgresql-globals.sql \
    > SHA256SUMS
  sha256sum -c SHA256SUMS
)
touch "$STAGING/COMPLETE"
mv "$STAGING" "$DEST"
complete=true

if [ "$was_active" = true ]; then
  systemctl start ais_uzmo.service
  systemctl is-active --quiet ais_uzmo.service
  was_active=false
fi

# Храним 14 суток. Маска не затрагивает другие каталоги внутри BACKUP_ROOT.
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d \
  -name '????????T??????.?????????Z' -mtime +14 -exec rm -rf -- {} +

trap - EXIT HUP INT TERM
printf 'Backup completed: %s\n' "$DEST"
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
TimeoutStartSec=30min
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

В защищённом переключении раздела 12 timer уже включается, а первый backup
создаётся под maintenance-страницей до публичного commit. При настройке вне
cutover либо для повторной проверки выполните:

~~~bash
systemctl daemon-reload
# Сначала один синхронный backup, затем timer. Очистка старого persistent-state
# не даёт таймеру немедленно поставить второй catch-up запуск.
systemctl disable --now ais-uzmo-backup.timer
systemctl stop ais-uzmo-backup.service
systemctl clean --what=state ais-uzmo-backup.timer || true
systemctl start ais-uzmo-backup.service
systemctl status ais-uzmo-backup.service --no-pager
systemctl is-active ais_uzmo.service
systemctl enable ais-uzmo-backup.timer
systemctl start ais-uzmo-backup.timer
systemctl list-timers ais-uzmo-backup.timer

LATEST=$(find /var/backups/ais_uzmo/daily -mindepth 1 -maxdepth 1 \
  -type d -name '*T*Z' | sort | tail -n 1)
test -f "$LATEST/COMPLETE"
cd "$LATEST"
sha256sum -c SHA256SUMS
pg_restore --list database.dump >/dev/null
pg_restore --exit-on-error --file=/dev/null database.dump
tar -tzf media.tar.gz >/dev/null
~~~

Копию нужно регулярно переносить на другой сервер/носитель. Backup на том же
диске не защищает от потери самого сервера. Периодически выполняйте тестовое
восстановление.

### 15.1. Отдельное обслуживание миниатюр после deployment

`generate_photo_thumbnails` намеренно не входит в критический cutover: команда
меняет и PostgreSQL, и `media`, а отдельные ошибки фотографий учитывает в сводке,
не завершая процесс с ненулевым exit code. Запускайте её только после успешных
smoke-проверок и первого ежедневного backup. Блок ниже делает backup до операции,
останавливает приложение, проверяет `Ошибок: 0`, возвращает сервис при ошибке или
сигнале и затем создаёт новый согласованный backup.

~~~bash
set -Eeuo pipefail
umask 077

systemctl start ais-uzmo-backup.service
test "$(systemctl show -p Result --value ais-uzmo-backup.service)" = "success"
PRE_MAINTENANCE=$(find /var/backups/ais_uzmo/daily -mindepth 1 -maxdepth 1 \
  -type d -name '*T*Z' | sort | tail -n 1)
test -f "$PRE_MAINTENANCE/COMPLETE"

systemctl is-active --quiet ais_uzmo.service
systemctl is-active --quiet ais-uzmo-backup.timer

THUMBNAIL_OUT=$(mktemp /var/tmp/ais-uzmo-thumbnails.XXXXXX.out)
THUMBNAIL_ERR=$(mktemp /var/tmp/ais-uzmo-thumbnails.XXXXXX.err)
cleanup_armed=1

finish_thumbnail_maintenance() {
  status=$?
  trap - EXIT HUP INT TERM
  set +e
  if [ "$status" -eq 0 ]; then
    rm -f "$THUMBNAIL_OUT" "$THUMBNAIL_ERR"
  else
    printf 'Thumbnail logs retained: %s %s\n' \
      "$THUMBNAIL_OUT" "$THUMBNAIL_ERR" >&2
  fi
  if [ "$cleanup_armed" -eq 1 ]; then
    systemctl start ais_uzmo.service
    systemctl start ais-uzmo-backup.timer
  fi
  exit "$status"
}

trap finish_thumbnail_maintenance EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

systemctl stop ais-uzmo-backup.timer
systemctl stop ais_uzmo.service

runuser -u ais -- env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py \
  generate_photo_thumbnails --include-deleted \
  > "$THUMBNAIL_OUT" 2> "$THUMBNAIL_ERR"

cat "$THUMBNAIL_OUT"
if [ -s "$THUMBNAIL_ERR" ]; then
  cat "$THUMBNAIL_ERR" >&2
fi
grep -Fq 'Ошибок: 0.' "$THUMBNAIL_OUT"

runuser -u ais -- env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py shell \
  -c 'from django.db import connection; connection.check_constraints(); print("constraints: ok")'

chown -R ais:www-data /srv/ais_uzmo/media
find /srv/ais_uzmo/media -type d -exec chmod 2750 {} +
find /srv/ais_uzmo/media -type f -exec chmod 0640 {} +

systemctl start ais_uzmo.service
systemctl start ais-uzmo-backup.timer
cleanup_armed=0
trap - EXIT HUP INT TERM
rm -f "$THUMBNAIL_OUT" "$THUMBNAIL_ERR"

systemctl start ais-uzmo-backup.service
test "$(systemctl show -p Result --value ais-uzmo-backup.service)" = "success"
POST_MAINTENANCE=$(find /var/backups/ais_uzmo/daily -mindepth 1 -maxdepth 1 \
  -type d -name '*T*Z' | sort | tail -n 1)
test -n "$POST_MAINTENANCE"
test "$POST_MAINTENANCE" != "$PRE_MAINTENANCE"
test -f "$POST_MAINTENANCE/COMPLETE"
(
  cd "$POST_MAINTENANCE"
  sha256sum -c SHA256SUMS
  pg_restore --list database.dump >/dev/null
  pg_restore --exit-on-error --file=/dev/null database.dump
  tar -tzf media.tar.gz >/dev/null
)
~~~

Если проверка `Ошибок: 0` не прошла, приложение будет запущено снова, но часть
миниатюр уже могла быть создана. Не объявляйте обслуживание завершённым:
исследуйте сохранённый вывод текущего запуска, устраните причину и повторите
операцию. Исходный `PRE_MAINTENANCE` остаётся точкой восстановления.

## 16. Восстановление из ежедневного backup

Ниже `BACKUP_DIR` — каталог, содержащий `COMPLETE`:

~~~bash
set -Eeuo pipefail

BACKUP_DIR=/var/backups/ais_uzmo/daily/YYYYMMDDTHHMMSS.NNNNNNNNNZ
test -f "$BACKUP_DIR/COMPLETE"
cd "$BACKUP_DIR"
sha256sum -c SHA256SUMS
pg_restore --list database.dump >/dev/null
pg_restore --exit-on-error --file=/dev/null database.dump
tar -tzf media.tar.gz >/dev/null
test -f /srv/ais_uzmo/.env

# Disabled units не запустятся на полувосстановленной БД после случайного reboot.
systemctl disable --now ais-uzmo-backup.timer
systemctl disable --now ais_uzmo.service

sudo -u postgres psql -d postgres --set ON_ERROR_STOP=1 -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='ais_uzmo' AND pid <> pg_backend_pid();"
sudo -u postgres dropdb --if-exists ais_uzmo
sudo -u postgres createdb --owner=ais_uzmo --encoding=UTF8 \
  --template=template0 ais_uzmo

sudo -u postgres psql -d postgres --set ON_ERROR_STOP=1 <<'SQL'
REVOKE ALL ON DATABASE ais_uzmo FROM PUBLIC;
GRANT CONNECT, TEMPORARY, CREATE ON DATABASE ais_uzmo TO ais_uzmo;
SQL

sudo -u postgres psql -d ais_uzmo --set ON_ERROR_STOP=1 <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO ais_uzmo;
SET ROLE ais_uzmo;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
RESET ROLE;
SQL

# --role принципиален: при запуске pg_restore только от postgres и с
# --no-owner все tables/sequences стали бы собственностью postgres, после чего
# приложение получило бы permission denied.
sudo -u postgres pg_restore --exit-on-error --no-owner --no-acl \
  --role=ais_uzmo \
  --dbname=ais_uzmo < "$BACKUP_DIR/database.dump"

foreign_owner_count=$(sudo -u postgres psql -X -d ais_uzmo -Atc \
  "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p','i','S','v','m') AND pg_get_userbyid(c.relowner) <> 'ais_uzmo'")
test "$foreign_owner_count" = "0"

RESTORE_STAMP=$(date -u +%Y%m%dT%H%M%SZ)
if [ -d /srv/ais_uzmo/media ]; then
  mv /srv/ais_uzmo/media \
    "/srv/ais_uzmo/media.before-restore-$RESTORE_STAMP"
fi
tar -C /srv/ais_uzmo -xzf "$BACKUP_DIR/media.tar.gz"

chown -R ais:www-data /srv/ais_uzmo/media
find /srv/ais_uzmo/media -type d -exec chmod 2750 {} +
find /srv/ais_uzmo/media -type f -exec chmod 0640 {} +

sudo -u ais env DJANGO_SETTINGS_MODULE=config.settings_prod \
  /srv/ais_uzmo/.venv/bin/python /srv/ais_uzmo/manage.py migrate --noinput

systemctl enable --now ais_uzmo.service
systemctl enable --now ais-uzmo-backup.timer
systemctl status ais_uzmo.service --no-pager
~~~

`app.env` нужен только при восстановлении всего сервера или потере рабочего
`.env`; в остальных случаях сохраняйте действующий файл. Если он потерян,
установите `BACKUP_DIR/app.env` как `/srv/ais_uzmo/.env` с владельцем `ais:ais` и
режимом `0600` **до** запуска блока выше. В нём находятся пароли и `SECRET_KEY`.

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
set -Eeuo pipefail

PRE=$(readlink -f /var/backups/ais_uzmo/pre-production-current)
ROLLBACK_STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FAILED=/var/backups/ais_uzmo/failed-production-$ROLLBACK_STAMP

test -f "$PRE/app.env"
test -f "$PRE/db.sqlite3"
test -f "$PRE/media.tar.gz"
test -f "$PRE/git-head"
test -f "$PRE/ais_uzmo-test.service"

systemctl disable --now ais-uzmo-backup.timer
systemctl disable --now ais_uzmo.service

install -d -m 0700 "$FAILED"
sudo -u postgres pg_dump --format=custom --no-owner --no-acl ais_uzmo \
  > "$FAILED/database.dump"
tar -C /srv/ais_uzmo -czf \
  "$FAILED/media.tar.gz" \
  media
cp -a /srv/ais_uzmo/.env "$FAILED/app.env"
sha256sum "$FAILED/database.dump" "$FAILED/media.tar.gz" \
  "$FAILED/app.env" > "$FAILED/SHA256SUMS"
sha256sum -c "$FAILED/SHA256SUMS"
pg_restore --list "$FAILED/database.dump" >/dev/null
pg_restore --exit-on-error --file=/dev/null "$FAILED/database.dump"
tar -tzf "$FAILED/media.tar.gz" >/dev/null
touch "$FAILED/COMPLETE"

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
- `ais_uzmo.service` активен и enabled, `ais_uzmo-test.service` остановлен и
  disabled;
- PostgreSQL и Redis доступны только с loopback;
- Redis требует пароль;
- production PostgreSQL role не имеет `CREATEDB`;
- Gunicorn слушает только `127.0.0.1:8000`;
- Nginx публикует `/static/`, но возвращает 404 для прямого `/media/`;
- `X-Forwarded-For` перезаписывается адресом клиента, а не дополняется
  недоверенной цепочкой;
- лимит запроса Nginx — 250 МБ;
- ежедневный backup имеет маркер `COMPLETE` и проходит SHA-256-проверку;
- тестовое восстановление создаёт tables/sequences с владельцем `ais_uzmo`;
- копия backup хранится вне этого сервера;
- до HTTPS порт 80 ограничен доверенным IP/CIDR/VPN; глобальный публичный HTTP
  не используется для паролей, cookie, персональных данных и файлов;
- временный SSH-ключ удалён после завершения работ.
