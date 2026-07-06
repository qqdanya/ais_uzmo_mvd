# АИС учёта заявок на материальное обеспечение

Веб-приложение на Django для учёта заявок, сведений о материальной базе, фотографий территориальных органов и действий пользователей.

Система предназначена для внутреннего использования сотрудниками ФКУ ЦХиСО ГУ МВД России по Красноярскому краю.

## Возможности

- Авторизация пользователей и активация учётных записей.
- Разграничение доступа по ролям, территориальным органам и отделам.
- Учёт заявок по направлениям: ТМЦ, транспорт, пожарная безопасность, антитеррор, ЦИТСиЗИ, УОТО.
- Контроль уникальности номера заявки в рамках территориального органа и отдела.
- Статусы заявок: «В работе», «Исполнена», «Отклонена».
- История изменения статусов и журнал действий пользователей.
- Загрузка, хранение, просмотр и прикрепление фотографий к заявкам.
- Экспорт данных и подготовка архивов фотографий.
- Административная панель для управления сотрудниками, правами, справочниками, заявками и настройками.

## Технологии

- Python 3.12+ / Django 5.2
- PostgreSQL для серверного развёртывания
- SQLite для локальной проверки и разработки
- Django Templates, HTMX, Bootstrap 5
- Pillow, openpyxl
- Gunicorn, Nginx, WhiteNoise

## Структура проекта

```text
apps/
  accounts/       административная панель, сотрудники, права, справочники
  audit/          журнал действий пользователей
  directory/      фотографии и папки территориальных органов
  requests_app/   заявки, таблицы, статусы, ТМЦ, экспорт
config/           настройки Django и маршрутизация проекта
docs/             инструкции по запуску, развёртыванию и сопровождению
scripts/          служебные скрипты проверки и загрузки vendor static
templates/        HTML-шаблоны
static/           CSS, JavaScript и локальные vendor-библиотеки
```

## Документация

| Документ | Назначение |
|---|---|
| [`docs/RUN_WINDOWS.md`](docs/RUN_WINDOWS.md) | Локальный запуск и проверка на Windows |
| [`docs/DEPLOY_LINUX.md`](docs/DEPLOY_LINUX.md) | Развёртывание на Linux-сервере с PostgreSQL, Gunicorn и Nginx |
| [`docs/DEPLOY_CHECKLIST.md`](docs/DEPLOY_CHECKLIST.md) | Краткий чеклист перед тестовым или боевым запуском |
| [`docs/QA_CHECKLIST.md`](docs/QA_CHECKLIST.md) | Ручная проверка после установки |
| [`docs/MAINTENANCE.md`](docs/MAINTENANCE.md) | Обновление, бэкапы, логи и сопровождение |
| [`docs/VENDOR_STATIC.md`](docs/VENDOR_STATIC.md) | Локальные Bootstrap, Bootstrap Icons, HTMX и Chart.js |

## Быстрый запуск на Windows для проверки

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py seed_initial_data
python manage.py test --parallel 4
python manage.py runserver 127.0.0.1:8000
```

После запуска открыть:

```text
http://127.0.0.1:8000/
```

Подробная инструкция: [`docs/RUN_WINDOWS.md`](docs/RUN_WINDOWS.md).

## Серверное развёртывание

Рекомендуемый production-вариант:

```text
Linux-сервер + PostgreSQL + Gunicorn + Nginx + HTTPS
```

Основной порядок:

1. Подготовить Linux-сервер и системного пользователя.
2. Установить Python, PostgreSQL, Nginx и системные зависимости.
3. Создать PostgreSQL-базу и пользователя базы.
4. Склонировать проект из приватного репозитория.
5. Создать `.env` из `.env.production.example`.
6. Установить зависимости из `requirements.txt`.
7. Выполнить миграции, начальное заполнение и сбор static-файлов.
8. Настроить Gunicorn через systemd.
9. Настроить Nginx и HTTPS.
10. Пройти чеклист проверки.

Подробная инструкция: [`docs/DEPLOY_LINUX.md`](docs/DEPLOY_LINUX.md).

## Переменные окружения

Для локального запуска используется шаблон:

```text
.env.example
```

Для сервера используется шаблон:

```text
.env.production.example
```

Реальный файл `.env` содержит секреты и не должен попадать в Git или релизный архив.

Минимальные production-переменные:

```env
SECRET_KEY=long-random-secret
DEBUG=False
ALLOWED_HOSTS=example.ru,www.example.ru
CSRF_TRUSTED_ORIGINS=https://example.ru,https://www.example.ru
DATABASE_URL=postgres://uzmo_user:strong-password@127.0.0.1:5432/uzmo_db
MEDIA_ROOT=media
```

## Зависимости

В проекте используются два файла зависимостей:

```text
requirements.in   прямые зависимости проекта
requirements.txt  lock-файл с точными версиями, созданный через pip-compile
```

Для установки на рабочей станции или сервере использовать:

```bash
pip install -r requirements.txt
```

Обновление зависимостей выполняет разработчик в отдельной ветке:

```bash
pip install pip-tools
pip-compile requirements.in --output-file=requirements.txt
pip install -r requirements.txt
python manage.py test --parallel 4
```

## Начальные данные

```bash
python manage.py seed_initial_data
```

Команда создаёт отделы, территориальные органы, подчинённые подразделения и начального руководителя, если в `.env` заданы `SUPERUSER_USERNAME`, `SUPERUSER_EMAIL`, `SUPERUSER_PASSWORD`.

Повторный запуск команды не создаёт дубликаты.

## Основные адреса

| Адрес | Назначение |
|---|---|
| `/` | Пользовательский рабочий экран |
| `/control/` | Административная панель |
| `/audit/` | Журнал действий |
| `/admin/` | Стандартная Django admin-панель |

## Проверка перед передачей или развёртыванием

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --parallel 4
python scripts/refactor_static_check.py
```

Для production-настроек:

```bash
python manage.py check --deploy --settings=config.settings_prod
python manage.py makemigrations --check --dry-run --settings=config.settings_prod
```

## Что нельзя хранить в репозитории и передавать в релизном архиве

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

Миграции Django, `requirements.in`, `requirements.txt`, `.env.example`, `.env.production.example`, `static/vendor/` и документацию удалять не нужно.
