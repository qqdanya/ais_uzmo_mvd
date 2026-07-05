# Generated manually for request number uniqueness across request tables.

import re

from django.db import IntegrityError, migrations, models
import django.db.models.deletion


def normalize_request_number(value):
    value = re.sub(r"\s+", " ", str(value or "").strip())
    return value.replace("ё", "е").replace("Ё", "Е").casefold()


def populate_request_number_registry(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Registry = apps.get_model("requests_app", "RequestNumberRegistry")
    model_specs = [
        ("TmcRequest", "tmc"),
        ("VehicleRepairRequest", "transport"),
        ("VehicleFuelRequest", "transport"),
        ("FireDepartmentRequest", "fire"),
        ("AntiTerrorMeasure", "antiterror"),
        ("CitsiziEquipment", "citsizi"),
        ("BuildingRepairRequest", "uoto"),
    ]
    for model_name, department in model_specs:
        Model = apps.get_model("requests_app", model_name)
        content_type, _ = ContentType.objects.get_or_create(app_label="requests_app", model=model_name.lower())
        qs = (
            Model.objects.filter(is_deleted=False)
            .exclude(request_number__isnull=True)
            .exclude(request_number="")
            .order_by("created_at", "pk")
        )
        for obj in qs.iterator():
            request_number = re.sub(r"\s+", " ", str(obj.request_number or "").strip())
            normalized = normalize_request_number(request_number)
            if not normalized:
                continue
            try:
                Registry.objects.create(
                    territorial_organ_id=obj.territorial_organ_id,
                    department=department,
                    request_number=request_number,
                    normalized_request_number=normalized,
                    content_type_id=content_type.pk,
                    object_id=obj.pk,
                )
            except IntegrityError:
                # В старых данных могли быть дубли. Новые сохранения будут проверяться приложением и БД.
                continue


def clear_request_number_registry(apps, schema_editor):
    Registry = apps.get_model("requests_app", "RequestNumberRegistry")
    Registry.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("directory", "0006_remove_territorialorganphotofolder_unique_root_photo_folder_per_organ_and_more"),
        ("requests_app", "0023_remove_new_request_status"),
    ]

    operations = [
        migrations.CreateModel(
            name="RequestNumberRegistry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("department", models.SlugField(db_index=True, max_length=80, verbose_name="отдел")),
                ("request_number", models.CharField(max_length=80, verbose_name="номер заявки")),
                ("normalized_request_number", models.CharField(db_index=True, max_length=80, verbose_name="нормализованный номер")),
                ("object_id", models.PositiveBigIntegerField(verbose_name="ID заявки")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="обновлено")),
                ("content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="contenttypes.contenttype", verbose_name="тип заявки")),
                ("territorial_organ", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="request_number_registry", to="directory.territorialorgan", verbose_name="территориальный орган")),
            ],
            options={
                "verbose_name": "номер заявки",
                "verbose_name_plural": "Реестр номеров заявок",
                "ordering": ("territorial_organ__name", "department", "request_number"),
            },
        ),
        migrations.AddIndex(
            model_name="requestnumberregistry",
            index=models.Index(fields=["territorial_organ", "department", "normalized_request_number"], name="requests_ap_territo_1edceb_idx"),
        ),
        migrations.AddIndex(
            model_name="requestnumberregistry",
            index=models.Index(fields=["content_type", "object_id"], name="requests_ap_content_39b5b7_idx"),
        ),
        migrations.AddConstraint(
            model_name="requestnumberregistry",
            constraint=models.UniqueConstraint(fields=("territorial_organ", "department", "normalized_request_number"), name="unique_request_number_per_organ_department"),
        ),
        migrations.AddConstraint(
            model_name="requestnumberregistry",
            constraint=models.UniqueConstraint(fields=("content_type", "object_id"), name="unique_request_number_registry_object"),
        ),
        migrations.RunPython(populate_request_number_registry, clear_request_number_registry),
    ]
