from .tests_base import *


class CoreAccessTests(RequestAppTestCase):

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_after_login(self):
        Department.objects.create(name="Transport", slug="transport", order_number=2)
        Department.objects.create(name="Unknown", slug="unknown", order_number=3)
        self.client.login(username="operator", password="pass12345")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test territorial organ")
        self.assertContains(response, "bi-box-seam")
        self.assertContains(response, "bi-truck")
        self.assertContains(response, "bi-folder2-open")

    def test_invalid_table_key_returns_404_for_direct_urls(self):
        self.client.login(username="operator", password="pass12345")
        invalid_key = "unknown-table"
        urls = [
            reverse("table_data", args=[self.organ.pk, invalid_key]),
            reverse("record_create", args=[self.organ.pk, invalid_key]),
            reverse("record_update", args=[self.organ.pk, invalid_key, 999]),
            reverse("record_delete", args=[self.organ.pk, invalid_key, 999]),
            reverse("export_table", args=[self.organ.pk, invalid_key, "csv"]),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)

    def test_operator_cannot_access_foreign_organ_direct_urls(self):
        other_organ = TerritorialOrgan.objects.create(name="Foreign territorial organ", order_number=2)
        self.user.profile.allowed_organs.set([self.organ])
        foreign_request = TmcRequest.objects.create(
            territorial_organ=other_organ,
            created_by=self.user,
            request_number="FOREIGN-1",
            request_date="2026-06-27",
            status="in_work",
        )
        TmcRequestItem.objects.create(request=foreign_request, name="Desk", quantity=1, unit="шт.")
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        foreign_photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=other_organ,
            image=SimpleUploadedFile("foreign-organ.png", buffer.getvalue(), content_type="image/png"),
            created_by=self.user,
            updated_by=self.user,
        )
        self.client.login(username="operator", password="pass12345")

        endpoints = [
            reverse("table_data", args=[other_organ.pk, "tmc-requests"]),
            reverse("record_create", args=[other_organ.pk, "tmc-requests"]),
            reverse("request_photos", args=[other_organ.pk, "tmc-requests", foreign_request.pk]),
            reverse("request_photos_download", args=[other_organ.pk, "tmc-requests", foreign_request.pk]),
            reverse("request_photo_picker", args=[other_organ.pk]),
            reverse("export_table", args=[other_organ.pk, "tmc-requests", "csv"]),
            reverse("photos", args=[other_organ.pk]),
            reverse("photo_download", args=[other_organ.pk, foreign_photo.pk]),
        ]

        for url in endpoints:
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 404)

    def test_observer_can_view_table_but_cannot_write_records(self):
        User = get_user_model()
        observer = User.objects.create_user("observer", password="pass12345")
        observer_profile = UserProfile.objects.create(user=observer, role=UserProfile.Role.OBSERVER)
        observer_profile.allowed_organs.set([self.organ])
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            request_number="OBS-1",
            request_date="2026-06-27",
            status="in_work",
        )
        TmcRequestItem.objects.create(request=request_obj, name="Paper", quantity=1, unit="шт.")
        self.client.login(username="observer", password="pass12345")

        table_response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))
        create_response = self.client.get(reverse("record_create", args=[self.organ.pk, "tmc-requests"]), HTTP_HX_REQUEST="true")
        update_response = self.client.get(reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]), HTTP_HX_REQUEST="true")
        delete_response = self.client.post(reverse("record_delete", args=[self.organ.pk, "tmc-requests", request_obj.pk]), HTTP_HX_REQUEST="true")

        self.assertEqual(table_response.status_code, 200)
        self.assertContains(table_response, "OBS-1")
        self.assertNotContains(table_response, reverse("record_create", args=[self.organ.pk, "tmc-requests"]))
        self.assertNotContains(table_response, reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]))
        self.assertEqual(create_response.status_code, 404)
        self.assertEqual(update_response.status_code, 404)
        self.assertEqual(delete_response.status_code, 404)

    def test_operator_can_write_only_assigned_departments(self):
        transport = Department.objects.create(name="Transport", slug="transport", order_number=2)
        self.user.profile.allowed_departments.set([transport])
        request_obj = TmcRequest.objects.create(territorial_organ=self.organ, request_number="43/TMC", request_date="2026-06-20", status="in_work")
        TmcRequestItem.objects.create(request=request_obj, name="Paper", quantity=5, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        table_response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))
        create_response = self.client.get(reverse("record_create", args=[self.organ.pk, "tmc-requests"]), HTTP_HX_REQUEST="true")
        update_response = self.client.get(reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(table_response, "43/TMC")
        self.assertNotContains(table_response, reverse("record_create", args=[self.organ.pk, "tmc-requests"]))
        self.assertNotContains(table_response, reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]))
        self.assertEqual(create_response.status_code, 404)
        self.assertEqual(update_response.status_code, 404)
