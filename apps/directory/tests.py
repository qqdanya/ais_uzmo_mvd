import shutil
import tempfile
from decimal import Decimal
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from .forms import TerritorialOrganPhotoForm
from .models import TerritorialOrgan, TerritorialOrganPhoto


TEST_MEDIA_ROOT = tempfile.mkdtemp()


def make_disguised_upload(name="not-a-photo.jpg", content=b"not an image", content_type="image/jpeg"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def make_png_upload(name="photo.png", size=(1, 1), content_type="image/png"):
    buffer = BytesIO()
    Image.new("RGB", size, color="white").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class DirectoryModelConstraintsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_territorial_organ_order_number_cannot_be_negative(self):
        organ = TerritorialOrgan(name="Negative order", order_number=Decimal("-1.00"))

        with self.assertRaises(ValidationError) as context:
            organ.full_clean()

        self.assertIn("order_number", context.exception.message_dict)

    def test_photo_save_stores_file_size_and_mime_type(self):
        organ = TerritorialOrgan.objects.create(name="Photo organ", order_number=Decimal("1.00"))
        upload = make_png_upload()

        photo = TerritorialOrganPhoto.objects.create(territorial_organ=organ, image=upload)

        self.assertEqual(photo.original_filename, "photo.png")
        self.assertGreater(photo.file_size, 0)
        self.assertEqual(photo.file_size, upload.size)
        self.assertEqual(photo.mime_type, "image/png")

    def test_photo_metadata_is_refreshed_when_image_changes(self):
        organ = TerritorialOrgan.objects.create(name="Refresh organ", order_number=Decimal("2.00"))
        photo = TerritorialOrganPhoto.objects.create(territorial_organ=organ, image=make_png_upload("old.png", size=(1, 1)))
        old_size = photo.file_size

        new_upload = make_png_upload("new.png", size=(3, 3))
        photo.image = new_upload
        photo.save()
        photo.refresh_from_db()

        self.assertEqual(photo.original_filename, "new.png")
        self.assertEqual(photo.file_size, new_upload.size)
        self.assertNotEqual(photo.file_size, old_size)
        self.assertEqual(photo.mime_type, "image/png")

    def test_photo_validation_rejects_non_image_with_allowed_extension(self):
        organ = TerritorialOrgan.objects.create(name="Strict photo organ", order_number=Decimal("3.00"))
        photo = TerritorialOrganPhoto(territorial_organ=organ, image=make_disguised_upload())

        with self.assertRaises(ValidationError) as context:
            photo.full_clean()

        self.assertIn("image", context.exception.message_dict)

    def test_photo_form_rejects_non_image_with_allowed_extension(self):
        organ = TerritorialOrgan.objects.create(name="Strict form organ", order_number=Decimal("4.00"))
        form = TerritorialOrganPhotoForm(data={"description": "Fake"}, files={"image": make_disguised_upload()}, organ=organ)

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_photo_metadata_uses_real_image_mime_type(self):
        organ = TerritorialOrgan.objects.create(name="Real MIME organ", order_number=Decimal("5.00"))
        upload = make_png_upload("renamed.jpg", content_type="application/octet-stream")

        photo = TerritorialOrganPhoto.objects.create(territorial_organ=organ, image=upload)

        self.assertEqual(photo.original_filename, "renamed.jpg")
        self.assertEqual(photo.mime_type, "image/png")

