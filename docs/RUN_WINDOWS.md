# Запуск проекта на Windows

Эта инструкция предназначена для локальной проверки, разработки или демонстрационного запуска на рабочей станции Windows.

Для боевого режима рекомендуется Linux-сервер с PostgreSQL, Gunicorn, Nginx и HTTPS. См. `docs/DEPLOY_LINUX.md`.

## 1. Требования

Установить заранее:

- Python 3.12 или новее;
- Git;
- PostgreSQL, если нужно проверить проект не на SQLite, а на PostgreSQL.

Проверить Python:

```powershell
python --version
```

## 2. Получение проекта

```powershell
cd C:\
git clone <PRIVATE_REPO_URL> ais_uzmo_mvd
cd C:\ais_uzmo_mvd
```

Если проект передан архивом, распаковать его, открыть PowerShell в корне проекта и продолжить со следующего шага.

## 3. Виртуальное окружение

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

После активации в начале строки появится `(.venv)`.

## 4. Установка зависимостей

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` — зафиксированный lock-файл. Для обычной установки не нужно запускать `pip-compile`.

## 5. Настройка `.env`

```powershell
copy .env.example .env
notepad .env
```

Минимальный локальный вариант:

```env
SECRET_KEY=local-dev-secret
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=
DATABASE_URL=sqlite:///db.sqlite3
MEDIA_ROOT=media
SUPERUSER_USERNAME=admin
SUPERUSER_EMAIL=admin@example.com
SUPERUSER_PASSWORD=admin12345
```

## 6. Подготовка базы и начальных данных

```powershell
python manage.py migrate
python manage.py seed_initial_data
```

## 7. Проверка проекта

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --parallel 4
python scripts/refactor_static_check.py
```

## 8. Запуск

```powershell
python manage.py runserver 127.0.0.1:8000
```

Открыть в браузере:

```text
http://127.0.0.1:8000/
```

## 9. Локальный запуск с PostgreSQL на Windows

Создать базу и пользователя в PostgreSQL, затем указать в `.env`:

```env
DATABASE_URL=postgres://uzmo_user:strong-password@127.0.0.1:5432/uzmo_db
```

После изменения базы выполнить:

```powershell
python manage.py migrate
python manage.py seed_initial_data
python manage.py test --parallel 4
python manage.py runserver 127.0.0.1:8000
```

## 10. Важно

`runserver` предназначен только для локальной проверки. Не использовать его как production-сервер.

Не коммитить и не передавать:

```text
.env
.venv/
db.sqlite3
media/
staticfiles/
```
