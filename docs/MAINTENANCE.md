# Сопровождение проекта

Документ предназначен для администратора или специалиста, который сопровождает установленную систему.

## 1. Обновление кода на Linux-сервере

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

После обновления пройти основные пункты из `docs/QA_CHECKLIST.md`.

## 2. Проверка состояния сервиса

```bash
sudo systemctl status ais_uzmo
journalctl -u ais_uzmo -n 100 --no-pager
journalctl -u ais_uzmo -f
```

Проверка Nginx:

```bash
sudo nginx -t
sudo systemctl status nginx
```

## 3. Резервное копирование PostgreSQL

Создать дамп:

```bash
pg_dump -U uzmo_user -h 127.0.0.1 -d uzmo_db -F c -f uzmo_db_$(date +%Y-%m-%d).dump
```

Восстановить дамп в подготовленную базу:

```bash
pg_restore -U uzmo_user -h 127.0.0.1 -d uzmo_db --clean --if-exists uzmo_db_YYYY-MM-DD.dump
```

Команды могут отличаться в зависимости от политики доступа PostgreSQL на сервере.

## 4. Резервное копирование media

Фотографии и загруженные файлы находятся в `MEDIA_ROOT`, обычно:

```text
/home/ais/apps/ais_uzmo/media/
```

Пример архивации:

```bash
tar -czf media_$(date +%Y-%m-%d).tar.gz /home/ais/apps/ais_uzmo/media
```

Для полноценного восстановления нужны и дамп PostgreSQL, и копия `media/`.

После обновления старого проекта до версии с серверными миниатюрами фотографий запустить генерацию thumbnail-файлов для уже загруженных изображений:

```bash
python manage.py generate_photo_thumbnails
```

Если нужно пересоздать миниатюры заново, использовать:

```bash
python manage.py generate_photo_thumbnails --force
```

## 5. Начальные данные

```bash
python manage.py seed_initial_data
```

Команду можно запускать повторно: она не должна создавать дубликаты справочников.

## 6. Изменение production-переменных

Файл `.env` находится в корне проекта на сервере. После изменения `.env` перезапустить сервис:

```bash
sudo systemctl restart ais_uzmo
```

Не хранить в `.env` временный пароль руководителя после первичного создания учётной записи.

## 7. Обновление Python-зависимостей

Обычное обновление сервера использует уже зафиксированный `requirements.txt`:

```bash
pip install -r requirements.txt
```

Обновлять версии зависимостей должен разработчик в отдельной ветке:

```bash
pip install pip-tools
pip-compile requirements.in --output-file=requirements.txt
pip install -r requirements.txt
python manage.py test --parallel 4
```

После успешной проверки обновлённые `requirements.in` и `requirements.txt` коммитятся вместе.

## 8. Static/vendor

Проект использует локальные vendor-файлы в `static/vendor/`. Если требуется заново скачать зафиксированные версии:

```bash
python scripts/download_vendor_static.py
python scripts/download_bootstrap_icons.py
```

Подробности: `docs/VENDOR_STATIC.md`.

## 9. Что не удалять

Не удалять из проекта:

```text
migrations/
requirements.in
requirements.txt
.env.example
.env.production.example
static/vendor/
docs/
scripts/
```

Не хранить в Git и не передавать в релизном архиве:

```text
.env
.venv/
db.sqlite3
media/
staticfiles/
*.log
*.zip
```
