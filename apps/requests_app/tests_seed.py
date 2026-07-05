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
