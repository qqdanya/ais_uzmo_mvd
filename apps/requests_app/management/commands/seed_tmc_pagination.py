from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.directory.models import TerritorialOrgan
from apps.requests_app.models import NeedStatus, TmcProduct, TmcRequest, TmcRequestItem, normalize_product_name


class Command(BaseCommand):
    help = "Creates demo TMC requests for checking table pagination."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=45)

    def handle(self, *args, **options):
        organ = TerritorialOrgan.objects.filter(is_active=True, parent__isnull=True).order_by("order_number", "name").first()
        if not organ:
            self.stdout.write(self.style.ERROR("No active territorial organ found."))
            return

        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first() or User.objects.first()
        products = [
            ("Бумага А4", "пач."),
            ("Картридж лазерный", "шт."),
            ("Папка-регистратор", "шт."),
            ("Ручка шариковая", "шт."),
            ("Стол компьютерный", "шт."),
            ("Кресло офисное", "шт."),
            ("Клавиатура проводная", "шт."),
            ("Мышь компьютерная", "шт."),
            ("Пылесос", "шт."),
            ("Сетевой фильтр", "шт."),
        ]
        product_objs = []
        for name, unit in products:
            product = TmcProduct.objects.filter(normalized_name=normalize_product_name(name)).first()
            if not product:
                product = TmcProduct.objects.create(name=name, unit=unit)
            product_objs.append(product)

        statuses = [NeedStatus.NEW, NeedStatus.IN_WORK, NeedStatus.DONE, NeedStatus.REJECTED]
        created = 0
        count = options["count"]
        for index in range(1, count + 1):
            number = f"DEMO-TMC-{index:03d}"
            status = statuses[index % len(statuses)]
            request_obj, was_created = TmcRequest.objects.get_or_create(
                territorial_organ=organ,
                request_number=number,
                defaults={
                    "request_date": timezone.localdate() - timedelta(days=index % 18),
                    "status": status,
                    "due_date": timezone.localdate() if status == NeedStatus.DONE else None,
                    "comment": f"Демонстрационная заявка для проверки пагинации № {index}",
                    "created_by": user,
                    "updated_by": user,
                },
            )
            if was_created:
                created += 1
            for item_index in range(1, (index % 3) + 2):
                product = product_objs[(index + item_index) % len(product_objs)]
                TmcRequestItem.objects.get_or_create(
                    request=request_obj,
                    name=product.name,
                    defaults={
                        "product": product,
                        "quantity": (index * item_index) % 9 + 1,
                        "unit": product.unit,
                    },
                )

        self.stdout.write(self.style.SUCCESS(f"Organ: {organ.name}"))
        self.stdout.write(self.style.SUCCESS(f"Created: {created}"))
        self.stdout.write(self.style.SUCCESS(f"Demo total: {TmcRequest.objects.filter(territorial_organ=organ, request_number__startswith='DEMO-TMC-').count()}"))
        self.stdout.write(self.style.SUCCESS(f"TMC total: {TmcRequest.objects.filter(territorial_organ=organ, is_deleted=False).count()}"))
