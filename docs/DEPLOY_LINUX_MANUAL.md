# Ручное развёртывание АИС УЗМО на Ubuntu

Эта инструкция описывает ручную установку приложения на отдельный чистый сервер
Ubuntu 24.04. Она предназначена для Linux-администратора, который хочет сам
проверить и выполнить каждый этап.

Это альтернатива автоматической установке из `DEPLOY_LINUX.md`. На одном сервере
нужно выбрать только один вариант: либо `deploy/install.sh`, либо действия ниже.

В результате будут настроены PostgreSQL, Redis, Gunicorn, systemd, Nginx,
ежедневные резервные копии и UFW. Все команды выполняются от `root`.

Выполняйте блоки по порядку и переходите дальше только при отсутствии ошибок. Не
вставляйте весь документ в терминал одной командой: ручная процедура специально
оставляет администратору контроль после каждого этапа.

> Установка меняет общие настройки PostgreSQL, Redis, Nginx и UFW. Сервер должен
> быть выделен под АИС УЗМО. Если на нём уже работают другие системы, сначала
> согласуйте совместную конфигурацию с ответственным администратором.

## 1. Подготовить значения и распаковать релиз

Получите от разработчика три файла:

```text
ais_uzmo-1.0.0.tar.gz
SHA256SUMS
RELEASE.txt
```

Номер версии может отличаться. Скопируйте файлы в `/root`, войдите на сервер по
SSH. До перехода в root-сеанс посмотрите `SSH_CONNECTION`: первое поле — адрес
вашего компьютера, четвёртое — порт SSH на сервере. Они понадобятся для UFW.

```bash
printf '%s\n' "$SSH_CONNECTION"
```

Затем откройте root-сеанс:

```bash
sudo -i
set -Eeuo pipefail
umask 027
```

Задайте реальные значения. Эти переменные действуют только в текущем сеансе,
поэтому не закрывайте его до окончания установки:

```bash
export VERSION=1.0.0
export ARCHIVE=/root/ais_uzmo-$VERSION.tar.gz
export SOURCE=/root/ais_uzmo-install-$VERSION
export APP=/srv/ais_uzmo

export SERVER_NAME=10.20.30.40
export TRUSTED_CIDR=10.20.30.0/24
export SSH_PORT=22
export SSH_CLIENT_IP=10.20.30.50
export SSH_SERVER_PORT=22
export ADMIN_USERNAME=admin
export ADMIN_EMAIL=admin@example.local
```

- `SERVER_NAME` — IP-адрес или внутреннее DNS-имя без `http://`, порта и `/`;
- `TRUSTED_CIDR` — разрешённый адрес или сеть IPv4; не используйте `0.0.0.0/0`;
- `SSH_PORT` — фактический порт SSH на сервере;
- `SSH_CLIENT_IP` и `SSH_SERVER_PORT` — первое и четвёртое поля сохранённого
  `SSH_CONNECTION`;
- `ADMIN_EMAIL` можно оставить пустым: `export ADMIN_EMAIL=`.

Проверьте простые поля до начала установки:

```bash
[[ "$SERVER_NAME" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$ ]]
[[ "$SSH_PORT" =~ ^[0-9]+$ ]] && ((10#$SSH_PORT >= 1 && 10#$SSH_PORT <= 65535))
[[ "$SSH_SERVER_PORT" =~ ^[0-9]+$ ]] && \
  ((10#$SSH_SERVER_PORT >= 1 && 10#$SSH_SERVER_PORT <= 65535))
[[ "$ADMIN_USERNAME" =~ ^[A-Za-z0-9@.+_-]{1,150}$ ]]
if [ -n "$ADMIN_EMAIL" ]; then
  [[ "$ADMIN_EMAIL" =~ ^[^[:space:]]+@[^[:space:]]+$ ]]
fi
```

Проверьте контрольную сумму и распакуйте архив:

