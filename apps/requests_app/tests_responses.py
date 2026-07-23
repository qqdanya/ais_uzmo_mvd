import csv
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.audit.models import AuditLog
from apps.audit.services.display import prepare_log
from apps.directory.models import TerritorialOrgan

from .models import (
    AntiTerrorMeasure,
    BuildingRepairRequest,
    CitsiziEquipment,
    EquipmentType,
    FireDepartmentRequest,
    NeedStatus,
    RequestResponse,
    TmcRequest,
    TmcRequestItem,
    VehicleFuelRequest,
    VehicleInventory,
    VehicleRepairRequest,
)
from .services.request_responses import attach_request_response_summaries
from .tests_base import RequestAppTestCase


class RequestResponseTestMixin:
    def setUp(self):
        super().setUp()
        self.request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="REQ-1",
            request_date=timezone.localdate() - timedelta(days=10),
            status=NeedStatus.IN_WORK,
            created_by=self.user,
            updated_by=self.user,
        )

    def response_content_type(self, request_obj=None):
        return ContentType.objects.get_for_model(
            request_obj or self.request_obj,
            for_concrete_model=False,
        )

    def create_response(
        self,
        *,
        request_obj=None,
        number="ANS-1",
        response_date=None,
        note="",
        user=None,
    ):
        request_obj = request_obj or self.request_obj
        return RequestResponse.objects.create(
            content_type=self.response_content_type(request_obj),
            object_id=request_obj.pk,
            response_number=number,
            response_date=response_date or timezone.localdate(),
            note=note,
            created_by=user or self.user,
            updated_by=user or self.user,
        )

    def response_panel_url(self, request_obj=None, table_key="tmc-requests", organ=None):
        request_obj = request_obj or self.request_obj
        return reverse(
            "request_responses",
            args=[(organ or request_obj.territorial_organ).pk, table_key, request_obj.pk],
        )

    def response_update_url(self, response_obj, request_obj=None, table_key="tmc-requests", organ=None):
        request_obj = request_obj or self.request_obj
        return reverse(
            "request_response_update",
            args=[
                (organ or request_obj.territorial_organ).pk,
                table_key,
                request_obj.pk,
                response_obj.pk,
            ],
        )

    def response_delete_url(self, response_obj, request_obj=None, table_key="tmc-requests", organ=None):
        request_obj = request_obj or self.request_obj
        return reverse(
            "request_response_delete",
            args=[
                (organ or request_obj.territorial_organ).pk,
                table_key,
                request_obj.pk,
                response_obj.pk,
            ],
        )

    def response_form_data(
        self,
        *,
        number="ANS-1",
        response_date=None,
        note="",
    ):
        return {
            "response_number": number,
            "response_date": (response_date or timezone.localdate()).isoformat(),
            "note": note,
        }

    def assert_response_classification(
        self,
        response,
        *,
        expected_order,
        current_number,
    ):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item.response_number for item in response.context["responses"]],
            expected_order,
        )
        self.assertContains(response, "Итоговый", count=1)
        self.assertContains(
            response,
            "Промежуточный",
            count=max(len(expected_order) - 1, 0),
        )
        for number in expected_order:
            is_current = number == current_number
            label = "Итоговый" if is_current else "Промежуточный"
            css_class = (
                "request-response-type-final"
                if is_current
                else "request-response-type-interim"
            )
            self.assertContains(
                response,
                (
                    '<div class="request-response-item-head">'
                    f'<span class="request-response-item-number">№ {number}</span>'
                    f'<span class="request-response-type {css_class}">{label}</span>'
                    "</div>"
                ),
                html=True,
            )


