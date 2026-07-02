from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.directory.models import Department, TerritorialOrgan
from apps.requests_app.models import RequestStatusHistory, TmcRequest

from .models import AuditLog


class AuditLogTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user("admin", password="pass12345")
        UserProfile.objects.create(user=self.admin, role=UserProfile.Role.ADMIN)
        self.operator = User.objects.create_user("operator", password="pass12345")
        UserProfile.objects.create(user=self.operator, role=UserProfile.Role.OPERATOR)
        self.organ = TerritorialOrgan.objects.create(name="Test organ", order_number=1)
        Department.objects.create(name="Обеспечение товарно-материальными ценностями", slug="tmc", order_number=1)

    def create_log(self, **kwargs):
        defaults = {
            "user": self.operator,
            "action": AuditLog.Action.UPDATE,
            "model_name": "TmcRequest",
            "object_id": "10",
            "object_repr": 'Изменена запись "Заявка ТМЦ № 10/TMC"',
            "old_values": {"comment": "Old description", "status": "in_work"},
            "new_values": {"comment": "New description", "status": "done"},
            "territorial_organ": self.organ,
            "ip_address": "127.0.0.1",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        }
        defaults.update(kwargs)
        return AuditLog.objects.create(**defaults)

    def test_audit_log_uses_admin_layout_filters_and_pagination(self):
        for index in range(30):
            self.create_log(object_id=str(index), object_repr=f"Запись {index}")
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"), {"action": AuditLog.Action.UPDATE})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Журнал действий")
        self.assertContains(response, "audit-filters")
        self.assertContains(response, "audit-table")
        self.assertNotContains(response, "Поиск в журнале событий")
        self.assertContains(response, "записей найдено")
        self.assertContains(response, "Google Chrome / Windows")
        self.assertContains(response, "Открыть")
        self.assertContains(response, "Событие")
        self.assertContains(response, "Платформа")
        self.assertContains(response, "Подробности")
        self.assertContains(response, "Все территориальные органы")
        self.assertContains(response, "Редактирование")
        self.assertContains(response, 'class="pagination-jump"')
        self.assertContains(response, "audit-detail-button")
        self.assertContains(response, "Страницы журнала действий")
        self.assertContains(response, "Сбросить")
        self.assertContains(response, "Запись отредактирована")
        self.assertEqual(len(response.context["logs"]), 25)

    def test_admin_index_links_to_full_audit_log(self):
        User = get_user_model()
        staff = User.objects.create_superuser("staff", password="pass12345")
        UserProfile.objects.create(user=staff, role=UserProfile.Role.ADMIN)
        self.client.login(username="staff", password="pass12345")

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Журнал действий")
        self.assertContains(response, reverse("audit_log"))

    def test_audit_log_hides_reset_without_filters_and_uses_oldest_default_date(self):
        old_log = self.create_log(object_repr="Old")
        AuditLog.objects.filter(pk=old_log.pk).update(created_at=timezone.datetime(2026, 6, 1, tzinfo=timezone.get_current_timezone()))
        self.create_log(object_repr="Fresh")
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"))

        self.assertContains(response, 'name="date_from" value="2026-06-01"')
        self.assertContains(response, "Old")
        self.assertContains(response, "Fresh")
        self.assertNotContains(response, "Сбросить")

    def test_audit_detail_shows_changed_values_and_user_agent(self):
        log = self.create_log()
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_detail", args=[log.pk]), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Подробности действия")
        self.assertContains(response, "Описание")
        self.assertContains(response, "Old description")
        self.assertContains(response, "New description")
        self.assertContains(response, "Изменена запись «Заявка ТМЦ № 10/TMC»")
        self.assertContains(response, "Google Chrome / Windows")
        self.assertContains(response, "User-Agent")
        self.assertNotContains(response, "ID: 10")

    def test_audit_detail_displays_foreign_keys_dates_and_request_history(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="55/TMC",
            request_date="2026-07-01",
            status="done",
            comment="Бумага",
        )
        RequestStatusHistory.objects.create(
            content_type=ContentType.objects.get_for_model(TmcRequest),
            object_id=request_obj.pk,
            old_status="in_work",
            new_status="done",
            completed_at="2026-07-02",
            changed_by=self.operator,
        )
        log = self.create_log(
            object_id=str(request_obj.pk),
            object_repr='Изменена запись "Заявка ТМЦ № 55/TMC"',
            old_values={"territorial_organ": self.organ.pk, "request_date": "2026-07-01", "status": "in_work"},
            new_values={"territorial_organ": self.organ.pk, "request_date": "2026-07-02", "status": "done"},
        )
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_detail", args=[log.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, "Test organ")
        self.assertContains(response, "01.07.2026")
        self.assertContains(response, "02.07.2026")
        self.assertNotContains(response, ">1<", html=False)
        self.assertContains(response, "История изменений заявки")
        self.assertContains(response, "В работе")
        self.assertContains(response, "Исполнена")

    def test_audit_detail_for_login_does_not_show_empty_changes_notice(self):
        log = self.create_log(
            action=AuditLog.Action.LOGIN,
            model_name="",
            object_id="",
            object_repr="",
            old_values=None,
            new_values=None,
        )
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_detail", args=[log.pk]), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Платформа и адрес")
        self.assertContains(response, "Вход в систему")
        self.assertNotContains(response, "Территориальный орган")
        self.assertNotContains(response, "Детальные изменения не зафиксированы")
        self.assertNotContains(response, "Измененные поля")

    def test_audit_detail_hides_empty_change_section_for_object_action(self):
        log = self.create_log(old_values={}, new_values={})
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_detail", args=[log.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, "Объект")
        self.assertNotContains(response, "Измененные поля")
        self.assertNotContains(response, "Дополнительные параметры по этому действию отсутствуют")

    def test_audit_empty_result_keeps_panel_rows_compact(self):
        self.create_log(object_repr="Visible")
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"), {"action": AuditLog.Action.DELETE})

        self.assertContains(response, "Записи журнала не найдены")
        self.assertContains(response, "audit-panel")

    def test_photo_description_event_is_human_readable(self):
        log = self.create_log(
            model_name="TerritorialOrganPhoto",
            object_repr='Изменена фотография "building.jpg"',
            old_values={"description": ""},
            new_values={"description": "Фасад здания"},
        )
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"))

        self.assertContains(response, "Добавлено описание фотографии")
        self.assertContains(response, "Изменена фотография «building.jpg»")

    def test_audit_event_summaries_use_clear_names(self):
        self.create_log(action=AuditLog.Action.DELETE, object_repr="Deleted request")
        self.create_log(
            model_name="TerritorialOrganPhotoFolder",
            object_repr='Изменена запись "Folder"',
            old_values={"name": "Old"},
            new_values={"name": "New"},
        )
        self.create_log(
            object_repr="Status request",
            old_values={"status": "in_work"},
            new_values={"audit_event": "request_status_changed", "status": "done"},
        )
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"))

        self.assertContains(response, "Запись удалена")
        self.assertContains(response, "Папка фотографий переименована")
        self.assertContains(response, "Изменен статус заявки")

    def test_my_audit_log_shows_only_current_user_without_user_and_department_filters(self):
        self.create_log(user=self.operator, object_repr="Operator action")
        self.create_log(user=self.admin, object_repr="Admin action")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("my_audit_log"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Мои действия")
        self.assertContains(response, "Operator action")
        self.assertNotContains(response, "Admin action")
        self.assertNotContains(response, "Все пользователи")
        self.assertNotContains(response, "Все отделы")
        self.assertNotContains(response, "<th>Пользователь</th>", html=True)

    def test_audit_log_filters_by_date_and_action(self):
        old_log = self.create_log(action=AuditLog.Action.CREATE, object_repr="Old")
        AuditLog.objects.filter(pk=old_log.pk).update(created_at=timezone.datetime(2026, 6, 1, tzinfo=timezone.get_current_timezone()))
        self.create_log(action=AuditLog.Action.DELETE, object_repr="Fresh")
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"), {"action": AuditLog.Action.DELETE, "date_from": "2026-07-01"})

        self.assertContains(response, "Fresh")
        self.assertNotContains(response, "Old")

    def test_audit_log_filters_accept_multiple_checkbox_values(self):
        self.create_log(action=AuditLog.Action.CREATE, object_repr="Created")
        self.create_log(action=AuditLog.Action.UPDATE, object_repr="Updated")
        self.create_log(action=AuditLog.Action.DELETE, object_repr="Deleted")
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(
            reverse("audit_log"),
            {"action": [AuditLog.Action.CREATE, AuditLog.Action.UPDATE]},
        )

        self.assertContains(response, "Created")
        self.assertContains(response, "Updated")
        self.assertNotContains(response, "Deleted")
        self.assertContains(response, 'name="action" value="create" checked')
        self.assertContains(response, 'name="action" value="update" checked')

    def test_audit_log_filters_by_department_and_object_type(self):
        self.create_log(model_name="TmcRequest", object_repr="TMC request")
        self.create_log(model_name="TerritorialOrganPhoto", object_repr="Photo item")
        self.create_log(model_name="TerritorialOrganPhotoFolder", object_repr="Folder item")
        self.client.login(username="admin", password="pass12345")

        department_response = self.client.get(reverse("audit_log"), {"department": "tmc"})
        self.assertContains(department_response, "TMC request")
        self.assertNotContains(department_response, "Photo item")
        self.assertNotContains(department_response, "Folder item")
        self.assertContains(department_response, 'name="department" value="tmc" checked')
        self.assertNotContains(department_response, 'name="department" value="photos"')

        object_response = self.client.get(reverse("audit_log"), {"object": "folder"})
        self.assertContains(object_response, "Folder item")
        self.assertNotContains(object_response, "TMC request")
        self.assertNotContains(object_response, "Photo item")
        self.assertContains(object_response, 'name="object" value="folder" checked')
