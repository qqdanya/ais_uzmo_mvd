import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


STATUS = [
    ("new", "Новая"),
    ("in_work", "В работе"),
    ("done", "Исполнена"),
    ("rejected", "Отклонена"),
]


def create_initial_history(apps, schema_editor):
    TmcRequest = apps.get_model("requests_app", "TmcRequest")
    TmcRequestStatusHistory = apps.get_model("requests_app", "TmcRequestStatusHistory")

    for request in TmcRequest.objects.all().iterator():
        history = TmcRequestStatusHistory.objects.create(
            request_id=request.pk,
            old_status=None,
            new_status=request.status,
            changed_by_id=request.created_by_id or request.updated_by_id,
            note="Начальное состояние заявки",
        )
        TmcRequestStatusHistory.objects.filter(pk=history.pk).update(changed_at=request.created_at)


class Migration(migrations.Migration):
    dependencies = [
        ("requests_app", "0004_tmc_request_items"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TmcRequestStatusHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("old_status", models.CharField(blank=True, choices=STATUS, max_length=20, null=True, verbose_name="предыдущий статус")),
                ("new_status", models.CharField(choices=STATUS, max_length=20, verbose_name="новый статус")),
                ("changed_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="дата изменения")),
                ("note", models.CharField(blank=True, max_length=255, verbose_name="примечание")),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tmc_status_changes", to=settings.AUTH_USER_MODEL, verbose_name="изменил")),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_history", to="requests_app.tmcrequest", verbose_name="заявка")),
            ],
            options={
                "verbose_name": "изменение статуса заявки ТМЦ",
                "verbose_name_plural": "История статусов заявок ТМЦ",
                "ordering": ("-changed_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="tmcrequeststatushistory",
            index=models.Index(fields=["request", "-changed_at"], name="requests_ap_request_a621ac_idx"),
        ),
        migrations.RunPython(create_initial_history, migrations.RunPython.noop),
    ]
