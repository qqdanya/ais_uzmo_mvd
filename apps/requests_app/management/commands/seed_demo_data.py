"""Generates realistic, configurable demo data for load and UI testing.

Every record this command creates or touches is attributed to a dedicated
demo user (DEMO_USERNAME). That attribution - not a text marker - is what
identifies demo data later for --clear, so comments and descriptions stay
plain, realistic sentences with no seed-tool artifacts in them.
"""
from __future__ import annotations

import random
from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.models import (
    AntiTerrorMeasure,
    BuildingRepairRequest,
    CitsiziEquipment,
    EquipmentType,
    FireAlarm,
    FireDepartmentRequest,
    FireExtinguisher,
    NeedStatus,
    RequestNumberRegistry,
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
from apps.requests_app.dev_state import SeedCancelled
from apps.requests_app.services.request_numbers import sync_request_number_registry
from apps.requests_app.services.statuses import completed_date_field

# SQLite's default per-statement variable limit can be as low as 999 -
# _clear_demo_data() can otherwise build a single pk__in/object_id__in with
# thousands of values from a large demo run and hit "too many SQL variables".
SQL_IN_CHUNK_SIZE = 500


def _parse_organ_ids(value):
    if not value:
        return None
    return [int(part) for part in value.split(",") if part.strip()]


def _chunked(items, size=SQL_IN_CHUNK_SIZE):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start : start + size]


DEMO_USERNAME = "demo_seed_bot"

STATUS_CHOICES = (NeedStatus.IN_WORK, NeedStatus.DONE, NeedStatus.REJECTED)
DEFAULT_IN_WORK_WEIGHT = 45
DEFAULT_DONE_WEIGHT = 40
DEFAULT_REJECTED_WEIGHT = 15

