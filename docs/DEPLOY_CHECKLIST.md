# Production deploy checklist

Этот чеклист нужен для тестовой или боевой установки проекта на сервер. Он не заменяет README, а фиксирует порядок безопасной проверки перед запуском.

## 1. Подготовка окружения

1. Создать виртуальное окружение.
2. Установить зависимости:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

3. Скопировать production-шаблон окружения:

```bash
cp .env.production.example .env
```

4. В `.env` обязательно заменить значения:

```env
SECRET_KEY=...
DEBUG=False
ALLOWED_HOSTS=...
DATABASE_URL=postgres://...
CSRF_TRUSTED_ORIGINS=https://...
SECURE_SSL_REDIRECT=True
SUPERUSER_PASSWORD=...
```

Реальный `.env` нельзя коммитить в Git.

## 2. Проверки Django

Перед запуском сервера выполнить:

```bash
python manage.py check --deploy --settings=config.settings_prod
python manage.py makemigrations --check --dry-run --settings=config.settings_prod
python manage.py migrate --settings=config.settings_prod
python manage.py collectstatic --noinput --settings=config.settings_prod
python manage.py test
```

Если `check --deploy` показывает предупреждения, их нужно разобрать до публичного запуска.

## 3. PostgreSQL

Production должен использовать PostgreSQL через `DATABASE_URL`. SQLite подходит только для локальной разработки и тестов.

Проверить:

- база создана;
- пользователь базы имеет права на эту базу;
- `python manage.py migrate --settings=config.settings_prod` проходит без ошибок;
- после миграций работает `python manage.py seed_initial_data --settings=config.settings_prod`, если нужны начальные справочники.

## 4. Static files

В проекте используется WhiteNoise и `CompressedManifestStaticFilesStorage`, поэтому перед запуском обязательно:

```bash
python manage.py collectstatic --noinput --settings=config.settings_prod
```

Проверить, что папка `staticfiles/` создана на сервере и не коммитится в Git.

## 5. Media files

Фотографии находятся в `MEDIA_ROOT`. Для production важно не открыть `media/` без проверки прав, если доступ к фотографиям должен зависеть от территориального органа или роли.

Безопасный вариант для будущего production hardening:

- Django-view проверяет права пользователя;
- Nginx отдаёт файл только после разрешения Django, например через `X-Accel-Redirect`.

Если media временно отдаются напрямую, это нужно считать осознанным ограничением тестового стенда.

## 6. HTTPS и cookies

В `config.settings_prod` включены:

```python
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
```

Это корректно только при настроенном HTTPS. Если HTTPS завершается на Nginx, убедиться, что прокидывается заголовок:

```text
X-Forwarded-Proto: https
```

## 7. Vendor static / CDN-зависимости

Bootstrap CSS/JS, Bootstrap Icons, HTMX и Chart.js подключаются из локального `static/vendor/`. Для Bootstrap Icons обязательно хранить рядом `bootstrap-icons.css` и папку `fonts/`; подробности в `docs/VENDOR_STATIC.md`.

## 8. Файлы, которые не должны попасть в Git

Проверить перед коммитом и деплоем:

```bash
git status --short
```

В репозитории не должно быть:

- `.env`;
- `db.sqlite3`;
- `media/`;
- `staticfiles/`;
- `dashboard_thresholds.json`;
- `dashboard_thresholds.json.tmp`;
- `__pycache__/`;
- `*.pyc`.

## 9. Dependency lock

Текущий `requirements.txt` задаёт совместимые диапазоны зависимостей. Перед настоящим production-релизом желательно зафиксировать точные версии из проверенного окружения:

```bash
python -m pip freeze > requirements.lock.txt
```

После этого установить проект на чистой машине и прогнать:

```bash
pip install -r requirements.lock.txt
python manage.py test
```

Не создавайте lock-файл из непроверенного окружения, где установлены лишние пакеты.

## 10. Smoke-test в браузере

После запуска проверить вручную:

1. Вход под Руководителем.
2. `/control/` и разделы админ-панели.
3. Создание и редактирование заявки.
4. Прикрепление фотографий к заявке.
5. Загрузка фотографии и отказ для поддельного `.jpg`.
6. Журнал действий.
7. `/admin/` доступен только Руководителю.
8. Оператор не видит чужие органы/отделы.
9. Наблюдатель не может изменять данные.


## Vendor static assets

Vendor static details are documented in `docs/VENDOR_STATIC.md`.