```bash
cd /root
sha256sum -c SHA256SUMS

tar -tzf "$ARCHIVE" >/dev/null
while IFS= read -r entry; do
  if [[ "$entry" = /* || "$entry" = ../* || "$entry" = *'/../'* || \
        "$entry" = *'/..' ]]; then
    echo "Небезопасный путь в архиве: $entry" >&2
    exit 1
  fi
done < <(tar -tzf "$ARCHIVE")

while read -r mode _; do
  case "${mode:0:1}" in
    -|d) ;;
    *) echo 'Архив содержит неподдерживаемый тип файла.' >&2; exit 1 ;;
  esac
done < <(tar -tvzf "$ARCHIVE")

if [ -e "$SOURCE" ] || [ -L "$SOURCE" ]; then
  echo "Каталог распаковки уже существует: $SOURCE" >&2
  exit 1
fi
install -d -m 0755 "$SOURCE"
tar -xzf "$ARCHIVE" -C "$SOURCE" --strip-components=1

for required in \
  manage.py \
  requirements.txt \
  config/settings_prod.py \
  deploy/check.sh \
  deploy/update.sh \
  deploy/backup.sh \
  deploy/release.sh \
  deploy/thresholds.sh \
  deploy/ais_uzmo.service \
  deploy/nginx.conf.template \
  deploy/ais-uzmo-backup.service \
  deploy/ais-uzmo-backup.timer; do
  test -f "$SOURCE/$required"
done
test "$(tr -d '[:space:]' < "$SOURCE/deploy/VERSION")" = "$VERSION"

if find "$SOURCE" ! -type f ! -type d -print -quit | grep -q .; then
  echo 'Архив содержит неподдерживаемые специальные файлы.' >&2
  exit 1
fi
```

Проверка SHA-256 должна вывести `OK`. При любой ошибке остановитесь и запросите
новый комплект.

## 2. Убедиться, что сервер чистый

Проверьте версию системы:

```bash
grep -qx 'ID=ubuntu' /etc/os-release
grep -qx 'VERSION_ID="24.04"' /etc/os-release
```

Следующие объекты не должны существовать:

```bash
for path in \
  /srv/ais_uzmo \
  /etc/ais_uzmo \
  /etc/nginx/sites-available/ais_uzmo \
  /etc/nginx/sites-enabled/ais_uzmo \
  /etc/systemd/system/ais_uzmo.service \
  /etc/systemd/system/ais-uzmo-backup.service \
  /etc/systemd/system/ais-uzmo-backup.timer \
  /usr/local/sbin/ais-uzmo-backup \
  /etc/redis/ais_uzmo.conf \
  /etc/redis/redis.conf.before-ais-uzmo \
  /var/backups/ais_uzmo; do
  if [ -e "$path" ] || [ -L "$path" ]; then
    echo "Уже существует: $path" >&2
    exit 1
  fi
done

if id ais >/dev/null 2>&1 || getent group ais >/dev/null 2>&1; then
  echo 'Пользователь или группа ais уже существуют.' >&2
  exit 1
fi

if [ -e /etc/nginx/sites-enabled/default ] || \
   [ -L /etc/nginx/sites-enabled/default ]; then
  if [ ! -L /etc/nginx/sites-enabled/default ] || \
     [ "$(readlink -- /etc/nginx/sites-enabled/default)" != \
       /etc/nginx/sites-available/default ]; then
    echo 'sites-enabled/default не является штатной ссылкой Nginx.' >&2
    exit 1
  fi
fi
```

Если какая-либо команда завершилась с ошибкой, не удаляйте найденные данные
вслепую: выясните, не установлена ли уже система.

## 3. Установить системные пакеты

Серверу нужен доступ к репозиториям Ubuntu и Python напрямую или через внутренние
зеркала.

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl nginx openssl postgresql postgresql-contrib \
  python3 python3-pip python3-venv redis-server rsync tar ufw

systemctl enable --now postgresql nginx

python3 - "$TRUSTED_CIDR" "$SSH_CLIENT_IP" <<'PY'
import ipaddress
import sys

network = ipaddress.ip_network(sys.argv[1], strict=False)
client = ipaddress.ip_address(sys.argv[2])
if network.version != 4 or network.prefixlen == 0:
    raise SystemExit("TRUSTED_CIDR должен быть IPv4-сетью без /0")
if client.version not in (4, 6):
    raise SystemExit("Некорректный SSH_CLIENT_IP")
PY

PG_ROLE_EXISTS="$(runuser -u postgres -- psql -d postgres -tAc \
  "SELECT 1 FROM pg_roles WHERE rolname='ais_uzmo'")"
PG_DATABASE_EXISTS="$(runuser -u postgres -- psql -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='ais_uzmo'")"
if [ "$PG_ROLE_EXISTS" = 1 ] || [ "$PG_DATABASE_EXISTS" = 1 ]; then
  echo 'Роль или база PostgreSQL ais_uzmo уже существуют.' >&2
  exit 1
fi
unset PG_ROLE_EXISTS PG_DATABASE_EXISTS
```

Если проверка сообщила, что роль или база уже существуют, остановитесь и выясните
происхождение данных.

## 4. Создать пользователя и установить исходный код

```bash
groupadd --system ais
useradd --system --gid ais --home-dir "$APP" \
  --no-create-home --shell /usr/sbin/nologin ais

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
  "$SOURCE/" "$APP/"