class RequestResponseModelTests(RequestResponseTestMixin, RequestAppTestCase):
    def test_number_is_trimmed_casefolded_and_whitespace_normalized(self):
        response = self.create_response(number="  Answer   AbC-1  ")

        self.assertEqual(response.response_number, "Answer AbC-1")
        self.assertEqual(response.normalized_response_number, "answer abc-1")
        self.assertEqual(response.request, self.request_obj)

    def test_number_is_unique_only_within_its_request(self):
        first = self.create_response(number=" Answer  17 ")
        other_request = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="REQ-2",
            request_date=timezone.localdate() - timedelta(days=9),
            status=NeedStatus.IN_WORK,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_response(number="answer 17")

        second = self.create_response(request_obj=other_request, number="answer 17")
        self.assertEqual(first.normalized_response_number, second.normalized_response_number)
        self.assertNotEqual(first.object_id, second.object_id)

    def test_hard_delete_cascades_responses_for_every_supported_request_model(self):
        request_objects = [
            self.request_obj,
            VehicleRepairRequest.objects.create(
                territorial_organ=self.organ,
                request_number="REPAIR-1",
                request_date=timezone.localdate() - timedelta(days=9),
            ),
            VehicleFuelRequest.objects.create(
                territorial_organ=self.organ,
                request_number="FUEL-1",
                request_date=timezone.localdate() - timedelta(days=8),
            ),
            FireDepartmentRequest.objects.create(
                territorial_organ=self.organ,
                request_number="FIRE-1",
                request_date=timezone.localdate() - timedelta(days=7),
            ),
            AntiTerrorMeasure.objects.create(
                territorial_organ=self.organ,
                request_number="ANTI-1",
                request_date=timezone.localdate() - timedelta(days=6),
            ),
            CitsiziEquipment.objects.create(
                territorial_organ=self.organ,
                request_number="CIT-1",
                request_date=timezone.localdate() - timedelta(days=5),
                equipment_type=EquipmentType.COMMUNICATION,
                quantity=1,
            ),
            BuildingRepairRequest.objects.create(
                territorial_organ=self.organ,
                request_number="BUILD-1",
                request_date=timezone.localdate() - timedelta(days=4),
            ),
        ]

        response_ids = {
            request_obj._meta.label_lower: self.create_response(
                request_obj=request_obj,
                number="ANS-CASCADE",
            ).pk
            for request_obj in request_objects
        }

        for request_obj in request_objects:
            with self.subTest(model=request_obj._meta.label_lower):
                response_id = response_ids[request_obj._meta.label_lower]
                request_obj.delete()
                self.assertFalse(RequestResponse.objects.filter(pk=response_id).exists())


