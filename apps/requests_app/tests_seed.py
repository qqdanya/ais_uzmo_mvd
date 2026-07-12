import csv
from io import BytesIO
from datetime import timedelta
from urllib.parse import quote_plus
import zipfile

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from PIL import Image

from apps.accounts.models import UserProfile
from apps.audit.models import AuditLog
from apps.directory.models import Department, TerritorialOrgan, TerritorialOrganPhoto, TerritorialOrganPhotoFolder
from apps.requests_app.models import (
    ACTIVE_NEED_STATUS_CHOICES,
    AntiTerrorMeasure,
    CitsiziEquipment,
    EquipmentType,
    FireAlarm,
    FireDepartmentRequest,
    FireExtinguisher,
    NeedStatus,
    SecurityAlarm,
    BuildingRepairRequest,
    RequestPhotoLink,
    RequestStatusHistory,
    ServiceHousing,
    TmcProduct,
    TmcRequest,
    TmcRequestItem,
    VehicleFuelRequest,
    VehicleInventory,
    VehicleRepairRequest,
)
from apps.requests_app.registry import TABLES, TABLE_BY_KEY




class SeedCommandTests(TestCase):
    def test_seed_is_idempotent(self):
        from django.core.management import call_command

        call_command("seed_initial_data")
        first_count = TerritorialOrgan.objects.count()
        call_command("seed_initial_data")
        self.assertEqual(TerritorialOrgan.objects.count(), first_count)

    def test_recent_request_is_not_forced_to_resolve_today(self):
        from apps.requests_app.management.commands.seed_demo_data import Command

        class PlannedFutureResolution:
            def choices(self, *args, **kwargs):
                return [NeedStatus.DONE]

            def randint(self, start, end):
                return end

        command = Command()
        command.review_days_max = 14
        command.status_weights = (0, 1, 0)
        command.resolved_weights = (1, 0)
        command.rng = PlannedFutureResolution()

        status, resolved_date = command._lifecycle(timezone.localdate())

        self.assertEqual(status, NeedStatus.IN_WORK)
        self.assertIsNone(resolved_date)

    def test_same_day_resolution_remains_possible(self):
        from apps.requests_app.management.commands.seed_demo_data import Command

        class PlannedSameDayResolution:
            def choices(self, *args, **kwargs):
                return [NeedStatus.DONE]

            def randint(self, start, end):
                return 0

        command = Command()
        command.review_days_max = 14
        command.status_weights = (0, 1, 0)
        command.resolved_weights = (1, 0)
        command.rng = PlannedSameDayResolution()

        today = timezone.localdate()
        status, resolved_date = command._lifecycle(today)

        self.assertEqual(status, NeedStatus.DONE)
        self.assertEqual(resolved_date, today)