TMC_PRODUCTS = (
    # Канцелярские товары
    ("Бумага офисная А4, 80 г/м²", "пач."),
    ("Бумага офисная А3, 80 г/м²", "пач."),
    ("Папка-регистратор 75 мм", "шт."),
    ("Папка-скоросшиватель картонная", "шт."),
    ("Папка на кольцах А4", "шт."),
    ("Файл-вкладыш А4 (пленка)", "упак."),
    ("Разделители листов картонные", "упак."),
    ("Ручка шариковая синяя", "шт."),
    ("Ручка шариковая черная", "шт."),
    ("Карандаш чернографитный", "шт."),
    ("Маркер перманентный черный", "шт."),
    ("Маркер текстовыделитель желтый", "шт."),
    ("Маркер для доски сухостираемый", "компл."),
    ("Ластик канцелярский", "шт."),
    ("Точилка для карандашей", "шт."),
    ("Линейка 30 см пластиковая", "шт."),
    ("Ножницы канцелярские", "шт."),
    ("Нож канцелярский (резак)", "шт."),
    ("Клей-карандаш", "шт."),
    ("Клей ПВА канцелярский", "фл."),
    ("Корректирующая жидкость", "шт."),
    ("Скотч канцелярский 19 мм", "шт."),
    ("Скотч упаковочный широкий", "шт."),
    ("Степлер № 24/6", "шт."),
    ("Скобы для степлера № 24/6", "упак."),
    ("Дырокол на 20 листов", "шт."),
    ("Скрепки канцелярские 28 мм", "упак."),
    ("Зажимы для бумаг 19 мм", "упак."),
    ("Стикеры для заметок 76х76 мм", "упак."),
    ("Конверт C4", "шт."),
    ("Конверт C5", "шт."),
    ("Конверт с окном DL", "шт."),
    ("Штемпельная подушка", "шт."),
    ("Штемпельная краска", "фл."),
    ("Блокнот А5 в клетку", "шт."),
    ("Тетрадь общая 96 листов", "шт."),
    ("Календарь настольный перекидной", "шт."),
    ("Настольный органайзер для канцелярии", "шт."),
    ("Антистеплер", "шт."),
    # Компьютерная и оргтехника
    ("Картридж лазерный HP 59A", "шт."),
    ("Картридж лазерный HP 85A", "шт."),
    ("Картридж Canon 725", "шт."),
    ("Картридж струйный Epson", "шт."),
    ("Тонер-туба для копира", "шт."),
    ("Бумага для факса термическая", "рулон"),
    ("Флеш-накопитель USB 32 ГБ", "шт."),
    ("Внешний жесткий диск 1 ТБ", "шт."),
    ("Кабель патч-корд UTP кат.5e, 3 м", "шт."),
    ("Разъем RJ-45 (коннектор)", "упак."),
    ("Сетевой фильтр 5 розеток", "шт."),
    ("Источник бесперебойного питания 650 ВА", "шт."),
    ("Клавиатура проводная USB", "шт."),
    ("Мышь компьютерная USB", "шт."),
    ("Коврик для компьютерной мыши", "шт."),
    ("Наушники с микрофоном (гарнитура)", "шт."),
    ("Веб-камера USB", "шт."),
    ("Батарейка AA", "упак."),
    ("Батарейка AAA", "упак."),
    ("Аккумулятор для радиостанции", "шт."),
    ("Удлинитель сетевой 5 м", "шт."),
    # Мебель и обустройство
    ("Стул офисный", "шт."),
    ("Кресло операторское", "шт."),
    ("Стол письменный офисный", "шт."),
    ("Шкаф металлический для документов", "шт."),
    ("Сейф металлический малый", "шт."),
    ("Стеллаж архивный металлический", "шт."),
    ("Вешалка напольная", "шт."),
    ("Жалюзи вертикальные офисные", "компл."),
    ("Лампа светодиодная E27", "шт."),
    ("Светильник настольный", "шт."),
    ("Часы настенные", "шт."),
    # Хозяйственные и чистящие средства
    ("Чистящее средство для оргтехники", "фл."),
    ("Моющее средство универсальное", "фл."),
    ("Стеклоочиститель", "фл."),
    ("Мешки для мусора 120 л", "упак."),
    ("Бумажные полотенца", "упак."),
    ("Туалетная бумага", "упак."),
    ("Жидкое мыло", "фл."),
    ("Освежитель воздуха", "шт."),
    ("Швабра с ведром (комплект)", "компл."),
    ("Салфетки для уборки микрофибра", "упак."),
    ("Перчатки хозяйственные резиновые", "пара"),
    # Инструмент и хозяйственный инвентарь
    ("Набор отверток", "компл."),
    ("Молоток слесарный", "шт."),
    ("Рулетка измерительная 5 м", "шт."),
    ("Фонарь аккумуляторный ручной", "шт."),
    ("Удлинитель силовой на катушке", "шт."),
    # Средства индивидуальной защиты и аптечка
    ("Аптечка первой помощи офисная", "шт."),
    ("Перчатки одноразовые латексные", "упак."),
    ("Жилет сигнальный со светоотражающими полосами", "шт."),
    # Хозяйство дежурной части
    ("Кулер для воды напольный", "шт."),
    ("Бутыль для кулера 19 л", "шт."),
    ("Электрочайник", "шт."),
    ("Стакан одноразовый пластиковый", "упак."),
)

