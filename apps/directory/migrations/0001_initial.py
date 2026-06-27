import apps.directory.models
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="Department",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160, unique=True, verbose_name="наименование")),
                ("slug", models.SlugField(max_length=80, unique=True, verbose_name="код")),
                ("order_number", models.PositiveSmallIntegerField(default=0, verbose_name="порядок")),
                ("description", models.TextField(blank=True, verbose_name="описание")),
                ("is_active", models.BooleanField(default=True, verbose_name="активен")),
            ],
            options={"verbose_name": "отдел", "verbose_name_plural": "отделы", "ordering": ("order_number", "name")},
        ),
        migrations.CreateModel(
            name="TerritorialOrgan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255, unique=True, verbose_name="наименование")),
                ("order_number", models.DecimalField(db_index=True, decimal_places=2, max_digits=6, verbose_name="номер")),
                ("description", models.TextField(blank=True, verbose_name="описание")),
                ("is_active", models.BooleanField(default=True, verbose_name="активен")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="children", to="directory.territorialorgan", verbose_name="родитель")),
            ],
            options={"verbose_name": "территориальный орган", "verbose_name_plural": "территориальные органы", "ordering": ("order_number", "name")},
        ),
        migrations.CreateModel(
            name="TerritorialOrganPhoto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="territorial_organs/%Y/%m/", validators=[django.core.validators.FileExtensionValidator(["jpg", "jpeg", "png", "webp"]), apps.directory.models.validate_photo_size], verbose_name="изображение")),
                ("description", models.TextField(blank=True, verbose_name="описание")),
                ("photo_date", models.DateField(blank=True, null=True, verbose_name="дата фотографии")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="обновлено")),
                ("is_deleted", models.BooleanField(db_index=True, default=False, verbose_name="удалено")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_photos", to=settings.AUTH_USER_MODEL, verbose_name="создал")),
                ("territorial_organ", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="photos", to="directory.territorialorgan", verbose_name="территориальный орган")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_photos", to=settings.AUTH_USER_MODEL, verbose_name="обновил")),
            ],
            options={"verbose_name": "фотография территориального органа", "verbose_name_plural": "фотографии территориальных органов", "ordering": ("-photo_date", "-created_at")},
        ),
        migrations.AddIndex(model_name="territorialorgan", index=models.Index(fields=["is_active", "order_number"], name="directory_t_is_acti_8f95c3_idx")),
        migrations.AddIndex(model_name="territorialorganphoto", index=models.Index(fields=["territorial_organ", "is_deleted"], name="directory_t_territo_8c2ca4_idx")),
    ]
