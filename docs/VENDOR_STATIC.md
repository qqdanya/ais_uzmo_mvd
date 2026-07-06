# Локальные frontend-библиотеки

Проект не зависит от CDN в рабочем интерфейсе. Bootstrap, Bootstrap Icons, HTMX и Chart.js хранятся локально в `static/vendor/`.

## Зафиксированные версии

| Библиотека | Версия |
|---|---:|
| Bootstrap | 5.3.3 |
| Bootstrap Icons | 1.11.3 |
| HTMX | 1.9.12 |
| Chart.js | 4.4.3 |

## Ожидаемые файлы

```text
static/vendor/bootstrap/bootstrap.min.css
static/vendor/bootstrap/bootstrap.bundle.min.js
static/vendor/bootstrap-icons/bootstrap-icons.css
static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff
static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2
static/vendor/htmx/htmx.min.js
static/vendor/chartjs/chart.umd.min.js
```

Эти файлы должны оставаться в репозитории. Не удалять `static/vendor/` перед развёртыванием.

## Повторная загрузка vendor-файлов

При наличии доступа в интернет из корня проекта выполнить:

```bash
python scripts/download_vendor_static.py
python scripts/download_bootstrap_icons.py
```

Скрипты скачивают именно те версии, которые ожидает проект.

## Проверка

```bash
python manage.py collectstatic --dry-run --noinput
python manage.py test --parallel 4
```

В браузере проверить:

- стили Bootstrap применяются;
- модальные окна открываются;
- Bootstrap Icons отображаются;
- HTMX-запросы работают;
- график оперативной сводки отображается.
