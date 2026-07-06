from __future__ import annotations

from collections import Counter
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw

from apps.accounts.models import UserProfile
from apps.directory.models import Department, TerritorialOrgan, TerritorialOrganPhoto, TerritorialOrganPhotoFolder
from apps.requests_app.models import (
    AntiTerrorMeasure,
    BuildingRepairRequest,
    CitsiziEquipment,
    EquipmentType,
    FireAlarm,
    FireDepartmentRequest,
    FireExtinguisher,
    NeedStatus,
    RequestPhotoLink,
    RequestStatusHistory,
    SecurityAlarm,
    ServiceHousing,
    TmcProduct,
    TmcRequest,
    TmcRequestItem,
    VehicleFuelRequest,
    VehicleInventory,
    VehicleRepairRequest,
    normalize_product_name,
)
from apps.requests_app.services.request_numbers import remove_request_number_registry, sync_request_number_registry
from apps.requests_app.services.statuses import completed_date_field


DEMO_MARKER = "[demo-seed]"
DEMO_PHOTO_FOLDER = "Демо: фотофиксация объектов"
DEMO_USER_USERNAME = "demo_operator"

STATUS_CYCLE = (
    NeedStatus.IN_WORK,
    NeedStatus.DONE,
    NeedStatus.IN_WORK,
    NeedStatus.REJECTED,
    NeedStatus.DONE,
)

TMC_PRODUCTS = (
    ("Бумага офисная А4, 80 г/м²", "пач."),
    ("Картридж лазерный HP 59A", "шт."),
    ("Картридж Canon 725", "шт."),
    ("Папка-регистратор 75 мм", "шт."),
    ("Скоросшиватель картонный", "шт."),
    ("Ручка шариковая синяя", "шт."),
    ("Маркер перманентный черный", "шт."),
    ("Конверт C4", "шт."),
    ("Батарейка AA", "упак."),
    ("Сетевой фильтр 5 розеток", "шт."),
    ("Клавиатура проводная USB", "шт."),
    ("Мышь компьютерная USB", "шт."),
    ("Стул офисный", "шт."),
    ("Кресло операторское", "шт."),
    ("Лампа светодиодная E27", "шт."),
    ("Чистящее средство для оргтехники", "фл."),
)

TMC_SCENARIOS = (
    "для канцелярии дежурной части и регистрации входящей корреспонденции",
    "для рабочих мест подразделения тылового обеспечения",
    "для кабинета участковых уполномоченных и архива материалов",
    "для обеспечения работы следственно-оперативной группы",
    "для замены изношенных расходных материалов в приемной граждан",
)

VEHICLE_REPAIR_SCENARIOS = (
    "Плановое техническое обслуживание служебного автомобиля, замена масла и фильтров.",
    "Диагностика подвески после эксплуатации на грунтовых дорогах района.",
    "Замена аккумуляторной батареи и проверка генератора.",
    "Ремонт тормозной системы патрульного автомобиля.",
    "Шиномонтаж и балансировка колес перед сезонной эксплуатацией.",
)

FUEL_SCENARIOS = (
    "Выделение лимита ГСМ для выездов следственно-оперативной группы.",
    "Обеспечение патрульных маршрутов в выходные и праздничные дни.",
    "ГСМ для доставки сотрудников в отдаленные населенные пункты.",
    "Топливо для служебного транспорта при проведении профилактических мероприятий.",
)

FIRE_REQUEST_SCENARIOS = (
    "Провести проверку пожарных кранов и актуализировать схему эвакуации.",
    "Организовать перезарядку огнетушителей с истекающим сроком эксплуатации.",
    "Устранить замечания по содержанию путей эвакуации в административном здании.",
    "Проверить исправность автоматической пожарной сигнализации в гаражном боксе.",
)

ANTITERROR_SCENARIOS = (
    "Обследование контрольно-пропускного пункта и периметрального ограждения.",
    "Проверка работоспособности тревожной кнопки и системы видеонаблюдения.",
    "Актуализация паспорта безопасности объекта и схемы доступа посетителей.",
    "Контроль устранения замечаний после комиссионного обследования объекта.",
)

