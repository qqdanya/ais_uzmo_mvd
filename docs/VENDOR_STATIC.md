# Vendor static assets

The project uses pinned frontend vendor versions:

- Bootstrap `5.3.3`
- Bootstrap Icons `1.11.3`
- HTMX `1.9.12`
- Chart.js `4.4.3`

For production, the frontend runtime libraries are served locally from `static/vendor/` so the application does not depend on CDN availability.

## Localized assets

These files are expected in the repository/static tree:

```text
static/vendor/bootstrap/bootstrap.min.css
static/vendor/bootstrap/bootstrap.bundle.min.js
static/vendor/bootstrap-icons/bootstrap-icons.css
static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff
static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2
static/vendor/htmx/htmx.min.js
static/vendor/chartjs/chart.umd.min.js
```

The templates use these local paths via `{% static %}`.

## Download pinned assets

From the project root, with internet access, run:

```bash
python scripts/download_vendor_static.py
python scripts/download_bootstrap_icons.py
```

The scripts download the exact pinned versions into `static/vendor/`.

## Verification

Run:

```bash
python manage.py collectstatic --dry-run --noinput
python manage.py test
```

Also check in the browser:

- Bootstrap modals open;
- HTMX requests work;
- the admin summary chart renders;
- Bootstrap Icons are visible.
