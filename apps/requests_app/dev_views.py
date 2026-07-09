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


def _int_or(raw, default):
    raw = (raw or "").strip()
    return int(raw) if raw.isdigit() else default


@admin_required
@require_http_methods(["GET", "POST"])
def dev_seed_data(request):
    output = None
    form_values = {
        "organs": "",
        "include_children": False,
        "requests_per_table": 4,
        "snapshots": 3,
        "days_span": 180,
        "seed": "",
        "clear": False,
    }

    if request.method == "POST":
        organs_raw = request.POST.get("organs", "").strip()
        organs = int(organs_raw) if organs_raw.isdigit() else None
        include_children = "include_children" in request.POST
        requests_per_table = _int_or(request.POST.get("requests_per_table"), 4)
        snapshots = _int_or(request.POST.get("snapshots"), 3)
        days_span = _int_or(request.POST.get("days_span"), 180)
        seed_raw = request.POST.get("seed", "").strip()
        seed = int(seed_raw) if seed_raw.isdigit() else None
        clear = "clear" in request.POST

        form_values.update(
            organs=organs_raw,
            include_children=include_children,
            requests_per_table=requests_per_table,
            snapshots=snapshots,
            days_span=days_span,
            seed=seed_raw,
            clear=clear,
        )

        buffer = io.StringIO()
        try:
            call_command(
                "seed_demo_data",
                organs=organs,
                include_children=include_children,
                requests_per_table=requests_per_table,
                snapshots=snapshots,
                days_span=days_span,
                seed=seed,
                clear=clear,
                stdout=buffer,
            )
        except Exception as exc:
            messages.error(request, f"Не удалось сгенерировать данные: {exc}")
        else:
            output = buffer.getvalue()
            messages.success(request, "Демо-данные сгенерированы.")

    return render(request, "dev_tools/seed_data.html", {"output": output, "form_values": form_values})
