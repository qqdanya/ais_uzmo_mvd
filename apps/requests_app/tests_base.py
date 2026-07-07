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




class RequestAppTestCase(TestCase):

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("operator", password="pass12345")
        self.profile = UserProfile.objects.create(user=self.user, role=UserProfile.Role.OPERATOR)
        self.organ = TerritorialOrgan.objects.create(name="Test territorial organ", order_number=1)
        self.department = Department.objects.create(name="TMC", slug="tmc", order_number=1)
        self.profile.allowed_organs.set([self.organ])
        self.profile.allowed_departments.set([self.department])

    def status_history(self, obj):
        content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
        return RequestStatusHistory.objects.filter(content_type=content_type, object_id=obj.pk)

    def create_status_history_entry(self, obj, old_status=None, new_status="in_work"):
        return RequestStatusHistory.objects.create(
            content_type=ContentType.objects.get_for_model(obj, for_concrete_model=False),
            object_id=obj.pk,
            old_status=old_status,
            new_status=new_status,
            changed_by=self.user,
        )

    def response_bytes(self, response):
        if getattr(response, "streaming", False):
            return b"".join(response.streaming_content)
        return response.content

    def response_workbook(self, response):
        return load_workbook(BytesIO(self.response_bytes(response)))

    def create_photo(self, filename="photo.png"):
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        image = SimpleUploadedFile(filename, buffer.getvalue(), content_type="image/png")
        return TerritorialOrganPhoto.objects.create(territorial_organ=self.organ, image=image, created_by=self.user, updated_by=self.user)