CITSIZI_SCENARIOS = {
    EquipmentType.COMMUNICATION: "Замена радиостанций дежурной части и настройка каналов связи.",
    EquipmentType.ORGANIZATIONAL: "Поставка МФУ для канцелярии и приемной граждан.",
    EquipmentType.COMPUTING: "Замена системных блоков на рабочих местах операторов.",
    EquipmentType.SPECIAL: "Обновление специализированного оборудования для служебных задач.",
    EquipmentType.VIDEO: "Дооснащение входной группы IP-камерами видеонаблюдения.",
    EquipmentType.SOUND_ALERT: "Проверка и восстановление системы звукового оповещения.",
}

BUILDING_REPAIR_SCENARIOS = (
    "Текущий ремонт кабинета приема граждан: покраска стен, замена плинтусов.",
    "Локальный ремонт кровли гаражного бокса после протечки.",
    "Восстановление напольного покрытия в коридоре административного здания.",
    "Замена дверного блока и ремонт откосов в помещении дежурной части.",
    "Ремонт санитарного узла и замена поврежденной сантехники.",
)

PHOTO_DESCRIPTIONS = (
    "Фасад административного здания после осмотра",
    "Гаражный бокс и прилегающая территория",
    "Помещение дежурной части для фотофиксации",
)


