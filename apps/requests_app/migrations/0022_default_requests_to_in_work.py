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


def move_new_requests_to_in_work(apps, schema_editor):
    for model_name in REQUEST_MODELS:
        model = apps.get_model("requests_app", model_name)
        model.objects.filter(status="new").update(status="in_work")


class Migration(migrations.Migration):
    dependencies = [
        ("requests_app", "0021_populate_tmc_products"),
    ]

    operations = [
        migrations.RunPython(move_new_requests_to_in_work, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="tmcrequest",
            name="status",
            field=models.CharField(choices=[("new", "Новая"), ("in_work", "В работе"), ("done", "Исполнена"), ("rejected", "Отклонена")], db_index=True, default="in_work", max_length=20, verbose_name="исполнение заявки"),
        ),
        migrations.AlterField(
            model_name="vehiclerepairrequest",
            name="status",
            field=models.CharField(choices=[("new", "Новая"), ("in_work", "В работе"), ("done", "Исполнена"), ("rejected", "Отклонена")], db_index=True, default="in_work", max_length=20, verbose_name="исполнение заявки"),
        ),
        migrations.AlterField(
            model_name="vehiclefuelrequest",
            name="status",
            field=models.CharField(choices=[("new", "Новая"), ("in_work", "В работе"), ("done", "Исполнена"), ("rejected", "Отклонена")], db_index=True, default="in_work", max_length=20, verbose_name="исполнение заявки"),
        ),
        migrations.AlterField(
            model_name="firedepartmentrequest",
            name="status",
            field=models.CharField(choices=[("new", "Новая"), ("in_work", "В работе"), ("done", "Исполнена"), ("rejected", "Отклонена")], db_index=True, default="in_work", max_length=20, verbose_name="исполнение заявки"),
        ),
        migrations.AlterField(
            model_name="antiterrormeasure",
            name="status",
            field=models.CharField(choices=[("new", "Новая"), ("in_work", "В работе"), ("done", "Исполнена"), ("rejected", "Отклонена")], db_index=True, default="in_work", max_length=20, verbose_name="исполнение"),
        ),
        migrations.AlterField(
            model_name="citsiziequipment",
            name="status",
            field=models.CharField(choices=[("new", "Новая"), ("in_work", "В работе"), ("done", "Исполнена"), ("rejected", "Отклонена")], db_index=True, default="in_work", max_length=20, verbose_name="исполнение"),
        ),
        migrations.AlterField(
            model_name="buildingrepairrequest",
            name="status",
            field=models.CharField(choices=[("new", "Новая"), ("in_work", "В работе"), ("done", "Исполнена"), ("rejected", "Отклонена")], db_index=True, default="in_work", max_length=20, verbose_name="исполнение заявки"),
        ),
    ]