printf '%s\n' "$VERSION" > "$APP/RELEASE"
chown -R root:root "$APP"
chmod 0755 "$APP"
chmod 0755 "$APP"/deploy/*.sh

install -d -o ais -g ais -m 2750 "$APP/media" "$APP/logs" "$APP/runtime"
install -d -o root -g root -m 0755 "$APP/staticfiles"
```

Код принадлежит `root`, а служебный пользователь `ais` может записывать данные
только в `media`, `logs` и `runtime`.

## 5. Создать Python-окружение

```bash
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/python" -m pip install \
  --disable-pip-version-check -r "$APP/requirements.txt"
```

Если Python-пакеты выдаются внутренним каталогом `wheelhouse`, сначала проверьте
его `SHA256SUMS`, затем вместо обычной установки используйте:

```bash
cd /путь/к/wheelhouse
sha256sum -c SHA256SUMS

"$APP/.venv/bin/python" -m pip install \
  --disable-pip-version-check --no-index \
  --find-links=/путь/к/wheelhouse \
  -r "$APP/requirements.txt"
```

После любого из двух вариантов обязательно выполните:

```bash
"$APP/.venv/bin/python" -m pip check
chown -R root:ais "$APP/.venv"
chmod -R u=rwX,g=rX,o= "$APP/.venv"
```

## 6. Настроить PostgreSQL

Пароль базы генерируется автоматически и не выводится на экран:

```bash
DB_PASSWORD="$(openssl rand -hex 32)"

printf "CREATE ROLE ais_uzmo LOGIN PASSWORD '%s';\n" "$DB_PASSWORD" | \
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d postgres

runuser -u postgres -- createdb --owner=ais_uzmo ais_uzmo

runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d ais_uzmo <<'SQL'
CREATE EXTENSION IF NOT EXISTS pg_trgm;
REVOKE ALL ON DATABASE ais_uzmo FROM PUBLIC;
GRANT CONNECT, TEMPORARY, CREATE ON DATABASE ais_uzmo TO ais_uzmo;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO ais_uzmo;
SQL

runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d postgres \
  -c "ALTER SYSTEM SET listen_addresses = 'localhost';"
systemctl restart postgresql
```

Проверьте, что PostgreSQL слушает только локальный интерфейс:

```bash
ss -ltn 'sport = :5432'
```

В выводе допустимы только `127.0.0.1:5432` и `[::1]:5432`.

## 7. Настроить Redis

```bash
REDIS_PASSWORD="$(openssl rand -hex 32)"

cp -a /etc/redis/redis.conf /etc/redis/redis.conf.before-ais-uzmo
sed -Ei \
  -e '/^[[:space:]]*#?[[:space:]]*bind[[:space:]]/d' \
  -e '/^[[:space:]]*#?[[:space:]]*protected-mode[[:space:]]/d' \
  -e '\|^[[:space:]]*include[[:space:]]+/etc/redis/ais_uzmo\.conf[[:space:]]*$|d' \
  /etc/redis/redis.conf

printf '\nbind 127.0.0.1 -::1\nprotected-mode yes\ninclude /etc/redis/ais_uzmo.conf\n' \
  >> /etc/redis/redis.conf

umask 077
printf 'requirepass %s\n' "$REDIS_PASSWORD" > /etc/redis/ais_uzmo.conf
chown root:redis /etc/redis/ais_uzmo.conf
chmod 0640 /etc/redis/ais_uzmo.conf
umask 027

systemctl enable redis-server
systemctl restart redis-server

export REDISCLI_AUTH="$REDIS_PASSWORD"
redis-cli -h 127.0.0.1 ping
unset REDISCLI_AUTH
```

Redis должен ответить `PONG`. Команда `ss -ltn 'sport = :6379'` должна показать
только локальные адреса.

## 8. Создать закрытый файл настроек приложения

Следующий блок создаёт рабочий `.env` для HTTP внутри закрытой доверенной сети:

```bash
DJANGO_SECRET_KEY="$(openssl rand -hex 64)"

umask 077
cat > "$APP/.env" <<ENV
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

chown root:ais "$APP/.env"
chmod 0640 "$APP/.env"
unset DB_PASSWORD REDIS_PASSWORD DJANGO_SECRET_KEY
umask 027
```

Не публикуйте `.env` и не отправляйте его вместе с исходным кодом.

## 9. Подготовить Django

Примените миграции:

```bash
cd "$APP"
runuser -u ais -- env DJANGO_SETTINGS_MODULE=config.settings_prod \
  "$APP/.venv/bin/python" manage.py migrate --noinput
```

Создайте начальные справочники и первого администратора. Пароль не отображается и
не сохраняется в `.env`:

```bash
read -r -s -p 'Пароль первого администратора (не менее 12 символов): ' \
  SUPERUSER_PASSWORD
printf '\n'
if [ "${#SUPERUSER_PASSWORD}" -lt 12 ]; then
  unset SUPERUSER_PASSWORD
  echo 'Пароль короче 12 символов.' >&2
  exit 1
fi
read -r -s -p 'Повторите пароль: ' SUPERUSER_PASSWORD_CONFIRM
printf '\n'
if [ "$SUPERUSER_PASSWORD" != "$SUPERUSER_PASSWORD_CONFIRM" ]; then
  unset SUPERUSER_PASSWORD SUPERUSER_PASSWORD_CONFIRM
  echo 'Пароли не совпадают.' >&2
  exit 1
fi
unset SUPERUSER_PASSWORD_CONFIRM
export SUPERUSER_PASSWORD
export SUPERUSER_USERNAME="$ADMIN_USERNAME"
export SUPERUSER_EMAIL="$ADMIN_EMAIL"
export DJANGO_SETTINGS_MODULE=config.settings_prod

runuser \
  --whitelist-environment=DJANGO_SETTINGS_MODULE,SUPERUSER_USERNAME,SUPERUSER_EMAIL,SUPERUSER_PASSWORD \
  -u ais -- "$APP/.venv/bin/python" manage.py seed_initial_data

unset SUPERUSER_PASSWORD SUPERUSER_USERNAME SUPERUSER_EMAIL DJANGO_SETTINGS_MODULE
```

Соберите статические файлы:

```bash
env DJANGO_SETTINGS_MODULE=config.settings_prod \
  "$APP/.venv/bin/python" manage.py collectstatic --noinput --clear

chown -R root:root "$APP/staticfiles"
find "$APP/staticfiles" -type d -exec chmod 0755 {} +
find "$APP/staticfiles" -type f -exec chmod 0644 {} +
```

## 10. Установить systemd-службы и Nginx

Сохраните параметры, которые понадобятся при обновлении:

```bash
install -d -o root -g root -m 0700 /etc/ais_uzmo
printf 'SERVER_NAME=%s\nTRUSTED_CIDR=%s\n' "$SERVER_NAME" "$TRUSTED_CIDR" \
  > /etc/ais_uzmo/deploy.env
chown root:root /etc/ais_uzmo/deploy.env
chmod 0600 /etc/ais_uzmo/deploy.env
```

Установите службы:

```bash
install -o root -g root -m 0644 "$APP/deploy/ais_uzmo.service" \
  /etc/systemd/system/ais_uzmo.service
install -o root -g root -m 0700 "$APP/deploy/backup.sh" \
  /usr/local/sbin/ais-uzmo-backup
install -o root -g root -m 0644 "$APP/deploy/ais-uzmo-backup.service" \
  /etc/systemd/system/ais-uzmo-backup.service
install -o root -g root -m 0644 "$APP/deploy/ais-uzmo-backup.timer" \
  /etc/systemd/system/ais-uzmo-backup.timer
```

Создайте конфигурацию Nginx из шаблона:

```bash
sed \
  -e "s|__SERVER_NAME__|$SERVER_NAME|g" \
  -e "s|__TRUSTED_CIDR__|$TRUSTED_CIDR|g" \
  "$APP/deploy/nginx.conf.template" \
  > /etc/nginx/sites-available/ais_uzmo

chown root:root /etc/nginx/sites-available/ais_uzmo
chmod 0644 /etc/nginx/sites-available/ais_uzmo
ln -s /etc/nginx/sites-available/ais_uzmo \
  /etc/nginx/sites-enabled/ais_uzmo
```

На чистой Ubuntu отключите только штатную ссылку `default`:

```bash
if [ -e /etc/nginx/sites-enabled/default ] || \
   [ -L /etc/nginx/sites-enabled/default ]; then
  if [ -L /etc/nginx/sites-enabled/default ] && \
     [ "$(readlink -- /etc/nginx/sites-enabled/default)" = \
       /etc/nginx/sites-available/default ]; then
    rm /etc/nginx/sites-enabled/default
  else
    echo 'sites-enabled/default не является штатной ссылкой Nginx.' >&2
    exit 1
  fi
fi
```

Если проверка остановила выполнение, не удаляйте найденный файл — сначала
согласуйте конфигурацию Nginx.

Проверьте конфигурацию и запустите приложение:

```bash
systemd-analyze verify /etc/systemd/system/ais_uzmo.service
nginx -t
systemctl daemon-reload
systemctl enable --now ais_uzmo.service
systemctl reload nginx
```

Если на этом этапе или позже возникла ошибка, безопасно остановите автозапуск
приложения и резервного копирования:

```bash
systemctl disable --now ais-uzmo-backup.timer 2>/dev/null || true
systemctl disable --now ais_uzmo.service 2>/dev/null || true
```

Не повторяйте команды создания роли, базы и конфигураций вслепую. Сначала
определите, на каком шаге остановилась установка.

Gunicorn, PostgreSQL и Redis должны слушать только `127.0.0.1`/`::1`. Наружу
открывается только Nginx.

## 11. Включить резервное копирование

```bash
install -d -o root -g root -m 0700 /var/backups/ais_uzmo/daily
systemctl start ais-uzmo-backup.service
test "$(systemctl show -p Result --value ais-uzmo-backup.service)" = success
systemctl enable --now ais-uzmo-backup.timer
```

Результат первого запуска должен быть `success`. Копии создаются ежедневно около
03:30 в `/var/backups/ais_uzmo/daily` и хранятся 14 дней. Они содержат данные,
фотографии, настройки порогов панели и секретные настройки, поэтому доступ к ним
должен быть только у ответственных администраторов. Актуальные копии нужно
переносить на отдельное защищённое хранилище.

## 12. Настроить UFW

Если сетевым экраном управляет другое подразделение, передайте ему требования:

- SSH — только из административной сети;
- HTTP — только из `TRUSTED_CIDR`;
- порты `8000`, `5432` и `6379` наружу не открывать.

Если UFW настраивается на этом сервере, не закрывайте текущий SSH-сеанс. Сначала
добавьте правило для текущего подключения:

```bash
test -n "$SSH_CLIENT_IP"
test -n "$SSH_SERVER_PORT"

ufw allow from "$SSH_CLIENT_IP" to any port "$SSH_SERVER_PORT" proto tcp \
  comment 'Current SSH client'
ufw allow from "$TRUSTED_CIDR" to any port "$SSH_PORT" proto tcp \
  comment 'SSH administration network'
ufw allow from "$TRUSTED_CIDR" to any port 80 proto tcp \
  comment 'AIS UZMO HTTP'
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
ufw status verbose
```

Если одна из двух команд `test` завершилась с ошибкой, UFW не включайте, пока не
определите адрес клиента и серверный порт SSH вручную.

## 13. Выполнить итоговую проверку

```bash
bash "$APP/deploy/check.sh"
```

Последняя строка должна быть:

```text
Все проверки пройдены.
```

После этого откройте `http://SERVER_NAME/` с компьютера в доверенной сети и
проверьте:

1. вход первого администратора;
2. открытие основных разделов;
3. создание и удаление контрольной заявки;
4. загрузку, открытие и удаление контрольной фотографии.

Перезагрузите сервер и повторите проверку:

```bash
reboot
```

После повторного входа:

```bash
sudo -i
bash /srv/ais_uzmo/deploy/check.sh
```

## 14. Если требуется HTTPS

Описанный релиз поддерживает штатную установку по HTTP только внутри утверждённой
защищённой сети. Нельзя просто включить редирект в `.env` или вручную дописать TLS
в Nginx: текущие `check.sh` и `update.sh` рассчитаны на HTTP, а обновление заново
формирует конфигурацию Nginx из шаблона.

Для контура, где обязателен HTTPS, до установки запросите у разработчика
согласованный комплект с поддержкой сертификата одновременно в шаблоне Nginx,
проверке, обновлении и настройках Django. Сертификат и сетевые правила выдаёт ИЦ.
Самоподписанный сертификат без доверия на рабочих станциях использовать не
следует.

## 15. Диагностика

```bash
bash /srv/ais_uzmo/deploy/check.sh
systemctl status ais_uzmo.service --no-pager
journalctl -u ais_uzmo.service -b -n 200 --no-pager
systemctl status ais-uzmo-backup.service --no-pager
journalctl -u ais-uzmo-backup.service -n 100 --no-pager
nginx -t
ss -ltnp
df -h /srv /var
ufw status verbose
```

Не используйте `chmod 777`, не удаляйте `.env`, `media`, `runtime`, PostgreSQL или
резервные копии для попытки «починить» установку. В обращение разработчику
передавайте вывод проверок и журналов, но не содержимое `.env`, дампы базы и
фотографии.

Обновление и штатное сопровождение после установки описаны в
[`MAINTENANCE.md`](MAINTENANCE.md).
