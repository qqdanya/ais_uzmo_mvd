from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requests_app", "0005_tmc_status_history"),
    ]

    operations = [
        migrations.AlterField(
            model_name="citsiziequipment",
            name="due_date",
            field=models.DateField(blank=True, null=True, verbose_name="дата исполнения"),
        ),
        migrations.AlterField(
            model_name="tmcneed",
            name="due_date",
            field=models.DateField(blank=True, null=True, verbose_name="дата исполнения"),
        ),
        migrations.AlterField(
            model_name="tmcrequest",
            name="due_date",
            field=models.DateField(blank=True, null=True, verbose_name="дата исполнения"),
        ),
        migrations.AddField(
            model_name="tmcrequeststatushistory",
            name="completed_at",
            field=models.DateField(blank=True, null=True, verbose_name="дата исполнения"),
        ),
    ]