TMC_SCENARIOS = (
    "Заявка для канцелярии дежурной части и регистрации входящей корреспонденции.",
    "Заявка для рабочих мест подразделения тылового обеспечения.",
    "Заявка для кабинета участковых уполномоченных и архива материалов.",
    "Заявка для обеспечения работы следственно-оперативной группы.",
    "Заявка для замены изношенных расходных материалов в приемной граждан.",
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


class Command(BaseCommand):
    help = "Creates realistic, configurable demo data across territorial organs and all dashboard tables."
    # Not a CLI flag - only settable via call_command(..., progress_callback=fn)
    # from the /dev/seed/ view, which polls a callable(done, total) to report
    # progress. See BaseCommand.stealth_options for how this bypasses
    # call_command's "unknown option" validation.
    stealth_options = ("progress_callback",)

    def add_arguments(self, parser):
        parser.add_argument("--organs", type=int, default=None, help="Limit the number of territorial organs to seed. By default all root organs are used.")
        parser.add_argument("--organ-ids", type=_parse_organ_ids, default=None, help="Comma-separated territorial organ IDs to seed. Overrides --organs if given.")
        parser.add_argument("--requests-per-table-min", type=int, default=3, help="Minimum number of requests to generate per organ for each request table.")
        parser.add_argument("--requests-per-table-max", type=int, default=6, help="Maximum number of requests to generate per organ for each request table.")
        parser.add_argument("--snapshots", type=int, default=3, help="How many state-snapshot slices to generate per organ for each state table.")
        parser.add_argument("--days-span", type=int, default=180, help="Spread generated request/snapshot dates across this many days back from today.")
        parser.add_argument("--review-days-max", type=int, default=14, help="Requests start out 'В работе'. Within this many days they may move to 'Исполнена'/'Отклонена'; once this many days have passed since filing, they must have resolved by now - no request stays 'В работе' forever.")
        parser.add_argument("--in-work-weight", type=int, default=DEFAULT_IN_WORK_WEIGHT, help="Relative weight for a request staying 'В работе', while its review window is still open.")
        parser.add_argument("--done-weight", type=int, default=DEFAULT_DONE_WEIGHT, help="Relative weight for a request resolving to 'Исполнена'.")
        parser.add_argument("--rejected-weight", type=int, default=DEFAULT_REJECTED_WEIGHT, help="Relative weight for a request resolving to 'Отклонена'.")
        parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible output. A random one is chosen and reported if omitted.")
        parser.add_argument("--skip-initial-data", action="store_true", help="Do not run seed_initial_data before creating demo records.")
        parser.add_argument("--clear", action="store_true", help="Remove demo records previously created by this command for the selected organs before seeding again.")

    def handle(self, *args, **options):
        if not options["skip_initial_data"]:
            call_command("seed_initial_data")

        organs = self._selected_organs(organ_ids=options.get("organ_ids"), limit=options["organs"])
        if not organs:
            self.stdout.write(self.style.ERROR("Нет активных территориальных органов для заполнения."))
            return

        seed = options["seed"] if options["seed"] is not None else random.SystemRandom().randrange(1_000_000)
        self.rng = random.Random(seed)
        self.requests_per_table_min = max(0, options["requests_per_table_min"])
        self.requests_per_table_max = max(self.requests_per_table_min, options["requests_per_table_max"])
        self.snapshots = max(0, options["snapshots"])
        self.days_span = max(1, options["days_span"])
        self.review_days_max = max(1, options["review_days_max"])
        self._configure_status_weights(options["in_work_weight"], options["done_weight"], options["rejected_weight"])
        progress_callback = options.get("progress_callback")

        user = self._demo_user()
        self.products = self._products()
        self.stats = Counter()

        if options["clear"]:
            self._clear_demo_data(organs, user)

        # Each department section for each organ gets its own short
        # transaction rather than one per organ (let alone one for the whole
        # run) - with a large requests-per-table range, even one organ's
        # worth of writes can take long enough to hold SQLite's write lock
        # past any other request's busy timeout (session saves on every
        # request, thanks to SESSION_SAVE_EVERY_REQUEST, are themselves
        # writes and will collide with this just as easily as a real write).
        canceled_after = None
        for index, organ in enumerate(organs, start=1):
            self._seed_organ(organ, user)
            if progress_callback:
                try:
                    progress_callback(index, len(organs))
                except SeedCancelled:
                    canceled_after = index
                    break

        if canceled_after is not None:
            self.stdout.write(self.style.WARNING(f"Генерация остановлена пользователем после {canceled_after} из {len(organs)} территориальных органов."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Территориальных органов заполнено: {len(organs)}"))
        self.stdout.write(self.style.SUCCESS(f"Seed для повторного воспроизведения этого набора данных: {seed}"))
        for key, value in sorted(self.stats.items()):
            self.stdout.write(self.style.SUCCESS(f"{key}: {value}"))
        if canceled_after is None:
            self.stdout.write(self.style.SUCCESS("Демо-данные готовы. Повторный запуск не создает дублей."))

    def _selected_organs(self, organ_ids, limit):
        # Requests are always scoped to a root territorial organ and one of
        # the 6 departments - child/subordinate units are purely structural
        # (shown as informational subunits on the organ card) and are never
        # themselves a request's territorial_organ, so there's nothing to
        # seed for them.
        qs = TerritorialOrgan.objects.filter(is_active=True, parent__isnull=True)
        if organ_ids:
            qs = qs.filter(pk__in=organ_ids)
        organs = list(qs.order_by("order_number", "name"))
        return organs[:limit] if limit else organs

    def _requests_count(self):
        return self.rng.randint(self.requests_per_table_min, self.requests_per_table_max)

    def _demo_user(self):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={"first_name": "Демо", "last_name": "Генератор", "email": ""},
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        UserProfile.objects.get_or_create(user=user, defaults={"role": UserProfile.Role.OPERATOR, "middle_name": "Тестовый"})
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

    def _seed_organ(self, organ, user):
        for step in (
            self._seed_tmc,
            self._seed_transport,
            self._seed_fire,
            self._seed_antiterror,
            self._seed_citsizi,
            self._seed_uoto,
        ):
            with transaction.atomic():
                step(organ, user)

    def _configure_status_weights(self, in_work_weight, done_weight, rejected_weight):
        in_work_weight, done_weight, rejected_weight = (max(0, w) for w in (in_work_weight, done_weight, rejected_weight))
        if in_work_weight + done_weight + rejected_weight <= 0:
            in_work_weight, done_weight, rejected_weight = DEFAULT_IN_WORK_WEIGHT, DEFAULT_DONE_WEIGHT, DEFAULT_REJECTED_WEIGHT
        self.status_weights = (in_work_weight, done_weight, rejected_weight)
        # Forced resolutions (see _lifecycle) only ever choose between DONE
        # and REJECTED - fall back to an even split if the user zeroed out
        # both, so a forced resolution still has something to pick from.
        self.resolved_weights = (done_weight, rejected_weight) if done_weight + rejected_weight > 0 else (1, 1)

    def _random_request_date(self):
        return timezone.localdate() - timedelta(days=self.rng.randint(0, self.days_span))

    def _lifecycle(self, request_date):
        """Every request is filed as "В работе". Within review_days_max days
        it may resolve into "Исполнена"/"Отклонена"; once that many days
        have passed since filing, the review window has definitely closed,
        so it must have resolved by now - no request stays "В работе"
        forever. Requests filed too recently for the window to have closed
        yet may still legitimately be open, same as a live backlog would.

        Pick the planned resolution delay from the full review window before
        comparing it with the request's age. Sampling only from the elapsed
        part of the window makes every recent cohort capable of resolving
        today and creates an artificial spike on the last chart day.
        """
        today = timezone.localdate()
        elapsed = (today - request_date).days
        if elapsed >= self.review_days_max:
            status = self.rng.choices((NeedStatus.DONE, NeedStatus.REJECTED), weights=self.resolved_weights, k=1)[0]
        else:
            status = self.rng.choices(STATUS_CHOICES, weights=self.status_weights, k=1)[0]
        if status == NeedStatus.IN_WORK:
            return status, None
        planned_delay = self.rng.randint(0, self.review_days_max)
        if planned_delay > elapsed:
            return NeedStatus.IN_WORK, None
        resolved_date = request_date + timedelta(days=planned_delay)
        return status, resolved_date

    def _as_datetime(self, date_value, *, after=None):
        # Demo history timestamps only need to be chronologically plausible,
        # not precise - pin them to a random business hour so ordering by
        # changed_at reads naturally instead of every event landing at
        # midnight. When a resolution lands on the same day it was filed,
        # offset it forward from the filing time instead of re-rolling an
        # independent hour, so the two events can't land out of order.
        if after is not None and date_value == after.date():
            return after + timedelta(minutes=self.rng.randint(30, 240))
        naive = datetime.combine(date_value, time(hour=self.rng.randint(8, 18), minute=self.rng.randint(0, 59)))
        return timezone.make_aware(naive)

    def _seed_tmc(self, organ, user):
        for item_number in range(1, self._requests_count() + 1):
            request_date = self._random_request_date()
            status, resolved_date = self._lifecycle(request_date)
            request_obj, _ = self._upsert_request(
                model=TmcRequest,
                organ=organ,
                department="tmc",
                request_number=self._request_number("ТМЦ", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "due_date": resolved_date if status == NeedStatus.DONE else None,
                    "comment": self.rng.choice(TMC_SCENARIOS),
                },
                table_key="tmc-requests",
                request_date=request_date,
                resolved_date=resolved_date,
            )
            self._replace_tmc_items(request_obj)
            self.stats["ТМЦ-заявки"] += 1

    def _seed_transport(self, organ, user):
        self._seed_vehicle_inventory(organ, user)
        for item_number in range(1, self._requests_count() + 1):
            request_date = self._random_request_date()
            status, resolved_date = self._lifecycle(request_date)
            self._upsert_request(
                model=VehicleRepairRequest,
                organ=organ,
                department="transport",
                request_number=self._request_number("АТР", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "completed_at": resolved_date if status == NeedStatus.DONE else None,
                    "comment": self.rng.choice(VEHICLE_REPAIR_SCENARIOS),
                },
                table_key="vehicle-repair",
                request_date=request_date,
                resolved_date=resolved_date,
            )
            self.stats["Заявки на ремонт автотранспорта"] += 1

        for item_number in range(1, self._requests_count() + 1):
            request_date = self._random_request_date()
            status, resolved_date = self._lifecycle(request_date)
            self._upsert_request(
                model=VehicleFuelRequest,
                organ=organ,
                department="transport",
                request_number=self._request_number("ГСМ", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "completed_at": resolved_date if status == NeedStatus.DONE else None,
                    "comment": self.rng.choice(FUEL_SCENARIOS),
                },
                table_key="vehicle-fuel",
                request_date=request_date,
                resolved_date=resolved_date,
            )
            self.stats["Заявки на ГСМ"] += 1

    def _seed_vehicle_inventory(self, organ, user):
        today = timezone.localdate()
        base = self._organ_scale(organ)
        for snapshot_number in range(self.snapshots):
            required = base + self.rng.randint(2, 6)
            available = self.rng.randint(max(required - 4, 0), required)
            broken = self.rng.randint(0, min(available, 3))
            writeoff = self.rng.randint(0, min(required, 2)) if self.rng.random() < 0.2 else 0
            self._upsert_snapshot(
                model=VehicleInventory,
                organ=organ,
                state_date=today - timedelta(days=self.rng.randint(0, self.days_span)),
                user=user,
                defaults={
                    "required_count": required,
                    "available_count": available,
                    "broken_count": broken,
                    "writeoff_count": writeoff,
                    "comment": "Срез обеспеченности служебным автотранспортом.",
                },
            )
            self.stats["Срезы автотранспорта"] += 1

    def _seed_fire(self, organ, user):
        today = timezone.localdate()
        base = self._organ_scale(organ)
        for snapshot_number in range(self.snapshots):
            required = base + self.rng.randint(5, 12)
            available = self.rng.randint(max(required - 4, 0), required)
            self._upsert_snapshot(
                model=FireExtinguisher,
                organ=organ,
                state_date=today - timedelta(days=self.rng.randint(0, self.days_span)),
                user=user,
                defaults={
                    "required_count": required,
                    "available_count": available,
                    "expiry_date": today + timedelta(days=self.rng.randint(-60, 400)),
                    "writeoff_count": self.rng.randint(0, min(required, 2)) if self.rng.random() < 0.2 else 0,
                    "comment": "Сведения по огнетушителям административных зданий и гаражных боксов.",
                },
            )
            self.stats["Срезы огнетушителей"] += 1

            required_objects = max(1, base // 3 + self.rng.randint(0, 3))
            equipped_objects = self.rng.randint(max(required_objects - 2, 0), required_objects)
            self._upsert_snapshot(
                model=FireAlarm,
                organ=organ,
                state_date=today - timedelta(days=self.rng.randint(0, self.days_span)),
                user=user,
                defaults={
                    "required_objects": required_objects,
                    "equipped_objects": equipped_objects,
                    "broken_objects": self.rng.randint(0, min(equipped_objects, 2)),
                    "comment": "Сведения по объектам, оборудованным пожарной сигнализацией.",
                },
            )
            self.stats["Срезы пожарной сигнализации"] += 1

            security_required = required_objects + self.rng.randint(0, 2)
            security_equipped = self.rng.randint(max(security_required - 2, 0), security_required)
            self._upsert_snapshot(
                model=SecurityAlarm,
                organ=organ,
                state_date=today - timedelta(days=self.rng.randint(0, self.days_span)),
                user=user,
                defaults={
                    "required_objects": security_required,
                    "equipped_objects": security_equipped,
                    "broken_objects": self.rng.randint(0, min(security_equipped, 2)),
                    "comment": "Сведения по объектам, оборудованным охранной сигнализацией.",
                },
            )
            self.stats["Срезы охранной сигнализации"] += 1

        for item_number in range(1, self._requests_count() + 1):
            request_date = self._random_request_date()
            status, resolved_date = self._lifecycle(request_date)
            self._upsert_request(
                model=FireDepartmentRequest,
                organ=organ,
                department="fire",
                request_number=self._request_number("ПБ", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "completed_at": resolved_date if status == NeedStatus.DONE else None,
                    "comment": self.rng.choice(FIRE_REQUEST_SCENARIOS),
                },
                table_key="fire-requests",
                request_date=request_date,
                resolved_date=resolved_date,
            )
            self.stats["Заявки пожарной безопасности"] += 1

    def _seed_antiterror(self, organ, user):
        for item_number in range(1, self._requests_count() + 1):
            request_date = self._random_request_date()
            status, resolved_date = self._lifecycle(request_date)
            self._upsert_request(
                model=AntiTerrorMeasure,
                organ=organ,
                department="antiterror",
                request_number=self._request_number("АТЗ", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "completed_at": resolved_date if status == NeedStatus.DONE else None,
                    "comment": self.rng.choice(ANTITERROR_SCENARIOS),
                },
                table_key="anti-terror",
                request_date=request_date,
                resolved_date=resolved_date,
            )
            self.stats["Антитеррористическая укрепленность"] += 1

    def _seed_citsizi(self, organ, user):
        equipment_types = [choice[0] for choice in EquipmentType.choices]
        for item_number in range(1, self._requests_count() + 1):
            equipment_type = self.rng.choice(equipment_types)
            request_date = self._random_request_date()
            status, resolved_date = self._lifecycle(request_date)
            self._upsert_request(
                model=CitsiziEquipment,
                organ=organ,
                department="citsizi",
                request_number=self._request_number("ЦЗ", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "equipment_type": equipment_type,
                    "quantity": self.rng.randint(1, 8),
                    "status": status,
                    "due_date": resolved_date if status == NeedStatus.DONE else None,
                    "comment": CITSIZI_SCENARIOS[equipment_type],
                },
                table_key="citsizi-equipment",
                request_date=request_date,
                resolved_date=resolved_date,
            )
            self.stats["Заявки ЦИТСиЗИ"] += 1

    def _seed_uoto(self, organ, user):
        today = timezone.localdate()
        base = max(1, self._organ_scale(organ) // 5)
        for snapshot_number in range(self.snapshots):
            total = base + self.rng.randint(0, 2)
            used = self.rng.randint(0, total)
            ready = self.rng.randint(0, total - used)
            self._upsert_snapshot(
                model=ServiceHousing,
                organ=organ,
                state_date=today - timedelta(days=self.rng.randint(0, self.days_span)),
                user=user,
                defaults={
                    "total_count": total,
                    "used_by_staff": used,
                    "ready_to_move": ready,
                    "comment": "Сведения по служебному жилью, закрепленному за территориальным органом.",
                },
            )
            self.stats["Срезы служебного жилья"] += 1

        for item_number in range(1, self._requests_count() + 1):
            request_date = self._random_request_date()
            status, resolved_date = self._lifecycle(request_date)
            self._upsert_request(
                model=BuildingRepairRequest,
                organ=organ,
                department="uoto",
                request_number=self._request_number("ТР", organ, item_number),
                user=user,
                defaults={
                    "request_date": request_date,
                    "status": status,
                    "completed_at": resolved_date if status == NeedStatus.DONE else None,
                    "comment": self.rng.choice(BUILDING_REPAIR_SCENARIOS),
                },
                table_key="building-repair",
                request_date=request_date,
                resolved_date=resolved_date,
            )
            self.stats["Заявки текущего ремонта"] += 1

    def _upsert_request(self, model, organ, department, request_number, user, defaults, table_key, request_date, resolved_date):
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
        self._ensure_status_history(obj, table_key, user, request_date, resolved_date)
        return obj, created

    def _upsert_snapshot(self, model, organ, state_date, user, defaults):
        # Scoped by created_by (the demo bot), not just (organ, state_date) -
        # a real user could legitimately have a snapshot for that same date,
        # and matching on it blindly would silently repurpose their record.
        obj = model.objects.filter(territorial_organ=organ, state_date=state_date, created_by=user).first()
        created = obj is None
        if created:
            obj = model(territorial_organ=organ, state_date=state_date, created_by=user)
        for field_name, value in defaults.items():
            setattr(obj, field_name, value)
        obj.updated_by = user
        obj.full_clean()
        obj.save()
        return obj, created

    def _replace_tmc_items(self, request_obj):
        request_obj.items.all().delete()
        item_count = self.rng.randint(1, min(5, len(self.products)))
        for product in self.rng.sample(self.products, k=item_count):
            TmcRequestItem.objects.create(
                request=request_obj,
                product=product,
                name=product.name,
                quantity=self.rng.randint(1, 20),
                unit=product.unit,
            )
            self.stats["Позиции ТМЦ"] += 1

    def _ensure_status_history(self, obj, table_key, user, request_date, resolved_date):
        if not hasattr(obj, "status"):
            return
        content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
        if RequestStatusHistory.objects.filter(content_type=content_type, object_id=obj.pk).exists():
            return

        filed_entry = RequestStatusHistory.objects.create(
            content_type=content_type,
            object_id=obj.pk,
            old_status=None,
            new_status=NeedStatus.IN_WORK,
            completed_at=None,
            changed_by=user,
            note="Создано генератором демо-данных",
        )
        filed_at = self._as_datetime(request_date)
        RequestStatusHistory.objects.filter(pk=filed_entry.pk).update(changed_at=filed_at)
        self.stats["Записи истории статусов"] += 1

        if obj.status == NeedStatus.IN_WORK or resolved_date is None:
            return

        completion_field = completed_date_field(table_key)
        completed_at = getattr(obj, completion_field, None) if obj.status == NeedStatus.DONE else None
        resolved_entry = RequestStatusHistory.objects.create(
            content_type=content_type,
            object_id=obj.pk,
            old_status=NeedStatus.IN_WORK,
            new_status=obj.status,
            completed_at=completed_at,
            changed_by=user,
            note="Статус изменен генератором демо-данных",
        )
        resolved_at = self._as_datetime(resolved_date, after=filed_at)
        RequestStatusHistory.objects.filter(pk=resolved_entry.pk).update(changed_at=resolved_at)
        self.stats["Записи истории статусов"] += 1

    def _clear_demo_data(self, organs, user):
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
            object_ids = list(model.objects.filter(territorial_organ__in=organs, created_by=user).values_list("pk", flat=True))
            if not object_ids:
                continue
            # A large demo run can produce thousands of ids - a single
            # pk__in with all of them at once can exceed SQLite's per-
            # statement variable limit ("too many SQL variables"), so
            # every pk__in/object_id__in lookup here is chunked. Each chunk
            # is also its own short transaction (see the comment on the
            # per-organ seeding loop above for why).
            for chunk in _chunked(object_ids):
                with transaction.atomic():
                    RequestStatusHistory.objects.filter(content_type=content_type, object_id__in=chunk).delete()
                    RequestNumberRegistry.objects.filter(content_type=content_type, object_id__in=chunk).delete()
                    model.objects.filter(pk__in=chunk).delete()
            self.stats[f"Удалено: {model._meta.verbose_name_plural}"] += len(object_ids)

        for model in (VehicleInventory, FireExtinguisher, FireAlarm, SecurityAlarm, ServiceHousing):
            with transaction.atomic():
                deleted, _ = model.objects.filter(territorial_organ__in=organs, created_by=user).delete()
            self.stats[f"Удалено: {model._meta.verbose_name_plural}"] += deleted

    def _request_number(self, prefix, organ, index):
        return f"ЦХиСО-{prefix}/{self._organ_code(organ)}/{timezone.localdate().year}-{index:03d}"

    def _organ_code(self, organ):
        try:
            value = Decimal(organ.order_number)
            return str(value).replace(".", "-")
        except (InvalidOperation, TypeError, ValueError):
            return str(organ.pk)

    def _organ_scale(self, organ):
        name = organ.name.lower()
        if organ.parent_id:
            return 5 + self.rng.randint(0, 4)
        if any(word in name for word in ("красноярск", "норильск", "канск", "ачинск", "минусинск", "лесосибирск", "железногорск")):
            return 22 + self.rng.randint(0, 7)
        if any(word in name for word in ("таймыр", "эвенкий", "турухан", "северо-енисей")):
            return 14 + self.rng.randint(0, 5)
        return 10 + self.rng.randint(0, 6)
