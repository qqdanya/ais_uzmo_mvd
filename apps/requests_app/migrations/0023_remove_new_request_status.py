from django.db import migrations, models


REQUEST_MODELS = [
    "TmcRequest",
    "VehicleRepairRequest",
    "VehicleFuelRequest",
    "FireDepartmentRequest",
    "AntiTerrorMeasure",
    "CitsiziEquipment",
    "BuildingRepairRequest",
]


ACTIVE_STATUS_CHOICES = [
    ("in_work", "В работе"),
    ("done", "Исполнена"),
    ("rejected", "Отклонена"),
]


def remove_new_status(apps, schema_editor):
    for model_name in REQUEST_MODELS:
        model = apps.get_model("requests_app", model_name)
        model.objects.filter(status="new").update(status="in_work")

    history = apps.get_model("requests_app", "RequestStatusHistory")
    history.objects.filter(old_status="new").update(old_status="in_work")
    history.objects.filter(new_status="new").update(new_status="in_work")


class Migration(migrations.Migration):
    dependencies = [
        ("requests_app", "0022_default_requests_to_in_work"),
    ]

    operations = [
        migrations.RunPython(remove_new_status, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="tmcrequest",
            name="status",
            field=models.CharField(choices=ACTIVE_STATUS_CHOICES, db_index=True, default="in_work", max_length=20, verbose_name="исполнение заявки"),
        ),
        migrations.AlterField(
            model_name="vehiclerepairrequest",
            name="status",
            field=models.CharField(choices=ACTIVE_STATUS_CHOICES, db_index=True, default="in_work", max_length=20, verbose_name="исполнение заявки"),
        ),
        migrations.AlterField(
            model_name="vehiclefuelrequest",
            name="status",
            field=models.CharField(choices=ACTIVE_STATUS_CHOICES, db_index=True, default="in_work", max_length=20, verbose_name="исполнение заявки"),
        ),
        migrations.AlterField(
            model_name="firedepartmentrequest",
            name="status",
            field=models.CharField(choices=ACTIVE_STATUS_CHOICES, db_index=True, default="in_work", max_length=20, verbose_name="исполнение заявки"),
        ),
        migrations.AlterField(
            model_name="antiterrormeasure",
            name="status",
            field=models.CharField(choices=ACTIVE_STATUS_CHOICES, db_index=True, default="in_work", max_length=20, verbose_name="исполнение"),
        ),
        migrations.AlterField(
            model_name="citsiziequipment",
            name="status",
            field=models.CharField(choices=ACTIVE_STATUS_CHOICES, db_index=True, default="in_work", max_length=20, verbose_name="исполнение"),
        ),
        migrations.AlterField(
            model_name="buildingrepairrequest",
            name="status",
            field=models.CharField(choices=ACTIVE_STATUS_CHOICES, db_index=True, default="in_work", max_length=20, verbose_name="исполнение заявки"),
        ),
        migrations.AlterField(
            model_name="requeststatushistory",
            name="old_status",
            field=models.CharField(blank=True, choices=ACTIVE_STATUS_CHOICES, max_length=20, null=True, verbose_name="предыдущий статус"),
        ),
        migrations.AlterField(
            model_name="requeststatushistory",
            name="new_status",
            field=models.CharField(choices=ACTIVE_STATUS_CHOICES, max_length=20, verbose_name="новый статус"),
        ),
    ]
