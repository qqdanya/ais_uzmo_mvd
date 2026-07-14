# Запуск проекта на Windows

Эта инструкция предназначена только для локальной проверки, разработки или
демонстрационного запуска на рабочей станции Windows. `runserver` открывается по
HTTP на локальном адресе и не должен быть доступен из внешней сети.

Для серверного запуска используйте `docs/DEPLOY_LINUX.md`. Штатный комплект
развёртывания использует HTTP только внутри утверждённой закрытой сети. Если в
целевом контуре обязателен HTTPS, нужен отдельно подготовленный и проверенный
комплект конфигурации; локальная Windows-инструкция его не заменяет.

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
python -m pip install -r requirements.txt
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

Этот вариант нужен, когда требуется проверить именно PostgreSQL. Миграциям
PostgreSQL требуется расширение `pg_trgm`.

Откройте установленную вместе с PostgreSQL программу **SQL Shell (psql)**,
подключитесь пользователем `postgres` и один раз выполните:

```sql
CREATE ROLE ais_uzmo_local LOGIN PASSWORD 'local-app-change-me';
CREATE DATABASE ais_uzmo_local OWNER ais_uzmo_local;
\connect ais_uzmo_local
CREATE EXTENSION IF NOT EXISTS pg_trgm;

\connect postgres
CREATE ROLE ais_uzmo_test LOGIN PASSWORD 'local-test-change-me' CREATEDB;
CREATE DATABASE ais_uzmo_test OWNER ais_uzmo_test;
\connect ais_uzmo_test
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

`ais_uzmo_local` используется приложением и не получает право создавать базы.
Отдельная роль `ais_uzmo_test` имеет `CREATEDB`, потому что Django создаёт и
удаляет временные базы во время тестов. Эти пароли предназначены только для
локального компьютера; замените их и не используйте в рабочем контуре.

Для запуска приложения укажите в `.env`:

```env
DATABASE_URL=postgresql://ais_uzmo_local:local-app-change-me@127.0.0.1:5432/ais_uzmo_local
```

Подготовьте базу и запустите приложение:

```powershell
python manage.py migrate
python manage.py seed_initial_data
python manage.py runserver 127.0.0.1:8000
```

Для отдельной проверки тестов на PostgreSQL временно задайте подключение тестовой
роли только в текущем окне PowerShell:

```powershell
$env:DATABASE_URL = "postgresql://ais_uzmo_test:local-test-change-me@127.0.0.1:5432/ais_uzmo_test"
python manage.py test --parallel 4
Remove-Item Env:DATABASE_URL
```

Если тесты были прерваны, всё равно удалите переменную командой
`Remove-Item Env:DATABASE_URL`, прежде чем снова запускать приложение.

## 10. Важно

`runserver` предназначен только для локальной проверки по HTTP. Не используйте
его как production-сервер и не публикуйте порт `8000` в локальной или внешней
сети.

Не коммитить и не передавать:

```text
.env
.venv/
db.sqlite3
media/
runtime/
dashboard_thresholds.json
dashboard_thresholds.json.tmp
logs/
staticfiles/
```
