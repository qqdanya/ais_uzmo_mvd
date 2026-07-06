# Чеклист перед развёртыванием

Краткий список проверок перед тестовым или боевым запуском. Подробная Linux-инструкция находится в `docs/DEPLOY_LINUX.md`, локальный запуск на Windows — в `docs/RUN_WINDOWS.md`.

## 1. Окружение

- Создано виртуальное окружение `.venv`.
- Зависимости установлены из lock-файла:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

- Реальный `.env` создан из `.env.production.example` и не попадает в Git.
- Для сервера используется `DEBUG=False`.

## 2. Обязательные production-переменные

```env
SECRET_KEY=...
DEBUG=False
ALLOWED_HOSTS=example.ru,www.example.ru
CSRF_TRUSTED_ORIGINS=https://example.ru,https://www.example.ru
DATABASE_URL=postgres://uzmo_user:strong-password@127.0.0.1:5432/uzmo_db
MEDIA_ROOT=media
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

## 3. PostgreSQL

Production должен использовать PostgreSQL через `DATABASE_URL`. SQLite подходит только для локальной разработки и тестов.

Проверить:

- база создана;
- пользователь базы имеет права на базу и schema `public`;
- `migrate --settings=config.settings_prod` проходит без ошибок;
- `seed_initial_data --settings=config.settings_prod` выполнен, если нужны начальные справочники.

## 4. Команды проверки

```bash
python manage.py check --deploy --settings=config.settings_prod
python manage.py makemigrations --check --dry-run --settings=config.settings_prod
python manage.py migrate --settings=config.settings_prod
python manage.py collectstatic --noinput --settings=config.settings_prod
python manage.py test --parallel 4
python scripts/refactor_static_check.py
```

## 5. Static и vendor-файлы

Перед запуском обязательно выполнить:

```bash
python manage.py collectstatic --noinput --settings=config.settings_prod
```

Проект использует локальные vendor-файлы в `static/vendor/`, а не CDN. Подробности в `docs/VENDOR_STATIC.md`.

Проверить наличие:

```text
static/vendor/bootstrap/bootstrap.min.css
static/vendor/bootstrap/bootstrap.bundle.min.js
static/vendor/bootstrap-icons/bootstrap-icons.css
static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff
static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2
static/vendor/htmx/htmx.min.js
static/vendor/chartjs/chart.umd.min.js
```

## 6. Media files

Фотографии находятся в `MEDIA_ROOT`.

Для тестового стенда media можно отдавать через Nginx напрямую. Если доступ к файлам должен строго зависеть от роли или территориального органа, безопасный production-вариант — отдавать файлы через Django-проверку прав и Nginx `X-Accel-Redirect`.

## 7. HTTPS и cookies

В production-настройках используются защищённые cookies:

```text
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
```

Поэтому для полноценного production нужен HTTPS. Если HTTPS завершается на Nginx, должен прокидываться заголовок:

```text
X-Forwarded-Proto: https
```

## 8. Файлы, которых не должно быть в релизе

```text
.env
.env.local
.env.prod
db.sqlite3
*.sqlite3
media/
staticfiles/
__pycache__/
*.pyc
.venv/
venv/
env/
.pytest_cache/
.coverage
htmlcov/
*.log
*.zip
dashboard_thresholds.json
dashboard_thresholds.json.tmp
.idea/
.vscode/
```

## 9. Dependency lock

В проекте используются:

```text
requirements.in   прямые зависимости проекта
requirements.txt  lock-файл с точными версиями, созданный через pip-compile
```

На сервере устанавливать зависимости только так:

```bash
pip install -r requirements.txt
```

Для обновления lock-файла разработчик использует:

```bash
pip install pip-tools
pip-compile requirements.in --output-file=requirements.txt
pip install -r requirements.txt
python manage.py test --parallel 4
```


## 10. Smoke-test в браузере

После запуска пройти `docs/QA_CHECKLIST.md`. Минимально проверить:

1. Вход под руководителем.
2. `/control/` и основные разделы административной панели.
3. Создание и редактирование заявки.
4. Прикрепление фотографий к заявке.
5. Экспорт данных.
6. Журнал действий.
7. Доступы оператора и наблюдателя.
8. `/admin/` доступен только уполномоченному пользователю.
