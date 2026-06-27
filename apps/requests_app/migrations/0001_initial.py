import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def base_fields():
    return [
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="создано")),
        ("updated_at", models.DateTimeField(auto_now=True, verbose_name="обновлено")),
        ("is_deleted", models.BooleanField(db_index=True, default=False, verbose_name="удалено")),
        ("comment", models.TextField(blank=True, verbose_name="комментарий")),
        ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL, verbose_name="создал")),
        ("territorial_organ", models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(class)s_items", to="directory.territorialorgan", verbose_name="территориальный орган")),
        ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL, verbose_name="обновил")),
    ]


STATUS = [("new", "Новая"), ("in_work", "В работе"), ("done", "Исполнена"), ("rejected", "Отклонена")]


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("directory", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="TmcNeed",
            fields=[
                *base_fields(),
                ("name", models.CharField(max_length=180, verbose_name="наименование")),
                ("quantity", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(0)], verbose_name="количество")),
                ("unit", models.CharField(default="шт.", max_length=40, verbose_name="единица измерения")),
                ("status", models.CharField(choices=STATUS, db_index=True, default="new", max_length=20, verbose_name="статус")),
                ("due_date", models.DateField(blank=True, null=True, verbose_name="срок исполнения")),
            ],
            options={"verbose_name": "потребность ТМЦ", "verbose_name_plural": "Сведения о потребности ТМЦ", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="TransportRequest",
            fields=[
                *base_fields(),
                ("vehicle_name", models.CharField(max_length=180, verbose_name="транспорт")),
                ("request_number", models.CharField(max_length=80, verbose_name="номер заявки")),
                ("request_date", models.DateField(verbose_name="дата заявки")),
                ("work_description", models.TextField(verbose_name="описание работ")),
                ("status", models.CharField(choices=STATUS, db_index=True, default="new", max_length=20, verbose_name="исполнение")),
                ("completed_at", models.DateField(blank=True, null=True, verbose_name="дата исполнения")),
            ],
            options={"verbose_name": "заявка автотранспорта", "verbose_name_plural": "Автотранспортное хозяйство", "ordering": ("-request_date",)},
        ),
        migrations.CreateModel(
            name="FireSafetyRequest",
            fields=[
                *base_fields(),
                ("object_name", models.CharField(max_length=180, verbose_name="объект")),
                ("violation", models.TextField(verbose_name="нарушение/потребность")),
                ("request_number", models.CharField(blank=True, max_length=80, verbose_name="номер заявки")),
                ("request_date", models.DateField(blank=True, null=True, verbose_name="дата заявки")),
                ("status", models.CharField(choices=STATUS, db_index=True, default="new", max_length=20, verbose_name="исполнение")),
            ],
            options={"verbose_name": "пожарная безопасность", "verbose_name_plural": "Отдел пожарной безопасности", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="AntiTerrorMeasure",
            fields=[
                *base_fields(),
                ("object_name", models.CharField(max_length=180, verbose_name="объект")),
                ("measure", models.TextField(verbose_name="мероприятие")),
                ("funding_required", models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(0)], verbose_name="потребность финансирования")),
                ("status", models.CharField(choices=STATUS, db_index=True, default="new", max_length=20, verbose_name="статус")),
            ],
            options={"verbose_name": "антитеррористическая укрепленность", "verbose_name_plural": "Антитеррористическая укрепленность", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="CitsiziEquipment",
            fields=[
                *base_fields(),
                ("equipment_name", models.CharField(max_length=180, verbose_name="наименование")),
                ("equipment_type", models.CharField(choices=[("communication", "Средства связи"), ("organizational", "Организационная техника"), ("computing", "Вычислительная техника"), ("special", "Специальная техника"), ("video", "Видеонаблюдение")], db_index=True, max_length=30, verbose_name="тип техники")),
                ("quantity", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(0)], verbose_name="количество")),
                ("status", models.CharField(choices=STATUS, db_index=True, default="new", max_length=20, verbose_name="исполнение")),
                ("due_date", models.DateField(blank=True, null=True, verbose_name="срок исполнения")),
            ],
            options={"verbose_name": "техника ЦИТСиЗИ", "verbose_name_plural": "По линии ЦИТСиЗИ", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="ServiceHousing",
            fields=[
                *base_fields(),
                ("total_count", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(0)], verbose_name="общее количество")),
                ("used_by_staff", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(0)], verbose_name="используется сотрудниками")),
                ("ready_to_move", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(0)], verbose_name="готово к заселению")),
            ],
            options={"verbose_name": "служебное жилье", "verbose_name_plural": "Служебное жилье", "ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="BuildingRepairRequest",
            fields=[
                *base_fields(),
                ("request_number", models.CharField(max_length=80, verbose_name="номер заявки")),
                ("request_date", models.DateField(verbose_name="дата заявки")),
                ("repair_object", models.CharField(max_length=180, verbose_name="объект ремонта")),
                ("work_description", models.TextField(verbose_name="описание работ")),
                ("status", models.CharField(choices=STATUS, db_index=True, default="new", max_length=20, verbose_name="исполнение заявки")),
                ("completed_at", models.DateField(blank=True, null=True, verbose_name="дата исполнения")),
            ],
            options={"verbose_name": "текущий ремонт", "verbose_name_plural": "Текущий ремонт зданий, помещений, сооружений / Заявка", "ordering": ("-request_date",)},
        ),
        migrations.AddIndex(model_name="tmcneed", index=models.Index(fields=["territorial_organ", "created_at", "status"], name="requests_ap_territo_69ca15_idx")),
        migrations.AddIndex(model_name="citsiziequipment", index=models.Index(fields=["territorial_organ", "equipment_type"], name="requests_ap_territo_d13f13_idx")),
    ]
