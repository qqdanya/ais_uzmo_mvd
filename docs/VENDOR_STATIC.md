# Локальные frontend-библиотеки

Проект не зависит от CDN в рабочем интерфейсе. Bootstrap, Bootstrap Icons, HTMX
и Chart.js хранятся локально в `static/vendor/` и входят в проверенный релизный
архив.

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

Эти файлы должны оставаться в репозитории. Не удаляйте `static/vendor/` перед
сборкой релиза и не заменяйте vendor-файлы вручную на установленном сервере.

## Обновление vendor-файлов разработчиком

Единственный штатный загрузчик — `scripts/download_vendor_static.py`. Это
разработческий файл: его запускают только в рабочей копии репозитория, а не на
сервере ИЦ.

При наличии разрешённого доступа в Интернет из корня проекта выполните:

```bash
python scripts/download_vendor_static.py
```

Скрипт загружает все перечисленные библиотеки, включая Bootstrap Icons.
`scripts/download_bootstrap_icons.py` отдельно не запускайте: он не является
вторым штатным способом подготовки релиза.

После загрузки разработчик должен просмотреть изменения, выполнить проверки ниже,
закоммитить файлы и собрать новый релиз через `deploy/release.sh`. Сотрудники ИЦ
получают уже готовый архив и проверяют его общий `SHA256SUMS`; скачивать frontend-
библиотеки из Интернета при установке или обновлении не нужно.

## Проверка

```bash
python manage.py collectstatic --dry-run --noinput
python scripts/refactor_static_check.py
python manage.py test --parallel 4
```

Проверки должны пройти до создания тега и релизного архива.

В браузере проверить:

- стили Bootstrap применяются;
- модальные окна открываются;
- Bootstrap Icons отображаются;
- HTMX-запросы работают;
- график оперативной сводки отображается.
