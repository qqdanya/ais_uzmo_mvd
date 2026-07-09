"""Dev-only tooling. Never mounted in config.urls unless settings.DEBUG is True
(config.settings_prod always sets DEBUG = False), so this has no production
attack surface regardless of what it does here.
"""
import io

from django.contrib import messages
from django.core.management import call_command
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.accounts.views import admin_required


@admin_required
@require_http_methods(["GET", "POST"])
def dev_seed_data(request):
    output = None
    if request.method == "POST":
        organs_raw = request.POST.get("organs", "").strip()
        organs = int(organs_raw) if organs_raw.isdigit() else None
        skip_photos = "skip_photos" in request.POST
        clear = "clear" in request.POST

        buffer = io.StringIO()
        try:
            call_command("seed_demo_data", organs=organs, skip_photos=skip_photos, clear=clear, stdout=buffer)
        except Exception as exc:
            messages.error(request, f"Не удалось сгенерировать данные: {exc}")
        else:
            output = buffer.getvalue()
            messages.success(request, "Демо-данные сгенерированы.")

    return render(
        request,
        "dev_tools/seed_data.html",
        {
            "output": output,
            "posted_organs": request.POST.get("organs", "") if request.method == "POST" else "",
            "posted_skip_photos": "skip_photos" in request.POST if request.method == "POST" else True,
            "posted_clear": "clear" in request.POST if request.method == "POST" else False,
        },
    )
