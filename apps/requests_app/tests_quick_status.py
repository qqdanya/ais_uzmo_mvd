from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.audit.models import AuditLog
from apps.directory.models import Department
from apps.requests_app.models import NeedStatus, TmcRequest, TmcRequestItem, VehicleRepairRequest

from .tests_base import RequestAppTestCase


class QuickStatusUpdateTests(RequestAppTestCase):
    def setUp(self):
        super().setUp()
        self.request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="QS-1",
            request_date=timezone.localdate(),
            status=NeedStatus.IN_WORK,
            created_by=self.user,
            updated_by=self.user,
        )
        TmcRequestItem.objects.create(request=self.request_obj, name="Бумага", quantity=1, unit="пач.")
        self.url = reverse(
            "record_status_update",
            args=[self.organ.pk, "tmc-requests", self.request_obj.pk],
        )
        self.client.login(username="operator", password="pass12345")

    def test_writable_table_renders_status_as_quick_action(self):
        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))

        self.assertContains(response, "status-badge-action")
        self.assertContains(response, self.url)
        self.assertContains(response, "Изменить статус заявки")

    def test_quick_status_modal_opens_with_current_status(self):
        response = self.client.get(self.url, HTTP_HX_REQUEST="true")
        responses_url = reverse(
            "request_responses",
            args=[self.organ.pk, "tmc-requests", self.request_obj.pk],
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Изменение статуса исполнения заявки")
        self.assertContains(response, "статус исполнения заявки")
        self.assertContains(response, 'type="radio"', count=3)
        self.assertContains(response, "quick-status-options")
        self.assertContains(response, "Добавить ответ")
        self.assertContains(response, "Ответ сохраняется отдельно и не меняет статус заявки.")
        self.assertContains(response, f'hx-get="{responses_url}?return_to=status"')
        self.assertContains(response, 'hx-target="#modal-content"')
        self.assertEqual(response.context["form"].initial["status"], NeedStatus.IN_WORK)
        self.assertIsNone(response.context["form"].initial.get("completed_at"))

    def test_quick_status_modal_preserves_terminal_status_and_date(self):
        self.request_obj.status = NeedStatus.REJECTED
        self.request_obj.due_date = timezone.localdate() - timedelta(days=2)
        self.request_obj.save(update_fields=["status", "due_date"])

        response = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.context["form"].initial["status"], NeedStatus.REJECTED)
        self.assertEqual(response.context["form"].initial["completed_at"], self.request_obj.due_date)
        self.assertContains(response, "Дата отклонения")

    def test_quick_status_change_updates_date_history_and_audit(self):
        completed_at = timezone.localdate() - timedelta(days=1)

        response = self.client.post(
            f"{self.url}?q=QS-1",
            {"status": NeedStatus.DONE, "completed_at": completed_at.isoformat()},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("HX-Trigger", response)
        self.assertContains(response, "QS-1")
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, NeedStatus.DONE)
        self.assertEqual(self.request_obj.due_date, completed_at)

        history = self.status_history(self.request_obj).get(old_status=NeedStatus.IN_WORK, new_status=NeedStatus.DONE)
        self.assertEqual(history.completed_at, completed_at)
        self.assertEqual(history.changed_by, self.user)
        self.assertEqual(history.note, "Быстрое изменение статуса")

        audit = AuditLog.objects.get(event_type=AuditLog.EventType.STATUS_CHANGED, object_id=str(self.request_obj.pk))
        self.assertEqual(audit.old_values["status"], NeedStatus.IN_WORK)
        self.assertEqual(audit.new_values["status"], NeedStatus.DONE)
        self.assertEqual(audit.new_values["due_date"], completed_at.isoformat())

    def test_rejection_requires_date_and_rejects_future_date(self):
        response = self.client.post(
            self.url,
            {"status": NeedStatus.REJECTED, "completed_at": ""},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Retarget"], "#modal-content")
        self.assertContains(response, "Укажите дату отклонения")
        self.assertContains(response, "Дата отклонения")

        future_date = timezone.localdate() + timedelta(days=1)
        response = self.client.post(
            self.url,
            {"status": NeedStatus.REJECTED, "completed_at": future_date.isoformat()},
            HTTP_HX_REQUEST="true",
        )

        self.assertContains(response, "Дата не может быть позже сегодняшней")
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, NeedStatus.IN_WORK)

    def test_return_to_work_clears_completion_date(self):
        self.request_obj.status = NeedStatus.DONE
        self.request_obj.due_date = timezone.localdate()
        self.request_obj.save(update_fields=["status", "due_date"])

        response = self.client.post(
            self.url,
            {"status": NeedStatus.IN_WORK, "completed_at": timezone.localdate().isoformat()},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, NeedStatus.IN_WORK)
        self.assertIsNone(self.request_obj.due_date)
        history = self.status_history(self.request_obj).get(old_status=NeedStatus.DONE, new_status=NeedStatus.IN_WORK)
        self.assertIsNone(history.completed_at)

    def test_quick_status_uses_completed_at_for_regular_request_tables(self):
        transport = Department.objects.create(name="Транспорт", slug="transport", order_number=2)
        self.user.profile.allowed_departments.add(transport)
        self.user.profile.writable_departments.add(transport)
        request_obj = VehicleRepairRequest.objects.create(
            territorial_organ=self.organ,
            request_number="VR-QS-1",
            request_date=timezone.localdate(),
            status=NeedStatus.IN_WORK,
        )
        url = reverse(
            "record_status_update",
            args=[self.organ.pk, "vehicle-repair", request_obj.pk],
        )

        response = self.client.post(
            url,
            {"status": NeedStatus.REJECTED, "completed_at": timezone.localdate().isoformat()},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        request_obj.refresh_from_db()
        self.assertEqual(request_obj.status, NeedStatus.REJECTED)
        self.assertEqual(request_obj.completed_at, timezone.localdate())
        history = self.status_history(request_obj).get(old_status=NeedStatus.IN_WORK, new_status=NeedStatus.REJECTED)
        self.assertEqual(history.completed_at, timezone.localdate())

    def test_observer_cannot_open_quick_status_action(self):
        self.user.profile.role = UserProfile.Role.OBSERVER
        self.user.profile.save(update_fields=["role"])

        response = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 404)