class Command(BaseCommand):
    help = "Creates realistic demo data across territorial organs and all dashboard tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--organs",
            type=int,
            default=None,
            help="Limit the number of territorial organs to seed. By default all root organs are used.",
        )
        parser.add_argument(
            "--include-children",
            action="store_true",
            help="Also seed child/subordinate territorial units. Dashboard multi-select uses root organs only, so this is optional.",
        )
        parser.add_argument(
            "--skip-initial-data",
            action="store_true",
            help="Do not run seed_initial_data before creating demo records.",
        )
        parser.add_argument(
            "--skip-photos",
            action="store_true",
            help="Do not create demo photo folders, placeholder photos and request-photo links.",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Remove records previously created by this command for the selected organs before seeding again.",
        )

    def handle(self, *args, **options):
        if not options["skip_initial_data"]:
            call_command("seed_initial_data")

        organs = self._selected_organs(include_children=options["include_children"], limit=options["organs"])
        if not organs:
            self.stdout.write(self.style.ERROR("Нет активных территориальных органов для заполнения."))
            return

        user = self._demo_user()
        self.products = self._products()
        self.departments = {department.slug: department for department in Department.objects.filter(is_active=True)}
        self.stats = Counter()

        with transaction.atomic():
            if options["clear"]:
                self._clear_demo_data(organs)
            for organ_index, organ in enumerate(organs, start=1):
                self._seed_organ(organ, organ_index, user, with_photos=not options["skip_photos"])

        self.stdout.write(self.style.SUCCESS(f"Территориальных органов заполнено: {len(organs)}"))
        for key, value in sorted(self.stats.items()):
            self.stdout.write(self.style.SUCCESS(f"{key}: {value}"))
        self.stdout.write(self.style.SUCCESS("Демо-данные готовы. Повторный запуск не создает дубли."))

    def _selected_organs(self, include_children, limit):
        qs = TerritorialOrgan.objects.filter(is_active=True)
        if not include_children:
            qs = qs.filter(parent__isnull=True)
        organs = list(qs.order_by("order_number", "name"))
        return organs[:limit] if limit else organs

    def _demo_user(self):
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).order_by("id").first()
        if user:
            UserProfile.objects.get_or_create(user=user, defaults={"role": UserProfile.Role.ADMIN})
            return user

        user, _ = User.objects.get_or_create(
            username=DEMO_USER_USERNAME,
            defaults={
                "first_name": "Оператор",
                "last_name": "Демо",
                "email": "",
                "is_staff": True,
            },
        )
        if user.has_usable_password():
            user.set_unusable_password()
            user.save(update_fields=["password"])
        UserProfile.objects.update_or_create(user=user, defaults={"role": UserProfile.Role.ADMIN, "middle_name": "Системный"})
        return user

    def _products(self):
        products = []
        for name, unit in TMC_PRODUCTS:
            product, _ = TmcProduct.objects.get_or_create(
                normalized_name=normalize_product_name(name),
                defaults={"name": name, "unit": unit, "is_active": True},
            )
            if product.unit != unit or not product.is_active:
                product.unit = unit
                product.is_active = True
                product.save(update_fields=["unit", "is_active", "updated_at"])
            products.append(product)
        return products

    def _seed_organ(self, organ, organ_index, user, with_photos):
        self._seed_tmc(organ, organ_index, user)
        self._seed_transport(organ, organ_index, user)
        self._seed_fire(organ, organ_index, user)
        self._seed_antiterror(organ, organ_index, user)
        self._seed_citsizi(organ, organ_index, user)
        self._seed_uoto(organ, organ_index, user)
        if with_photos:
            photos = self._seed_photos(organ, organ_index, user)
            self._link_photos_to_requests(organ, user, photos)

    def _seed_tmc(self, organ, organ_index, user):
        today = timezone.localdate()
        for item_number in range(1, 7):
            status = STATUS_CYCLE[(organ_index + item_number) % len(STATUS_CYCLE)]
            request_date = today - timedelta(days=item_number * 5 + organ_index % 9)
            due_date = self._completed_at(request_date, item_number) if status == NeedStatus.DONE else None
            request_obj, _ = self._upsert_request(
                model=TmcRequest,
                organ=organ,
                department="tmc",
                request_number=self._request_number("ТМЦ", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "due_date": due_date,
                    "comment": self._comment(f"Заявка {TMC_SCENARIOS[(organ_index + item_number) % len(TMC_SCENARIOS)]}."),
                },
                table_key="tmc-requests",
            )
            self._replace_tmc_items(request_obj, organ_index, item_number)
            self.stats["ТМЦ-заявки"] += 1

    def _seed_transport(self, organ, organ_index, user):
        today = timezone.localdate()
        self._seed_vehicle_inventory(organ, organ_index, user)
        for item_number in range(1, 5):
            request_date = today - timedelta(days=item_number * 9 + organ_index % 11)
            status = STATUS_CYCLE[(organ_index + item_number + 1) % len(STATUS_CYCLE)]
            self._upsert_request(
                model=VehicleRepairRequest,
                organ=organ,
                department="transport",
                request_number=self._request_number("АТР", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "completed_at": self._completed_at(request_date, item_number) if status == NeedStatus.DONE else None,
                    "comment": self._comment(VEHICLE_REPAIR_SCENARIOS[(organ_index + item_number) % len(VEHICLE_REPAIR_SCENARIOS)]),
                },
                table_key="vehicle-repair",
            )
            self.stats["Заявки на ремонт автотранспорта"] += 1

        for item_number in range(1, 4):
            request_date = today - timedelta(days=item_number * 8 + organ_index % 7)
            status = STATUS_CYCLE[(organ_index + item_number + 2) % len(STATUS_CYCLE)]
            self._upsert_request(
                model=VehicleFuelRequest,
                organ=organ,
                department="transport",
                request_number=self._request_number("ГСМ", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "completed_at": self._completed_at(request_date, item_number) if status == NeedStatus.DONE else None,
                    "comment": self._comment(FUEL_SCENARIOS[(organ_index + item_number) % len(FUEL_SCENARIOS)]),
                },
                table_key="vehicle-fuel",
            )
            self.stats["Заявки на ГСМ"] += 1

    def _seed_vehicle_inventory(self, organ, organ_index, user):
        today = timezone.localdate()
        base = self._organ_scale(organ, organ_index)
        for snapshot_number in range(3):
            required = base + 3 + snapshot_number
            available = max(required - ((organ_index + snapshot_number) % 3), 0)
            broken = min(available, (organ_index + snapshot_number) % 2)
            writeoff = min(required, 1 if organ_index % 5 == 0 and snapshot_number == 0 else 0)
            self._upsert_snapshot(
                model=VehicleInventory,
                organ=organ,
                state_date=today - timedelta(days=30 * snapshot_number),
                user=user,
                defaults={
                    "required_count": required,
                    "available_count": available,
                    "broken_count": broken,
                    "writeoff_count": writeoff,
                    "comment": self._comment("Срез обеспеченности служебным автотранспортом."),
                },
            )
            self.stats["Срезы автотранспорта"] += 1

    def _seed_fire(self, organ, organ_index, user):
        today = timezone.localdate()
        base = self._organ_scale(organ, organ_index)
        for snapshot_number in range(3):
            required = base + 8 + snapshot_number * 2
            available = max(required - ((organ_index + snapshot_number) % 4), 0)
            self._upsert_snapshot(
                model=FireExtinguisher,
                organ=organ,
                state_date=today - timedelta(days=30 * snapshot_number),
                user=user,
                defaults={
                    "required_count": required,
                    "available_count": available,
                    "expiry_date": today + timedelta(days=(snapshot_number - 1) * 45 + (organ_index % 20)),
                    "writeoff_count": min(required, (organ_index + snapshot_number) % 2),
                    "comment": self._comment("Сведения по огнетушителям административных зданий и гаражных боксов."),
                },
            )
            self.stats["Срезы огнетушителей"] += 1

            required_objects = max(1, base // 3 + snapshot_number + 1)
            equipped_objects = max(required_objects - ((organ_index + snapshot_number) % 2), 0)
            broken_objects = min(equipped_objects, 1 if organ_index % 6 == 0 and snapshot_number == 0 else 0)
            self._upsert_snapshot(
                model=FireAlarm,
                organ=organ,
                state_date=today - timedelta(days=30 * snapshot_number),
                user=user,
                defaults={
                    "required_objects": required_objects,
                    "equipped_objects": equipped_objects,
                    "broken_objects": broken_objects,
                    "comment": self._comment("Сведения по объектам, оборудованным пожарной сигнализацией."),
                },
            )
            self.stats["Срезы пожарной сигнализации"] += 1

            security_required = required_objects + 1
            security_equipped = max(security_required - ((organ_index + snapshot_number + 1) % 2), 0)
            security_broken = min(security_equipped, 1 if organ_index % 7 == 0 and snapshot_number == 0 else 0)
            self._upsert_snapshot(
                model=SecurityAlarm,
                organ=organ,
                state_date=today - timedelta(days=30 * snapshot_number),
                user=user,
                defaults={
                    "required_objects": security_required,
                    "equipped_objects": security_equipped,
                    "broken_objects": security_broken,
                    "comment": self._comment("Сведения по объектам, оборудованным охранной сигнализацией."),
                },
            )
            self.stats["Срезы охранной сигнализации"] += 1

        for item_number in range(1, 4):
            request_date = today - timedelta(days=item_number * 10 + organ_index % 8)
            status = STATUS_CYCLE[(organ_index + item_number + 3) % len(STATUS_CYCLE)]
            self._upsert_request(
                model=FireDepartmentRequest,
                organ=organ,
                department="fire",
                request_number=self._request_number("ПБ", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "completed_at": self._completed_at(request_date, item_number) if status == NeedStatus.DONE else None,
                    "comment": self._comment(FIRE_REQUEST_SCENARIOS[(organ_index + item_number) % len(FIRE_REQUEST_SCENARIOS)]),
                },
                table_key="fire-requests",
            )
            self.stats["Заявки пожарной безопасности"] += 1

    def _seed_antiterror(self, organ, organ_index, user):
        today = timezone.localdate()
        for item_number in range(1, 4):
            request_date = today - timedelta(days=item_number * 13 + organ_index % 9)
            status = STATUS_CYCLE[(organ_index + item_number + 4) % len(STATUS_CYCLE)]
            self._upsert_request(
                model=AntiTerrorMeasure,
                organ=organ,
                department="antiterror",
                request_number=self._request_number("АТЗ", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "completed_at": self._completed_at(request_date, item_number) if status == NeedStatus.DONE else None,
                    "comment": self._comment(ANTITERROR_SCENARIOS[(organ_index + item_number) % len(ANTITERROR_SCENARIOS)]),
                },
                table_key="anti-terror",
            )
            self.stats["Антитеррористическая укрепленность"] += 1

    def _seed_citsizi(self, organ, organ_index, user):
        today = timezone.localdate()
        equipment_types = [choice[0] for choice in EquipmentType.choices]
        for item_number in range(1, 5):
            equipment_type = equipment_types[(organ_index + item_number) % len(equipment_types)]
            request_date = today - timedelta(days=item_number * 7 + organ_index % 10)
            status = STATUS_CYCLE[(organ_index + item_number + 1) % len(STATUS_CYCLE)]
            self._upsert_request(
                model=CitsiziEquipment,
                organ=organ,
                department="citsizi",
                request_number=self._request_number("ЦЗ", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "equipment_type": equipment_type,
                    "quantity": 1 + ((organ_index + item_number) % 5),
                    "status": status,
                    "due_date": self._completed_at(request_date, item_number) if status == NeedStatus.DONE else None,
                    "comment": self._comment(CITSIZI_SCENARIOS[equipment_type]),
                },
                table_key="citsizi-equipment",
            )
            self.stats["Заявки ЦИТСиЗИ"] += 1

    def _seed_uoto(self, organ, organ_index, user):
        today = timezone.localdate()
        base = max(1, self._organ_scale(organ, organ_index) // 5)
        for snapshot_number in range(3):
            total = base + (1 if organ_index % 4 == 0 else 0)
            used = max(total - 1 - (snapshot_number % 2), 0)
            ready = min(total - used, 1 if total > used else 0)
            self._upsert_snapshot(
                model=ServiceHousing,
                organ=organ,
                state_date=today - timedelta(days=30 * snapshot_number),
                user=user,
                defaults={
                    "total_count": total,
                    "used_by_staff": used,
                    "ready_to_move": ready,
                    "comment": self._comment("Сведения по служебному жилью, закрепленному за территориальным органом."),
                },
            )
            self.stats["Срезы служебного жилья"] += 1

        for item_number in range(1, 4):
            request_date = today - timedelta(days=item_number * 11 + organ_index % 7)
            status = STATUS_CYCLE[(organ_index + item_number + 2) % len(STATUS_CYCLE)]
            self._upsert_request(
                model=BuildingRepairRequest,
                organ=organ,
                department="uoto",
                request_number=self._request_number("ТР", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "completed_at": self._completed_at(request_date, item_number) if status == NeedStatus.DONE else None,
                    "comment": self._comment(BUILDING_REPAIR_SCENARIOS[(organ_index + item_number) % len(BUILDING_REPAIR_SCENARIOS)]),
                },
                table_key="building-repair",
            )
            self.stats["Заявки текущего ремонта"] += 1

    def _upsert_request(self, model, organ, department, request_number, user, defaults, table_key):
        obj = model.objects.filter(territorial_organ=organ, request_number=request_number).first()
        created = obj is None
        if created:
            obj = model(territorial_organ=organ, request_number=request_number, created_by=user)
        for field_name, value in defaults.items():
            setattr(obj, field_name, value)
        obj.updated_by = user
        obj.full_clean()
        obj.save()
        sync_request_number_registry(obj, department)
        self._ensure_status_history(obj, table_key, user)
        return obj, created

    def _upsert_snapshot(self, model, organ, state_date, user, defaults):
        obj = model.objects.filter(territorial_organ=organ, state_date=state_date, comment__contains=DEMO_MARKER).first()
        created = obj is None
        if created:
            obj = model(territorial_organ=organ, state_date=state_date, created_by=user)
        for field_name, value in defaults.items():
            setattr(obj, field_name, value)
        obj.updated_by = user
        obj.full_clean()
        obj.save()
        return obj, created

    def _replace_tmc_items(self, request_obj, organ_index, request_index):
        request_obj.items.all().delete()
        item_count = 2 + ((organ_index + request_index) % 3)
        for row_number in range(item_count):
            product = self.products[(organ_index + request_index + row_number) % len(self.products)]
            TmcRequestItem.objects.create(
                request=request_obj,
                product=product,
                name=product.name,
                quantity=1 + ((organ_index + request_index + row_number) % 8),
                unit=product.unit,
            )
            self.stats["Позиции ТМЦ"] += 1

    def _ensure_status_history(self, obj, table_key, user):
        if not hasattr(obj, "status"):
            return
        content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
        if RequestStatusHistory.objects.filter(content_type=content_type, object_id=obj.pk).exists():
            return
        completion_field = completed_date_field(table_key)
        completed_at = getattr(obj, completion_field, None) if obj.status == NeedStatus.DONE else None
        RequestStatusHistory.objects.create(
            content_type=content_type,
            object_id=obj.pk,
            old_status=None,
            new_status=obj.status,
            completed_at=completed_at,
            changed_by=user,
            note="Создано командой demo-seed",
        )
        self.stats["Записи истории статусов"] += 1

    def _seed_photos(self, organ, organ_index, user):
        department = self.departments.get("uoto") or Department.objects.filter(is_active=True).first()
        folder, created = TerritorialOrganPhotoFolder.objects.get_or_create(
            territorial_organ=organ,
            parent=None,
            name=DEMO_PHOTO_FOLDER,
            is_deleted=False,
            defaults={"created_by": user, "updated_by": user, "created_department": department},
        )
        if not created:
            folder.updated_by = user
            folder.created_department = folder.created_department or department
            folder.save(update_fields=["updated_by", "created_department", "updated_at"])

        photos = []
        for photo_number, description in enumerate(PHOTO_DESCRIPTIONS, start=1):
            original_filename = f"demo-organ-{self._organ_code(organ)}-{photo_number}.jpg"
            photo = TerritorialOrganPhoto.objects.filter(
                territorial_organ=organ,
                original_filename=original_filename,
                description__contains=DEMO_MARKER,
                is_deleted=False,
            ).first()
            if not photo:
                photo = TerritorialOrganPhoto(
                    territorial_organ=organ,
                    folder=folder,
                    description=self._comment(description),
                    created_by=user,
                    updated_by=user,
                    created_department=department,
                )
                photo.image.save(original_filename, ContentFile(self._demo_image_bytes(organ, description, organ_index)), save=False)
                photo.full_clean()
                photo.save()
                self.stats["Фотографии"] += 1
            else:
                photo.folder = folder
                photo.description = self._comment(description)
                photo.updated_by = user
                photo.created_department = photo.created_department or department
                photo.full_clean()
                photo.save()
            photos.append(photo)
        return photos

    def _link_photos_to_requests(self, organ, user, photos):
        if not photos:
            return
        linkable = [
            *TmcRequest.objects.filter(territorial_organ=organ, comment__contains=DEMO_MARKER).order_by("request_date")[:1],
            *VehicleRepairRequest.objects.filter(territorial_organ=organ, comment__contains=DEMO_MARKER).order_by("request_date")[:1],
            *FireDepartmentRequest.objects.filter(territorial_organ=organ, comment__contains=DEMO_MARKER).order_by("request_date")[:1],
            *AntiTerrorMeasure.objects.filter(territorial_organ=organ, comment__contains=DEMO_MARKER).order_by("request_date")[:1],
            *BuildingRepairRequest.objects.filter(territorial_organ=organ, comment__contains=DEMO_MARKER).order_by("request_date")[:1],
        ]
        for index, obj in enumerate(linkable):
            photo = photos[index % len(photos)]
            content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
            _, created = RequestPhotoLink.objects.get_or_create(
                photo=photo,
                content_type=content_type,
                object_id=obj.pk,
                defaults={"territorial_organ": organ, "created_by": user},
            )
            if created:
                self.stats["Связи заявок с фотографиями"] += 1

    def _clear_demo_data(self, organs):
        request_models = (
            TmcRequest,
            VehicleRepairRequest,
            VehicleFuelRequest,
            FireDepartmentRequest,
            AntiTerrorMeasure,
            CitsiziEquipment,
            BuildingRepairRequest,
        )
        for model in request_models:
            content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
            object_ids = list(model.objects.filter(territorial_organ__in=organs, comment__contains=DEMO_MARKER).values_list("pk", flat=True))
            if not object_ids:
                continue
            RequestPhotoLink.objects.filter(content_type=content_type, object_id__in=object_ids).delete()
            RequestStatusHistory.objects.filter(content_type=content_type, object_id__in=object_ids).delete()
            for obj in model.objects.filter(pk__in=object_ids):
                remove_request_number_registry(obj)
            model.objects.filter(pk__in=object_ids).delete()
            self.stats[f"Удалено {model._meta.verbose_name_plural}"] += len(object_ids)

        for model in (VehicleInventory, FireExtinguisher, FireAlarm, SecurityAlarm, ServiceHousing):
            deleted, _ = model.objects.filter(territorial_organ__in=organs, comment__contains=DEMO_MARKER).delete()
            self.stats[f"Удалено {model._meta.verbose_name_plural}"] += deleted

        for photo in TerritorialOrganPhoto.objects.filter(territorial_organ__in=organs, description__contains=DEMO_MARKER):
            if photo.image:
                photo.image.delete(save=False)
            photo.delete()
        TerritorialOrganPhotoFolder.objects.filter(territorial_organ__in=organs, name=DEMO_PHOTO_FOLDER).delete()

    def _request_number(self, prefix, organ, index):
        return f"ЦХиСО-{prefix}/{self._organ_code(organ)}/{timezone.localdate().year}-{index:03d}"

    def _organ_code(self, organ):
        try:
            value = Decimal(organ.order_number)
            return str(value).replace(".", "-")
        except (InvalidOperation, TypeError, ValueError):
            return str(organ.pk)

    def _organ_scale(self, organ, organ_index):
        name = organ.name.lower()
        if organ.parent_id:
            return 5 + organ_index % 5
        if any(word in name for word in ("красноярск", "норильск", "канск", "ачинск", "минусинск", "лесосибирск", "железногорск")):
            return 22 + organ_index % 8
        if any(word in name for word in ("таймыр", "эвенкий", "турухан", "северо-енисей")):
            return 14 + organ_index % 6
        return 10 + organ_index % 7

    def _completed_at(self, request_date, index):
        completed_at = request_date + timedelta(days=2 + index % 6)
        return min(completed_at, timezone.localdate())

    def _comment(self, text):
        return f"{text} {DEMO_MARKER}"

    def _demo_image_bytes(self, organ, description, organ_index):
        width, height = 1280, 720
        image = Image.new("RGB", (width, height), color=(230, 230, 225))
        draw = ImageDraw.Draw(image)
        draw.rectangle((50, 70, width - 50, height - 70), outline=(120, 120, 120), width=5)
        draw.rectangle((90, 120, width - 90, 260), fill=(210, 210, 205))
        draw.rectangle((140, 330, 1140, 620), fill=(200, 205, 205), outline=(120, 120, 120), width=4)
        draw.text((120, 150), "DEMO PHOTO MATERIAL", fill=(40, 40, 40))
        draw.text((120, 205), f"Territorial organ code: {self._organ_code(organ)}", fill=(40, 40, 40))
        draw.text((170, 390), f"Photo set: {organ_index}", fill=(40, 40, 40))
        draw.text((170, 450), "Generated placeholder for manual UI testing", fill=(80, 80, 80))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        return buffer.getvalue()