class RequestResponseCrudTests(RequestResponseTestMixin, RequestAppTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.create_status_history_entry(self.request_obj)

    def assert_request_status_unchanged(self, expected_history_count=1):
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, NeedStatus.IN_WORK)
        self.assertEqual(self.status_history(self.request_obj).count(), expected_history_count)

    def test_status_flow_shows_back_button_and_preserves_return_path(self):
        response_obj = self.create_response(number="ANS-NAVIGATION")
        panel_url = f"{self.response_panel_url()}?return_to=status"
        status_url = reverse(
            "record_status_update",
            args=[self.organ.pk, "tmc-requests", self.request_obj.pk],
        )

        direct_panel = self.client.get(
            self.response_panel_url(),
            HTTP_HX_REQUEST="true",
        )
        self.assertNotContains(direct_panel, "Назад к изменению статуса")

        status_panel = self.client.get(panel_url, HTTP_HX_REQUEST="true")
        self.assertTrue(status_panel.context["return_to_status"])
        self.assertContains(status_panel, "Назад к изменению статуса")
        self.assertContains(status_panel, f'hx-get="{status_url}"')
        self.assertContains(status_panel, f'hx-post="{panel_url}"')
        self.assertContains(
            status_panel,
            f'hx-get="{self.response_update_url(response_obj)}?return_to=status"',
        )
        self.assertContains(
            status_panel,
            f'hx-get="{self.response_delete_url(response_obj)}?return_to=status"',
        )

        edit_panel = self.client.get(
            f"{self.response_update_url(response_obj)}?return_to=status",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(
            edit_panel,
            f'hx-get="{self.response_panel_url()}?return_to=status"',
        )
        self.assertContains(
            edit_panel,
            f'hx-post="{self.response_update_url(response_obj)}?return_to=status"',
        )

        delete_panel = self.client.get(
            f"{self.response_delete_url(response_obj)}?return_to=status",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(
            delete_panel,
            f'hx-get="{self.response_panel_url()}?return_to=status"',
        )
        self.assertContains(
            delete_panel,
            f'hx-post="{self.response_delete_url(response_obj)}?return_to=status"',
        )

    def test_create_ignores_parent_ids_from_post_and_keeps_request_in_work(self):
        other_request = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="REQ-OTHER",
            request_date=timezone.localdate() - timedelta(days=5),
            status=NeedStatus.DONE,
        )
        data = self.response_form_data(
            number="ANS-CREATED",
            note="The request still requires additional work.",
        )
        data.update(
            {
                "content_type": self.response_content_type(other_request).pk,
                "object_id": other_request.pk,
            }
        )

        response = self.client.post(
            self.response_panel_url(),
            data,
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        created = RequestResponse.objects.get(response_number="ANS-CREATED")
        self.assertEqual(created.request, self.request_obj)
        self.assertEqual(created.created_by, self.user)
        self.assertEqual(created.updated_by, self.user)
        self.assertFalse(other_request.responses.exists())
        self.assert_request_status_unchanged()

        log = AuditLog.objects.get(event_type=AuditLog.EventType.RESPONSE_CREATED)
        self.assertEqual(log.action, AuditLog.Action.UPDATE)
        self.assertEqual(log.model_name, "TmcRequest")
        self.assertEqual(log.object_id, str(self.request_obj.pk))
        self.assertEqual(log.territorial_organ, self.organ)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.new_values["response_id"], str(created.pk))
        self.assertEqual(log.new_values["response_number"], "ANS-CREATED")
        self.assertFalse(AuditLog.objects.filter(model_name="RequestResponse").exists())
        prepare_log(log, include_status_history=False)
        self.assertIn("ANS-CREATED", log.inline_detail)
        self.assertIn(timezone.localdate().strftime("%d.%m.%Y"), log.inline_detail)
        self.assertIn("requestResponsesChanged", response["HX-Trigger"])

    def test_update_changes_only_response_and_writes_parent_audit(self):
        response_obj = self.create_response(
            number="ANS-OLD",
            response_date=timezone.localdate() - timedelta(days=2),
            note="Old note",
        )
        original_created_by = response_obj.created_by

        response = self.client.post(
            self.response_update_url(response_obj),
            self.response_form_data(
                number="ANS-NEW",
                response_date=timezone.localdate() - timedelta(days=1),
                note="New note",
            ),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        response_obj.refresh_from_db()
        self.assertEqual(response_obj.response_number, "ANS-NEW")
        self.assertEqual(response_obj.note, "New note")
        self.assertEqual(response_obj.created_by, original_created_by)
        self.assertEqual(response_obj.updated_by, self.user)
        self.assert_request_status_unchanged()

        log = AuditLog.objects.get(event_type=AuditLog.EventType.RESPONSE_UPDATED)
        self.assertEqual(log.model_name, "TmcRequest")
        self.assertEqual(log.object_id, str(self.request_obj.pk))
        self.assertEqual(log.old_values["response_number"], "ANS-OLD")
        self.assertEqual(log.new_values["response_number"], "ANS-NEW")
        self.assertEqual(log.old_values["note"], "Old note")
        self.assertEqual(log.new_values["note"], "New note")
        self.assertIn("requestResponsesChanged", response["HX-Trigger"])

    def test_delete_removes_only_selected_response_and_writes_parent_audit(self):
        kept = self.create_response(number="ANS-KEEP")
        deleted = self.create_response(number="ANS-DELETE")

        response = self.client.post(
            self.response_delete_url(deleted),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(RequestResponse.objects.filter(pk=kept.pk).exists())
        self.assertFalse(RequestResponse.objects.filter(pk=deleted.pk).exists())
        self.assert_request_status_unchanged()

        log = AuditLog.objects.get(event_type=AuditLog.EventType.RESPONSE_DELETED)
        self.assertEqual(log.model_name, "TmcRequest")
        self.assertEqual(log.object_id, str(self.request_obj.pk))
        self.assertEqual(log.old_values["response_id"], str(deleted.pk))
        self.assertEqual(log.old_values["response_number"], "ANS-DELETE")
        self.assertEqual(
            log.new_values,
            {"audit_event": AuditLog.EventType.RESPONSE_DELETED},
        )
        self.assertIn("requestResponsesChanged", response["HX-Trigger"])

    def test_duplicate_and_future_date_are_rejected_without_audit(self):
        self.create_response(number="ANS-DUPLICATE")
        invalid_payloads = [
            self.response_form_data(number="  ans-duplicate  "),
            self.response_form_data(
                number="ANS-FUTURE",
                response_date=timezone.localdate() + timedelta(days=1),
            ),
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(
                    self.response_panel_url(),
                    payload,
                    HTTP_HX_REQUEST="true",
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)

        self.assertEqual(RequestResponse.objects.count(), 1)
        self.assertFalse(
            AuditLog.objects.filter(event_type=AuditLog.EventType.RESPONSE_CREATED).exists()
        )
        self.assert_request_status_unchanged()

    def test_create_and_update_forms_do_not_show_manual_response_type(self):
        response_obj = self.create_response(number="ANS-WITHOUT-TYPE")

        create_form = self.client.get(
            self.response_panel_url(),
            HTTP_HX_REQUEST="true",
        )
        update_form = self.client.get(
            self.response_update_url(response_obj),
            HTTP_HX_REQUEST="true",
        )

        for form_response in (create_form, update_form):
            with self.subTest(path=form_response.request["PATH_INFO"]):
                self.assertEqual(form_response.status_code, 200)
                self.assertNotContains(form_response, "Тип ответа")
                self.assertNotContains(form_response, 'name="response_type"', html=False)

    def test_read_only_user_can_view_but_cannot_create_edit_or_delete(self):
        response_obj = self.create_response(number="ANS-READ-ONLY")
        viewer = get_user_model().objects.create_user("response-viewer", password="pass12345")
        profile = UserProfile.objects.create(user=viewer, role=UserProfile.Role.OBSERVER)
        profile.allowed_organs.add(self.organ)
        profile.allowed_departments.add(self.department)
        self.client.force_login(viewer)

        panel = self.client.get(self.response_panel_url(), HTTP_HX_REQUEST="true")

        self.assertEqual(panel.status_code, 200)
        self.assertFalse(panel.context["can_write"])
        self.assertIsNone(panel.context["form"])
        self.assertContains(panel, "ANS-READ-ONLY")
        self.assertNotContains(panel, self.response_update_url(response_obj))
        self.assertNotContains(panel, self.response_delete_url(response_obj))

        write_attempts = [
            (
                self.response_panel_url(),
                self.response_form_data(number="ANS-FORBIDDEN"),
            ),
            (
                self.response_update_url(response_obj),
                self.response_form_data(number="ANS-FORBIDDEN"),
            ),
            (self.response_delete_url(response_obj), {}),
        ]
        for url, data in write_attempts:
            with self.subTest(url=url):
                attempt = self.client.post(url, data, HTTP_HX_REQUEST="true")
                self.assertEqual(attempt.status_code, 404)

        response_obj.refresh_from_db()
        self.assertEqual(response_obj.response_number, "ANS-READ-ONLY")
        self.assertEqual(RequestResponse.objects.count(), 1)

    def test_cross_request_and_cross_organ_response_ids_return_404(self):
        response_obj = self.create_response(number="ANS-PRIVATE")
        same_organ_request = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="REQ-SAME-ORGAN",
            request_date=timezone.localdate() - timedelta(days=4),
        )
        other_organ = TerritorialOrgan.objects.create(
            name="Other response organ",
            order_number=2,
        )
        other_organ_request = TmcRequest.objects.create(
            territorial_organ=other_organ,
            request_number="REQ-OTHER-ORGAN",
            request_date=timezone.localdate() - timedelta(days=3),
        )

        cross_parent_urls = [
            self.response_update_url(response_obj, request_obj=same_organ_request),
            self.response_delete_url(response_obj, request_obj=same_organ_request),
        ]
        for url in cross_parent_urls:
            with self.subTest(url=url):
                self.assertEqual(
                    self.client.get(url, HTTP_HX_REQUEST="true").status_code,
                    404,
                )
                self.assertEqual(
                    self.client.post(
                        url,
                        self.response_form_data(number="ANS-HIJACK"),
                        HTTP_HX_REQUEST="true",
                    ).status_code,
                    404,
                )

        inaccessible_panel = self.response_panel_url(
            request_obj=other_organ_request,
            organ=other_organ,
        )
        self.assertEqual(
            self.client.get(inaccessible_panel, HTTP_HX_REQUEST="true").status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                inaccessible_panel,
                self.response_form_data(number="ANS-HIDDEN"),
                HTTP_HX_REQUEST="true",
            ).status_code,
            404,
        )
        response_obj.refresh_from_db()
        self.assertEqual(response_obj.response_number, "ANS-PRIVATE")


class RequestResponseTableTests(RequestResponseTestMixin, RequestAppTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_table_handles_zero_one_and_many_responses_and_shows_latest_preview(self):
        one_request = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="REQ-ONE",
            request_date=timezone.localdate() - timedelta(days=9),
        )
        many_request = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="REQ-MANY",
            request_date=timezone.localdate() - timedelta(days=8),
        )
        self.create_response(
            request_obj=one_request,
            number="ANS-ONLY",
            response_date=timezone.localdate() - timedelta(days=4),
        )
        oldest = self.create_response(
            request_obj=many_request,
            number="ANS-OLD",
            response_date=timezone.localdate() - timedelta(days=6),
        )
        middle = self.create_response(
            request_obj=many_request,
            number="ANS-MIDDLE",
            response_date=timezone.localdate() - timedelta(days=3),
        )
        newest = self.create_response(
            request_obj=many_request,
            number="ANS-NEWEST",
            response_date=timezone.localdate() - timedelta(days=1),
        )

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Номер заявки / Исходящий")
        self.assertContains(response, 'class="request-reference-divider"', html=False)
        self.assertContains(response, "Ответов нет")
        self.assertContains(response, "ANS-ONLY")
        self.assertContains(response, "ANS-NEWEST")
        self.assertContains(response, "ещё 2")
        self.assertNotContains(response, "ANS-OLD")
        self.assertNotContains(response, "ANS-MIDDLE")

        objects_by_number = {
            obj.request_number: obj for obj in response.context["page"].object_list
        }
        zero = objects_by_number["REQ-1"]
        one = objects_by_number["REQ-ONE"]
        many = objects_by_number["REQ-MANY"]
        self.assertEqual(zero.response_count, 0)
        self.assertIsNone(zero.latest_response)
        self.assertEqual(one.response_count, 1)
        self.assertEqual(one.response_extra_count, 0)
        self.assertEqual(one.latest_response.response_number, "ANS-ONLY")
        self.assertEqual(many.response_count, 3)
        self.assertEqual(many.response_extra_count, 2)
        self.assertEqual(many.latest_response.pk, newest.pk)

        modal = self.client.get(
            self.response_panel_url(request_obj=many_request),
            HTTP_HX_REQUEST="true",
        )
        self.assert_response_classification(
            modal,
            expected_order=["ANS-NEWEST", "ANS-MIDDLE", "ANS-OLD"],
            current_number="ANS-NEWEST",
        )
        for number in ("ANS-NEWEST", "ANS-MIDDLE", "ANS-OLD"):
            self.assertContains(modal, number)

        previous_response_ids = [newest.pk, middle.pk, oldest.pk]
        existing_snapshots = list(
            RequestResponse.objects.filter(
                pk__in=previous_response_ids,
            )
            .order_by("pk")
            .values_list("pk", "updated_at")
        )
        parent_updated_at = many_request.updated_at
        parent_history_count = self.status_history(many_request).count()
        newest_now = self.create_response(
            request_obj=many_request,
            number="ANS-NEWEST-NOW",
            response_date=timezone.localdate(),
        )

        shifted_modal = self.client.get(
            self.response_panel_url(request_obj=many_request),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(shifted_modal.context["responses"][0].pk, newest_now.pk)
        self.assert_response_classification(
            shifted_modal,
            expected_order=[
                "ANS-NEWEST-NOW",
                "ANS-NEWEST",
                "ANS-MIDDLE",
                "ANS-OLD",
            ],
            current_number="ANS-NEWEST-NOW",
        )
        self.assertEqual(
            list(
                RequestResponse.objects.filter(
                    pk__in=previous_response_ids,
                )
                .order_by("pk")
                .values_list("pk", "updated_at")
            ),
            existing_snapshots,
        )
        many_request.refresh_from_db()
        self.assertEqual(many_request.status, NeedStatus.IN_WORK)
        self.assertEqual(many_request.updated_at, parent_updated_at)
        self.assertEqual(
            self.status_history(many_request).count(),
            parent_history_count,
        )

    def test_changing_response_date_reassigns_current_final_classification(self):
        previous = self.create_response(
            number="ANS-PREVIOUS",
            response_date=timezone.localdate() - timedelta(days=4),
        )
        current = self.create_response(
            number="ANS-CURRENT",
            response_date=timezone.localdate() - timedelta(days=1),
        )
        initial_modal = self.client.get(
            self.response_panel_url(),
            HTTP_HX_REQUEST="true",
        )
        self.assert_response_classification(
            initial_modal,
            expected_order=["ANS-CURRENT", "ANS-PREVIOUS"],
            current_number="ANS-CURRENT",
        )

        updated_modal = self.client.post(
            self.response_update_url(current),
            self.response_form_data(
                number=current.response_number,
                response_date=timezone.localdate() - timedelta(days=7),
            ),
            HTTP_HX_REQUEST="true",
        )

        self.assert_response_classification(
            updated_modal,
            expected_order=["ANS-PREVIOUS", "ANS-CURRENT"],
            current_number="ANS-PREVIOUS",
        )
        previous.refresh_from_db()
        self.assertEqual(
            updated_modal.context["responses"][0].pk,
            previous.pk,
        )

    def test_deleting_current_final_promotes_previous_response(self):
        previous = self.create_response(
            number="ANS-PREVIOUS",
            response_date=timezone.localdate() - timedelta(days=4),
        )
        current = self.create_response(
            number="ANS-CURRENT",
            response_date=timezone.localdate() - timedelta(days=1),
        )
        initial_modal = self.client.get(
            self.response_panel_url(),
            HTTP_HX_REQUEST="true",
        )
        self.assert_response_classification(
            initial_modal,
            expected_order=["ANS-CURRENT", "ANS-PREVIOUS"],
            current_number="ANS-CURRENT",
        )

        after_delete = self.client.post(
            self.response_delete_url(current),
            HTTP_HX_REQUEST="true",
        )

        self.assert_response_classification(
            after_delete,
            expected_order=["ANS-PREVIOUS"],
            current_number="ANS-PREVIOUS",
        )
        self.assertEqual(after_delete.context["responses"][0].pk, previous.pk)
        self.assertNotContains(after_delete, "ANS-CURRENT")

    def test_same_response_date_uses_created_at_then_pk_as_stable_tiebreakers(self):
        shared_date = timezone.localdate() - timedelta(days=1)
        lower_pk = self.create_response(
            number="ANS-LOWER-PK",
            response_date=shared_date,
        )
        higher_pk = self.create_response(
            number="ANS-HIGHER-PK",
            response_date=shared_date,
        )
        base_created_at = timezone.now() - timedelta(hours=1)
        RequestResponse.objects.filter(pk=lower_pk.pk).update(
            created_at=base_created_at + timedelta(seconds=1),
        )
        RequestResponse.objects.filter(pk=higher_pk.pk).update(
            created_at=base_created_at,
        )

        created_at_modal = self.client.get(
            self.response_panel_url(),
            HTTP_HX_REQUEST="true",
        )
        self.assert_response_classification(
            created_at_modal,
            expected_order=["ANS-LOWER-PK", "ANS-HIGHER-PK"],
            current_number="ANS-LOWER-PK",
        )

        RequestResponse.objects.filter(
            pk__in=[lower_pk.pk, higher_pk.pk],
        ).update(created_at=base_created_at)
        pk_tiebreak_modal = self.client.get(
            self.response_panel_url(),
            HTTP_HX_REQUEST="true",
        )
        self.assert_response_classification(
            pk_tiebreak_modal,
            expected_order=["ANS-HIGHER-PK", "ANS-LOWER-PK"],
            current_number="ANS-HIGHER-PK",
        )
        self.assertGreater(higher_pk.pk, lower_pk.pk)

    def test_tmc_multi_item_row_renders_one_rowspanned_response_cell(self):
        TmcRequestItem.objects.create(
            request=self.request_obj,
            name="Paper",
            quantity=2,
            unit="packs",
        )
        TmcRequestItem.objects.create(
            request=self.request_obj,
            name="Folders",
            quantity=3,
            unit="pcs",
        )
        self.create_response(number="ANS-ROWSPAN")

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'rowspan="2" class="tmc-request-cell request-reference-table-cell',
            html=False,
        )
        self.assertContains(
            response,
            f'hx-get="{self.response_panel_url()}"',
            count=1,
            html=False,
        )
        self.assertContains(response, "ANS-ROWSPAN")

    def test_search_matches_any_response_and_does_not_duplicate_request_rows(self):
        matching = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="REQ-MATCHING",
            request_date=timezone.localdate() - timedelta(days=8),
        )
        excluded = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="REQ-EXCLUDED",
            request_date=timezone.localdate() - timedelta(days=7),
        )
        TmcRequestItem.objects.create(
            request=matching,
            name="First item",
            quantity=1,
            unit="pcs",
        )
        TmcRequestItem.objects.create(
            request=matching,
            name="Second item",
            quantity=1,
            unit="pcs",
        )
        self.create_response(
            request_obj=matching,
            number="ARCHIVE-ONE",
            note="shared-search-token",
            response_date=timezone.localdate() - timedelta(days=5),
        )
        self.create_response(
            request_obj=matching,
            number="ARCHIVE-TWO",
            note="shared-search-token",
            response_date=timezone.localdate() - timedelta(days=1),
        )
        self.create_response(
            request_obj=excluded,
            number="UNRELATED",
            note="another note",
        )

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
            {"q": "shared-search-token"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertEqual(
            [obj.pk for obj in response.context["page"].object_list],
            [matching.pk],
        )
        self.assertContains(response, matching.request_number)
        self.assertNotContains(response, excluded.request_number)
        self.assertContains(response, "ARCHIVE-TWO")


class RequestResponseLifecycleTests(RequestResponseTestMixin, RequestAppTestCase):
    def test_soft_delete_preserves_responses_and_restore_makes_them_visible_again(self):
        response_obj = self.create_response(number="ANS-PERSISTENT")
        self.client.force_login(self.user)

        deleted = self.client.post(
            reverse(
                "record_delete",
                args=[self.organ.pk, "tmc-requests", self.request_obj.pk],
            ),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(deleted.status_code, 200)
        self.request_obj.refresh_from_db()
        self.assertTrue(self.request_obj.is_deleted)
        self.assertEqual(self.request_obj.status, NeedStatus.IN_WORK)
        self.assertTrue(RequestResponse.objects.filter(pk=response_obj.pk).exists())
        self.assertEqual(
            self.client.get(
                self.response_panel_url(),
                HTTP_HX_REQUEST="true",
            ).status_code,
            404,
        )

        restored = self.client.post(
            reverse(
                "admin_trash_restore_request",
                kwargs={"table_key": "tmc-requests", "pk": self.request_obj.pk},
            ),
        )

        self.assertEqual(restored.status_code, 302)
        self.request_obj.refresh_from_db()
        self.assertFalse(self.request_obj.is_deleted)
        self.assertEqual(self.request_obj.status, NeedStatus.IN_WORK)
        self.assertTrue(RequestResponse.objects.filter(pk=response_obj.pk).exists())
        panel = self.client.get(
            self.response_panel_url(),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(panel.status_code, 200)
        self.assertContains(panel, "ANS-PERSISTENT")


class RequestResponseAdminSurfaceTests(RequestResponseTestMixin, RequestAppTestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(
            "response-admin",
            password="pass12345",
        )
        UserProfile.objects.create(user=self.admin, role=UserProfile.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_admin_registry_searches_all_responses_and_detail_lists_them(self):
        self.create_response(
            number="ANS-ARCHIVE",
            response_date=timezone.localdate() - timedelta(days=3),
            note="admin-response-search-token",
        )
        self.create_response(
            number="ANS-LATEST",
            response_date=timezone.localdate() - timedelta(days=1),
        )

        registry = self.client.get(
            reverse("admin_requests_panel"),
            {"q": "admin-response-search-token"},
        )

        self.assertEqual(registry.status_code, 200)
        self.assertEqual(registry.context["page"].paginator.count, 1)
        row = registry.context["page"].object_list[0]
        self.assertEqual(row["number"], self.request_obj.request_number)
        self.assertEqual(row["response_count"], 2)
        self.assertEqual(row["latest_response_number"], "ANS-LATEST")
        self.assertContains(registry, "Номер заявки / Исходящий")
        self.assertContains(registry, "ANS-LATEST")
        self.assertContains(registry, "ещё 1")

        detail = self.client.get(
            reverse(
                "admin_request_detail",
                kwargs={"table_key": "tmc-requests", "pk": self.request_obj.pk},
            )
        )

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context["response_count"], 2)
        self.assertEqual(
            [item.response_number for item in detail.context["responses"]],
            ["ANS-LATEST", "ANS-ARCHIVE"],
        )
        self.assertContains(detail, "Ответы на заявку")
        self.assertContains(detail, "admin-response-search-token")
        self.assertContains(detail, "не изменяют статус заявки")

    def test_trash_keeps_response_reference_off_non_request_records(self):
        state_record = VehicleInventory.objects.create(
            territorial_organ=self.organ,
            state_date=timezone.localdate(),
            required_count=1,
            available_count=1,
            broken_count=0,
            writeoff_count=0,
            is_deleted=True,
            updated_by=self.admin,
        )

        trash = self.client.get(
            reverse("admin_trash_panel"),
            {"section": "requests"},
        )

        self.assertEqual(trash.status_code, 200)
        row = next(
            item
            for item in trash.context["request_page"].object_list
            if item["pk"] == state_record.pk and item["table_key"] == "vehicle-inventory"
        )
        self.assertFalse(row["has_request_reference"])
        self.assertNotContains(trash, "admin-request-reference-divider")
        self.assertNotContains(trash, "Ответов нет")


class RequestResponsePerformanceTests(RequestResponseTestMixin, RequestAppTestCase):
    def test_latest_response_summaries_are_loaded_in_one_query_for_many_requests(self):
        requests = [self.request_obj]
        for index in range(15):
            request_obj = TmcRequest.objects.create(
                territorial_organ=self.organ,
                request_number=f"REQ-PERF-{index:02d}",
                request_date=timezone.localdate() - timedelta(days=index),
            )
            requests.append(request_obj)
            self.create_response(
                request_obj=request_obj,
                number=f"ANS-PERF-{index:02d}",
                response_date=timezone.localdate() - timedelta(days=index),
            )
            self.create_response(
                request_obj=request_obj,
                number=f"ANS-PERF-{index:02d}-OLD",
                response_date=timezone.localdate() - timedelta(days=index + 1),
            )

        self.response_content_type()
        with CaptureQueriesContext(connection) as queries:
            attached = attach_request_response_summaries(requests, TmcRequest)
            values = [
                (
                    request_obj.response_count,
                    request_obj.latest_response.response_number
                    if request_obj.latest_response
                    else "",
                )
                for request_obj in attached
            ]

        self.assertLessEqual(len(queries.captured_queries), 1)
        self.assertEqual(values[0], (0, ""))
        self.assertTrue(all(count == 2 for count, _number in values[1:]))


class RequestResponseExportTests(RequestResponseTestMixin, RequestAppTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        TmcRequestItem.objects.create(
            request=self.request_obj,
            name="Paper",
            quantity=1,
            unit="pack",
        )
        self.create_response(
            number="ANS-OLDER",
            response_date=timezone.localdate() - timedelta(days=2),
        )
        self.create_response(
            number="ANS-NEWER",
            response_date=timezone.localdate() - timedelta(days=1),
        )

    def expected_multiline_reference(self):
        newer_date = (timezone.localdate() - timedelta(days=1)).strftime("%d.%m.%Y")
        older_date = (timezone.localdate() - timedelta(days=2)).strftime("%d.%m.%Y")
        return (
            f"REQ-1\n"
            f"ANS-NEWER от {newer_date}\n"
            f"ANS-OLDER от {older_date}"
        )

    def expected_single_line_reference(self):
        return self.expected_multiline_reference().replace(
            "\nANS-NEWER",
            " / ANS-NEWER",
        ).replace(
            "\nANS-OLDER",
            "; ANS-OLDER",
        )

    def test_tmc_csv_exports_all_responses_in_one_cell_newest_first(self):
        response = self.client.get(
            reverse(
                "export_table",
                args=[self.organ.pk, "tmc-requests", "csv"],
            )
        )

        rows = list(
            csv.reader(
                self.response_bytes(response).decode("utf-8-sig").splitlines()
            )
        )
        self.assertEqual(rows[0][0], "Номер заявки / Исходящий")
        self.assertEqual(rows[1][0], self.expected_single_line_reference())

    def test_tmc_xlsx_exports_all_responses_in_one_wrapped_cell_newest_first(self):
        response = self.client.get(
            reverse(
                "export_table",
                args=[self.organ.pk, "tmc-requests", "xlsx"],
            )
        )

        sheet = self.response_workbook(response).active
        self.assertEqual(sheet["C2"].value, "Номер заявки / Исходящий")
        self.assertEqual(sheet["C3"].value, self.expected_multiline_reference())
        self.assertTrue(sheet["C3"].alignment.wrap_text)

    def test_generic_csv_and_styled_xlsx_export_the_same_multi_response_contract(self):
        request_obj = VehicleRepairRequest.objects.create(
            territorial_organ=self.organ,
            request_number="REPAIR-EXPORT",
            request_date=timezone.localdate() - timedelta(days=10),
        )
        self.create_response(
            request_obj=request_obj,
            number="REPAIR-OLD",
            response_date=timezone.localdate() - timedelta(days=3),
        )
        self.create_response(
            request_obj=request_obj,
            number="REPAIR-NEW",
            response_date=timezone.localdate() - timedelta(days=1),
        )
        newest_date = (timezone.localdate() - timedelta(days=1)).strftime("%d.%m.%Y")
        oldest_date = (timezone.localdate() - timedelta(days=3)).strftime("%d.%m.%Y")
        multiline = (
            f"REPAIR-EXPORT\n"
            f"REPAIR-NEW от {newest_date}\n"
            f"REPAIR-OLD от {oldest_date}"
        )
        single_line = multiline.replace(
            "\nREPAIR-NEW",
            " / REPAIR-NEW",
        ).replace(
            "\nREPAIR-OLD",
            "; REPAIR-OLD",
        )

        csv_response = self.client.get(
            reverse(
                "export_table",
                args=[self.organ.pk, "vehicle-repair", "csv"],
            )
        )
        csv_rows = list(
            csv.reader(
                self.response_bytes(csv_response).decode("utf-8-sig").splitlines()
            )
        )
        self.assertEqual(csv_rows[0][0], "Номер заявки / Исходящий")
        self.assertEqual(csv_rows[1][0], single_line)

        xlsx_response = self.client.get(
            reverse(
                "export_table",
                args=[self.organ.pk, "vehicle-repair", "xlsx"],
            )
        )
        sheet = self.response_workbook(xlsx_response).active
        self.assertEqual(sheet["A1"].value, "Номер заявки / Исходящий")
        self.assertEqual(sheet["A2"].value, multiline)
        self.assertTrue(sheet["A2"].alignment.wrap_text)
