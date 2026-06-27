import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("directory", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("create", "Создание"), ("update", "Изменение"), ("delete", "Удаление"), ("login", "Вход"), ("logout", "Выход")], db_index=True, max_length=20, verbose_name="действие")),
                ("model_name", models.CharField(blank=True, db_index=True, max_length=120, verbose_name="модель")),
                ("object_id", models.CharField(blank=True, max_length=64, verbose_name="ID объекта")),
                ("object_repr", models.CharField(blank=True, max_length=255, verbose_name="объект")),
                ("old_values", models.JSONField(blank=True, null=True, verbose_name="старые значения")),
                ("new_values", models.JSONField(blank=True, null=True, verbose_name="новые значения")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP")),
                ("user_agent", models.TextField(blank=True, verbose_name="User-Agent")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="создано")),
                ("territorial_organ", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="directory.territorialorgan", verbose_name="территориальный орган")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name="пользователь")),
            ],
            options={"verbose_name": "запись аудита", "verbose_name_plural": "журнал действий", "ordering": ("-created_at",)},
        ),
        migrations.AddIndex(model_name="auditlog", index=models.Index(fields=["action", "model_name", "created_at"], name="audit_audit_action_dd125e_idx")),
    ]
