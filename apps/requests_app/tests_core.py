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

    def test_dashboard_places_organ_subunits_after_main_departments(self):
        for index in range(2, 7):
            Department.objects.create(name=f"Department {index}", slug=f"department-{index}", order_number=index)
        child = TerritorialOrgan.objects.create(name="Local department", order_number=1, parent=self.organ)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("dashboard"))
        content = response.content.decode()

        self.assertContains(response, 'id="organ-subunits"')
        self.assertContains(response, 'class="subunits has-subunits"')
        self.assertGreater(content.index(child.name), content.index("Department 6"))

    def test_organ_info_updates_moved_subunits_out_of_band(self):
        child = TerritorialOrgan.objects.create(name="Local department", order_number=1, parent=self.organ)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("organ_info", args=[self.organ.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, 'id="organ-subunits"')
        self.assertContains(response, 'class="subunits has-subunits"')
        self.assertContains(response, 'hx-swap-oob="outerHTML"')
        self.assertContains(response, child.name)

    def test_dashboard_exposes_server_default_state_for_js_redundant_fetch_check(self):
        # app.js's serverRenderedWorkspaceState() parses #table-area's hx-get
        # URL and the workspace's data-department-slug to detect when the
        # visitor's saved organ/department/table already match what the
        # server rendered, so it can skip re-fetching #organ-info/#workspace.
        # If this markup contract changes, that check silently stops working
        # and every page load goes back to always re-fetching.
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, 'data-tables-workspace')
        self.assertContains(response, f'data-department-slug="{self.department.slug}"')
        self.assertContains(response, f'hx-get="{reverse("table_data", args=[self.organ.pk, "tmc-requests"])}"')

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
            reverse("record_create", args=[other_organ.pk, "tmc-requests"]),
            reverse("request_photos", args=[other_organ.pk, "tmc-requests", foreign_request.pk]),
            reverse("request_photos_download", args=[other_organ.pk, "tmc-requests", foreign_request.pk]),
            reverse("request_photo_picker", args=[other_organ.pk]),
            reverse("export_table", args=[other_organ.pk, "tmc-requests", "csv"]),
            reverse("photo_download", args=[other_organ.pk, foreign_photo.pk]),
        ]

        for url in endpoints:
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 404)

        # table_data and photos back the navigation flow that auto-restores a
        # user's last-selected organ on page load - if an admin revokes that
        # organ in the meantime, this must render an honest "no access"
        # message (so htmx swaps it into the workspace normally) rather than
        # a 404 that htmx won't swap, leaving a stuck loading spinner.
        for url in [reverse("table_data", args=[other_organ.pk, "tmc-requests"]), reverse("photos", args=[other_organ.pk])]:
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Нет доступа к этому территориальному органу")

    def test_navigation_endpoints_show_honest_message_after_access_revoked(self):
        # Simulates the real scenario reported by users: they had this organ
        # open, an admin then revokes access to it, and the client's saved
        # navigation state (localStorage) tries to restore that same organ
        # on the next page load. table_data/department_tables/organ_info all
        # back that auto-restore flow via htmx swaps into a "Загрузка..."
        # placeholder - a raised Http404 there used to leave that spinner
        # stuck forever with just a generic error toast, instead of telling
        # the user plainly that access was revoked.
        self.client.login(username="operator", password="pass12345")
        self.profile.allowed_organs.set([])

        endpoints = [
            reverse("organ_info", args=[self.organ.pk]),
            reverse("department_tables", args=[self.organ.pk, self.department.slug]),
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
            reverse("photos", args=[self.organ.pk]),
        ]

        for url in endpoints:
            with self.subTest(url=url):
                response = self.client.get(url, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Нет доступа к этому территориальному органу")

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
