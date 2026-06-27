# Автоматизированная информационная система учета заявок на материальное обеспечение ФКУ ЦХиСО ГУ МВД России по Красноярскому краю

Production-ready Django-приложение для учета заявок и сведений по территориальным органам МВД и направлениям материального обеспечения. Реализованы авторизация, роли, справочники, трехколоночный dashboard, CRUD через HTMX-модалки, soft delete, аудит, экспорт CSV/XLSX и фотографии территориальных органов.

## Технологии

- Python, Django
- Django Templates, HTMX, Bootstrap 5, Bootstrap Icons
- SQLite для разработки
- PostgreSQL через `DATABASE_URL` для production
- Pillow для изображений, openpyxl для Excel

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py seed_initial_data
python manage.py runserver
```

После запуска откройте `http://127.0.0.1:8000/`.

## Переменные окружения

Скопируйте `.env.example` в `.env` и задайте значения:

- `SECRET_KEY` - секретный ключ Django
- `DEBUG` - `True` для разработки, `False` для production
- `ALLOWED_HOSTS` - список host через запятую
- `DATABASE_URL` - например `sqlite:///db.sqlite3` или `postgres://user:pass@host:5432/dbname`
- `CSRF_TRUSTED_ORIGINS` - доверенные HTTPS origins
- `SUPERUSER_USERNAME`, `SUPERUSER_EMAIL`, `SUPERUSER_PASSWORD` - создание суперпользователя seed-командой
- `MEDIA_ROOT` - путь хранения загруженных фотографий

## Начальные данные

```bash
python manage.py seed_initial_data
```

Команда создает 6 отделов, 37 территориальных органов с подчиненными подразделениями и суперпользователя, если заданы env-переменные. Повторный запуск не создает дубликаты.

## Роли

- Администратор: полный доступ, справочники, все CRUD, аудит, Django admin.
- Оператор: создание, изменение и удаление записей по доступным территориальным органам.
- Наблюдатель: просмотр без изменения данных.

Роль и доступные органы настраиваются в Django admin через `UserProfile`.

## Production

Для PostgreSQL задайте:

```env
DEBUG=False
ALLOWED_HOSTS=example.ru
DATABASE_URL=postgres://user:password@db:5432/material_requests
SECRET_KEY=long-random-secret
CSRF_TRUSTED_ORIGINS=https://example.ru
```

В production отдачу `MEDIA_ROOT` лучше вынести на Nginx/S3/объектное хранилище. Static-файлы подготовьте командой:

```bash
set DJANGO_SETTINGS_MODULE=config.settings_prod
python manage.py collectstatic
gunicorn config.wsgi:application
```

## Тесты

```bash
python manage.py test
```

Покрыты базовые сценарии авторизации, доступ к dashboard, CRUD с аудитом, фильтр по типу техники, загрузка/удаление фото и идемпотентность seed-команды.
