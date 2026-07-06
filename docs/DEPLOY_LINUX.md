# Развёртывание на Linux-сервере

Рекомендуемая схема для тестового и боевого сервера:

```text
Ubuntu/Debian + PostgreSQL + Gunicorn + Nginx + HTTPS
```

Все команды ниже приведены для Ubuntu/Debian. Имена пользователя, базы, домена и путей можно изменить под инфраструктуру организации.

## 1. Подготовка сервера

Подключиться к серверу по SSH:

```bash
ssh root@SERVER_IP
```

Обновить систему и установить пакеты:

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip git nginx postgresql postgresql-contrib build-essential libpq-dev
```

## 2. Системный пользователь

Не рекомендуется запускать приложение от `root`.

```bash
adduser ais
usermod -aG sudo ais
```

Дальше работать от пользователя `ais` там, где это указано.

## 3. PostgreSQL

Создать базу и пользователя:

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE uzmo_db;
CREATE USER uzmo_user WITH PASSWORD 'CHANGE_ME_STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE uzmo_db TO uzmo_user;
\c uzmo_db
GRANT ALL ON SCHEMA public TO uzmo_user;
\q
```

## 4. Получение проекта

```bash
sudo -iu ais
mkdir -p ~/apps
cd ~/apps
git clone <PRIVATE_REPO_URL> ais_uzmo
cd ~/apps/ais_uzmo
```

Для приватного GitHub-репозитория на сервере обычно создают отдельный SSH deploy key с доступом только на чтение.

## 5. Виртуальное окружение и зависимости

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 6. Production `.env`

```bash
cp .env.production.example .env
nano .env
```

Пример значений:

```env
SECRET_KEY=long-random-secret
DEBUG=False
ALLOWED_HOSTS=example.ru,www.example.ru
CSRF_TRUSTED_ORIGINS=https://example.ru,https://www.example.ru
DATABASE_URL=postgres://uzmo_user:CHANGE_ME_STRONG_PASSWORD@127.0.0.1:5432/uzmo_db
MEDIA_ROOT=media

SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True

SUPERUSER_USERNAME=admin
SUPERUSER_EMAIL=admin@example.com
SUPERUSER_PASSWORD=CHANGE_ME_BEFORE_FIRST_SEED
```

Реальный `.env` нельзя коммитить и передавать вместе с архивом проекта.

Для production-настроек нужен HTTPS. Если сервер временно проверяется только по IP без HTTPS, используйте отдельный тестовый стенд и не считайте такую схему боевой.

## 7. Миграции, static и начальные данные

```bash
export DJANGO_SETTINGS_MODULE=config.settings_prod

python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py seed_initial_data
python manage.py test --parallel 4
python scripts/refactor_static_check.py
```

После первичного создания руководителя рекомендуется удалить `SUPERUSER_PASSWORD` из серверного `.env` или заменить его на нерабочее значение.

## 8. Проверка Gunicorn вручную

```bash
source .venv/bin/activate
gunicorn config.wsgi:application --bind 127.0.0.1:8000
```

В другом SSH-сеансе:

```bash
curl http://127.0.0.1:8000/
```

Если ответ приходит, остановить ручной Gunicorn через `Ctrl+C` и настроить systemd.

## 9. systemd-сервис

Создать файл:

```bash
sudo nano /etc/systemd/system/ais_uzmo.service
```

Содержимое:

```ini
[Unit]
Description=AIS UZMO Django application
After=network.target postgresql.service

[Service]
User=ais
Group=www-data
WorkingDirectory=/home/ais/apps/ais_uzmo
Environment="DJANGO_SETTINGS_MODULE=config.settings_prod"
ExecStart=/home/ais/apps/ais_uzmo/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Запуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ais_uzmo
sudo systemctl start ais_uzmo
sudo systemctl status ais_uzmo
```

Логи:

```bash
journalctl -u ais_uzmo -f
```

## 10. Nginx

Создать конфигурацию:

```bash
sudo nano /etc/nginx/sites-available/ais_uzmo
```

Пример:

```nginx
server {
    listen 80;
    server_name example.ru www.example.ru;

    client_max_body_size 100M;

    location /static/ {
        alias /home/ais/apps/ais_uzmo/staticfiles/;
    }

    location /media/ {
        alias /home/ais/apps/ais_uzmo/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Активировать сайт:

```bash
sudo ln -s /etc/nginx/sites-available/ais_uzmo /etc/nginx/sites-enabled/ais_uzmo
sudo nginx -t
sudo systemctl reload nginx
```

## 11. HTTPS

Для публичного домена можно использовать Certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d example.ru -d www.example.ru
```

После включения HTTPS проверить, что в `.env` указано:

```env
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
CSRF_TRUSTED_ORIGINS=https://example.ru,https://www.example.ru
```

## 12. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

## 13. Проверка после запуска

Пройти `docs/QA_CHECKLIST.md`.

Минимально проверить:

1. Вход в систему.
2. `/control/`.
3. Создание и редактирование заявки.
4. Загрузка и просмотр фотографии.
5. Прикрепление фотографии к заявке.
6. Экспорт данных.
7. Журнал действий.
8. Доступы оператора и наблюдателя.

## 14. Обновление после нового коммита

```bash
sudo -iu ais
cd ~/apps/ais_uzmo
source .venv/bin/activate

git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py test --parallel 4

sudo systemctl restart ais_uzmo
```

Подробности по сопровождению: `docs/MAINTENANCE.md`.
