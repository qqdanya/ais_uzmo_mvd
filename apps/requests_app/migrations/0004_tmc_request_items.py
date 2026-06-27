import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


STATUS = [
    ("new", "Новая"),
    ("in_work", "В работе"),
    ("done", "Исполнена"),
    ("rejected", "Отклонена"),
]


def migrate_tmc_needs(apps, schema_editor):
    TmcNeed = apps.get_model("requests_app", "TmcNeed")
    TmcRequest = apps.get_model("requests_app", "TmcRequest")
    TmcRequestItem = apps.get_model("requests_app", "TmcRequestItem")

    for need in TmcNeed.objects.all().iterator():
        request_date = need.due_date or need.created_at.date()
        request_obj = TmcRequest.objects.create(
            territorial_organ_id=need.territorial_organ_id,
            created_by_id=need.created_by_id,
            updated_by_id=need.updated_by_id,
            is_deleted=need.is_deleted,
            comment=need.comment,
            request_number=f"ТМЦ-{need.pk}",
            request_date=request_date,
            status=need.status,
            due_date=need.due_date,
        )
        TmcRequest.objects.filter(pk=request_obj.pk).update(created_at=need.created_at, updated_at=need.updated_at)
        TmcRequestItem.objects.create(
            request_id=request_obj.pk,
            name=need.name,
            quantity=max(need.quantity, 1),
            unit=need.unit,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("requests_app", "0003_alter_buildingrepairrequest_repair_object_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TmcRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="обновлено")),
                ("is_deleted", models.BooleanField(db_index=True, default=False, verbose_name="удалено")),
                ("comment", models.TextField(blank=True, verbose_name="комментарий")),
                ("request_number", models.CharField(max_length=80, verbose_name="номер заявки")),
                ("request_date", models.DateField(verbose_name="дата заявки")),
                ("status", models.CharField(choices=STATUS, db_index=True, default="new", max_length=20, verbose_name="исполнение заявки")),
                ("due_date", models.DateField(blank=True, null=True, verbose_name="срок исполнения")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL, verbose_name="создал")),
                ("territorial_organ", models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(class)s_items", to="directory.territorialorgan", verbose_name="территориальный орган")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL, verbose_name="обновил")),
            ],
            options={
                "verbose_name": "заявка ТМЦ",
                "verbose_name_plural": "Заявки ТМЦ",
                "ordering": ("-request_date", "-created_at"),
            },
        ),
        migrations.CreateModel(
            name="TmcRequestItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180, verbose_name="наименование")),
                ("quantity", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)], verbose_name="количество")),
                ("unit", models.CharField(default="шт.", max_length=40, verbose_name="единица измерения")),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="requests_app.tmcrequest", verbose_name="заявка")),
            ],
            options={
                "verbose_name": "позиция заявки ТМЦ",
                "verbose_name_plural": "Позиции заявки ТМЦ",
                "ordering": ("id",),
            },
        ),
        migrations.AddIndex(
            model_name="tmcrequest",
            index=models.Index(fields=["territorial_organ", "request_date", "status"], name="requests_ap_territo_73a786_idx"),
        ),
        migrations.RunPython(migrate_tmc_needs, migrations.RunPython.noop),
    ]
