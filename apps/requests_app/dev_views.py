"""Dev-only tooling. Never mounted in config.urls unless settings.DEBUG is True
(config.settings_prod always sets DEBUG = False), so this has no production
attack surface regardless of what it does here.
"""
import io
import threading
import time

from django.core.cache import cache
from django.core.management import call_command
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.accounts.views import admin_required
from apps.directory.models import TerritorialOrgan

SQLITE_LOCK_RETRY_ATTEMPTS = 3

PROGRESS_CACHE_KEY = "dev_seed_progress"
PROGRESS_CACHE_TIMEOUT = 3600
IDLE_PROGRESS = {"running": False, "done": 0, "total": 0, "finished": False, "output": None, "error": None}


def _int_or(raw, default):
    raw = (raw or "").strip()
    return int(raw) if raw.isdigit() else default


@admin_required
def dev_seed_data(request):
    organs = list(TerritorialOrgan.objects.filter(is_active=True, parent__isnull=True).order_by("order_number", "name"))
    return render(request, "dev_tools/seed_data.html", {"organs": organs})


@admin_required
@require_http_methods(["POST"])
def dev_seed_start(request):
    current = cache.get(PROGRESS_CACHE_KEY) or IDLE_PROGRESS
    if current["running"]:
        return JsonResponse({"error": "Генерация уже выполняется."}, status=409)

    organ_ids = [int(value) for value in request.POST.getlist("organ_ids") if value.isdigit()]
    requests_min = _int_or(request.POST.get("requests_per_table_min"), 3)
    requests_max = max(requests_min, _int_or(request.POST.get("requests_per_table_max"), requests_min))
    snapshots = _int_or(request.POST.get("snapshots"), 3)
    days_span = _int_or(request.POST.get("days_span"), 180)
    seed_raw = request.POST.get("seed", "").strip()
    seed = int(seed_raw) if seed_raw.isdigit() else None
    clear = "clear" in request.POST

    cache.set(PROGRESS_CACHE_KEY, {**IDLE_PROGRESS, "running": True, "total": len(organ_ids) or 1}, PROGRESS_CACHE_TIMEOUT)

    def progress_callback(done, total):
        state = cache.get(PROGRESS_CACHE_KEY) or dict(IDLE_PROGRESS)
        state.update(running=True, done=done, total=total)
        cache.set(PROGRESS_CACHE_KEY, state, PROGRESS_CACHE_TIMEOUT)

    def run():
        # SQLite only ever allows one writer at a time - under just the
        # wrong timing (this background thread plus the browser's own
        # session-save/presence-ping writes) the whole run can still
        # occasionally hit "database is locked" despite the longer busy
        # timeout and WAL mode. Retrying is safe: seed_demo_data's upserts
        # are keyed by request_number/created_by, so re-running after a
        # mid-run failure doesn't create duplicates.
        last_error = None
        for attempt in range(1, SQLITE_LOCK_RETRY_ATTEMPTS + 1):
            buffer = io.StringIO()
            try:
                call_command(
                    "seed_demo_data",
                    organ_ids=organ_ids or None,
                    requests_per_table_min=requests_min,
                    requests_per_table_max=requests_max,
                    snapshots=snapshots,
                    days_span=days_span,
                    seed=seed,
                    clear=clear,
                    progress_callback=progress_callback,
                    stdout=buffer,
                )
            except OperationalError as exc:
                last_error = exc
                if "locked" not in str(exc).lower() or attempt == SQLITE_LOCK_RETRY_ATTEMPTS:
                    break
                time.sleep(1.5 * attempt)
                continue
            except Exception as exc:
                cache.set(PROGRESS_CACHE_KEY, {**IDLE_PROGRESS, "finished": True, "error": str(exc)}, PROGRESS_CACHE_TIMEOUT)
                return
            else:
                state = cache.get(PROGRESS_CACHE_KEY) or dict(IDLE_PROGRESS)
                state.update(running=False, finished=True, done=state.get("total", 1), output=buffer.getvalue())
                cache.set(PROGRESS_CACHE_KEY, state, PROGRESS_CACHE_TIMEOUT)
                return
        cache.set(PROGRESS_CACHE_KEY, {**IDLE_PROGRESS, "finished": True, "error": str(last_error)}, PROGRESS_CACHE_TIMEOUT)

    threading.Thread(target=run, daemon=True).start()
    return JsonResponse({"started": True})


@admin_required
def dev_seed_progress(request):
    # This is polled every 1.5s while a generation is running and never
    # touches request.session itself - but SESSION_SAVE_EVERY_REQUEST=True
    # makes SessionMiddleware re-save it after every request regardless,
    # which is itself a write that can collide with the generator's own
    # writes on SQLite. That write is genuinely pointless here (nothing
    # about the session changed), so skip it instead of fighting the
    # generator for the write lock every single poll.
    request.session.save = lambda *args, **kwargs: None
    state = cache.get(PROGRESS_CACHE_KEY) or IDLE_PROGRESS
    return JsonResponse(state)
