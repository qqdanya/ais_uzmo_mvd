from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
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
        self.operator_profile = UserProfile.objects.create(user=self.operator, role=UserProfile.Role.OPERATOR)
        self.organ = TerritorialOrgan.objects.create(name="Test organ", order_number=1)
        self.department = Department.objects.create(name="Обеспечение товарно-материальными ценностями", slug="tmc", order_number=1)
        self.operator_profile.allowed_departments.add(self.department)
        self.operator_profile.allowed_organs.add(self.organ)

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
        self.assertContains(response, "data-date-range-picker")
        self.assertContains(response, "audit-date-picker")
        self.assertContains(response, "data-admin-multiselect")
        self.assertContains(response, "data-admin-multiselect-select-all")
        self.assertContains(response, "data-admin-multiselect-clear")
        self.assertNotContains(response, "Поиск в журнале событий")
        self.assertContains(response, "записей найдено")
        self.assertContains(response, "Google Chrome / Windows")
        self.assertContains(response, "Открыть")
        self.assertContains(response, "Событие")
        self.assertContains(response, "Платформа")
        self.assertContains(response, "Подробности")
        self.assertNotContains(response, "<th>Действие</th>", html=True)
        self.assertContains(response, "Все территориальные органы")
        self.assertContains(response, "Редактирование")
        self.assertContains(response, 'class="pagination-jump"')
        self.assertContains(response, "audit-detail-button")
        self.assertContains(response, "Страницы журнала действий")
        self.assertContains(response, "Сбросить")
        self.assertContains(response, "Заявка отредактирована")
        self.assertEqual(len(response.context["logs"]), 25)

    def test_audit_log_query_count_has_a_ceiling(self):
        # Measured 39 queries for 30 seeded log entries (all-time view, since
        # the default 25-per-page result set is what actually gets rendered
        # and prepare_log() resolves each row's user/organ/model references).
        for index in range(30):
            self.create_log(object_id=str(index), object_repr=f"Запись {index}")
        self.client.login(username="admin", password="pass12345")

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("audit_log"), {"date_from": "", "date_to": ""})

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries.captured_queries), 55)

    def test_audit_log_does_not_reload_user_profile_per_row(self):
        # Regression test: templates/audit_log.html calls log.user|display_name
        # per row, which reads user.profile - without user__profile in
        # select_related, that's one extra accounts_userprofile SELECT per
        # row. Other profile queries happen on this page regardless of row
        # count (the logged-in admin's own profile, throttled presence
        # tracking, the user-filter dropdown) - isolate the one query that
        # actually joins audit_auditlog to accounts_userprofile, which must
        # stay a single joined SELECT no matter how many rows are on the page.
        for index in range(30):
            self.create_log(object_id=str(index), object_repr=f"Запись {index}")
        self.client.login(username="admin", password="pass12345")

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("audit_log"), {"date_from": "", "date_to": ""})

        self.assertEqual(response.status_code, 200)
        joined_profile_queries = [
            q for q in queries.captured_queries if "audit_auditlog" in q["sql"].lower() and "accounts_userprofile" in q["sql"].lower()
        ]
        self.assertEqual(len(joined_profile_queries), 1)

    def test_admin_index_links_to_full_audit_log(self):
        User = get_user_model()
        staff = User.objects.create_superuser("staff", password="pass12345")
        UserProfile.objects.create(user=staff, role=UserProfile.Role.ADMIN)
        self.client.login(username="staff", password="pass12345")

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Журнал действий")
        self.assertContains(response, reverse("audit_log"))

    def test_audit_log_defaults_to_recent_window_and_hides_reset_without_filters(self):
        old_log = self.create_log(object_repr="Old")
        AuditLog.objects.filter(pk=old_log.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=45)
        )
        self.create_log(object_repr="Fresh")
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"))

        expected_default = (timezone.localdate() - timezone.timedelta(days=30)).isoformat()
        self.assertContains(response, f'name="date_from" value="{expected_default}"')
        self.assertNotContains(response, "Old")
        self.assertContains(response, "Fresh")
        self.assertNotContains(response, "Сбросить")
        self.assertContains(response, "За всё время")

    def test_audit_log_all_time_link_surfaces_older_entries_without_scanning_by_default(self):
        old_log = self.create_log(object_repr="Old")
        AuditLog.objects.filter(pk=old_log.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=45)
        )
        self.create_log(object_repr="Fresh")
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"), {"date_from": "", "date_to": ""})

        self.assertContains(response, "Old")
        self.assertContains(response, "Fresh")
        self.assertContains(response, "Сбросить")
        self.assertNotContains(response, "За всё время")

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
        self.assertNotContains(response, "Заявка тмц")
        self.assertContains(response, "Google Chrome / Windows")
        self.assertContains(response, "Сведения о браузере")
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
        self.assertContains(response, "История изменений статуса заявки")
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

    def test_audit_detail_hides_folder_author_department_field(self):
        log = self.create_log(
            action=AuditLog.Action.CREATE,
            model_name="TerritorialOrganPhotoFolder",
            object_repr='Создана папка фотографий "333"',
            new_values={"name": "333", "created_department": str(self.department.pk)},
        )
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_detail", args=[log.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, "Папка фотографий «333»")
        self.assertContains(response, '<strong class="audit-action audit-action-create">Папка фотографий создана</strong>', html=True)
        self.assertNotContains(response, '<span class="audit-action audit-action-create">Папка фотографий</span>', html=True)
        self.assertContains(response, "Наименование")
        self.assertNotContains(response, "Отдел автора")

    def test_audit_detail_hides_photo_author_department_field(self):
        log = self.create_log(
            action=AuditLog.Action.CREATE,
            model_name="TerritorialOrganPhoto",
            object_repr='Создана фотография "building.jpg"',
            new_values={"original_filename": "building.jpg", "created_department": str(self.department.pk)},
        )
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_detail", args=[log.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, "Фотография «building.jpg»")
        self.assertContains(response, "Фотография добавлена")
        self.assertNotContains(response, "Отдел автора")

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
        self.assertContains(response, "Фотография «building.jpg»")
        self.assertNotContains(response, "Изменена фотография «building.jpg»")

    def test_photo_restore_event_is_human_readable(self):
        log = self.create_log(
            model_name="TerritorialOrganPhoto",
            object_repr='Изменена фотография "restore.jpg"',
            old_values={"is_deleted": "True"},
            new_values={"audit_event": "photo_restored_from_trash", "is_deleted": "False", "original_filename": "restore.jpg"},
        )
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"))
        detail_response = self.client.get(reverse("audit_detail", args=[log.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, "Фотография восстановлена")
        self.assertContains(response, "Фотография «restore.jpg»")
        self.assertNotContains(response, "Изменена фотография «restore.jpg»")
        self.assertContains(detail_response, '<strong class="audit-action audit-action-update">Фотография восстановлена</strong>', html=True)

    def test_audit_event_summaries_use_clear_names(self):
        self.create_log(action=AuditLog.Action.DELETE, object_repr="Deleted request")
        self.create_log(
            model_name="TerritorialOrganPhotoFolder",
            object_repr='Изменена запись "Folder"',
            old_values={"name": "Old"},
            new_values={"name": "New"},
        )
        self.create_log(
            action=AuditLog.Action.CREATE,
            model_name="TerritorialOrganPhotoFolder",
            object_repr='Создана запись "333"',
            new_values={"name": "333"},
        )
        self.create_log(
            object_repr="Status request",
            old_values={"status": "in_work"},
            new_values={"audit_event": "request_status_changed", "status": "done"},
        )
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"))

        self.assertContains(response, "Заявка удалена")
        self.assertContains(response, "Папка фотографий переименована")
        self.assertContains(response, "Папка фотографий создана")
        self.assertContains(response, "Папка фотографий «Folder»")
        self.assertContains(response, "Папка фотографий «333»")
        self.assertNotContains(response, "Создана запись «333»")
        self.assertContains(response, "Изменен статус заявки")

    def test_user_audit_log_shows_available_department_actions_with_filters(self):
        User = get_user_model()
        colleague = User.objects.create_user("colleague", password="pass12345", first_name="Иван", last_name="Иванов")
        colleague_profile = UserProfile.objects.create(user=colleague, role=UserProfile.Role.OPERATOR)
        colleague_profile.allowed_departments.add(self.department)
        colleague_profile.allowed_organs.add(self.organ)
        self.create_log(user=self.operator, object_repr="Operator action")
        self.create_log(user=colleague, object_repr="Colleague action")
        self.create_log(user=self.admin, object_repr="Admin action")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("my_audit_log"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Журнал действий")
        self.assertContains(response, "Operator action")
        self.assertContains(response, "Colleague action")
        self.assertNotContains(response, "Admin action")
        self.assertContains(response, "Все пользователи")
        self.assertContains(response, "Все отделы")
        self.assertContains(response, "<th>Пользователь</th>", html=True)

    def test_user_audit_log_hides_unavailable_department_actions_and_detail(self):
        User = get_user_model()
        other_department = Department.objects.create(name="Другой отдел", slug="other", order_number=2)
        other_user = User.objects.create_user("other", password="pass12345")
        other_profile = UserProfile.objects.create(user=other_user, role=UserProfile.Role.OPERATOR)
        other_profile.allowed_departments.add(other_department)
        other_profile.allowed_organs.add(self.organ)
        visible_log = self.create_log(user=self.operator, object_repr="Visible action")
        hidden_log = self.create_log(user=other_user, object_repr="Hidden action")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("my_audit_log"))
        detail_response = self.client.get(reverse("audit_detail", args=[hidden_log.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, "Visible action")
        self.assertNotContains(response, "Hidden action")
        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(self.client.get(reverse("audit_detail", args=[visible_log.pk]), HTTP_HX_REQUEST="true").status_code, 200)

    def test_audit_log_filters_by_date_and_action(self):
        old_log = self.create_log(action=AuditLog.Action.CREATE, object_repr="Old")
        AuditLog.objects.filter(pk=old_log.pk).update(created_at=timezone.datetime(2026, 6, 1, tzinfo=timezone.get_current_timezone()))
        self.create_log(action=AuditLog.Action.DELETE, object_repr="Fresh")
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"), {"action": AuditLog.Action.DELETE, "date_from": "2026-07-01"})

        self.assertContains(response, "Fresh")
        self.assertNotContains(response, "Old")

    def test_audit_log_date_to_includes_the_whole_day(self):
        late_log = self.create_log(object_repr="LateInDay")
        AuditLog.objects.filter(pk=late_log.pk).update(
            created_at=timezone.datetime(2026, 7, 1, 23, 59, 0, tzinfo=timezone.get_current_timezone())
        )
        next_day_log = self.create_log(object_repr="NextDay")
        AuditLog.objects.filter(pk=next_day_log.pk).update(
            created_at=timezone.datetime(2026, 7, 2, 0, 0, 1, tzinfo=timezone.get_current_timezone())
        )
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"), {"date_from": "2026-07-01", "date_to": "2026-07-01"})

        self.assertContains(response, "LateInDay")
        self.assertNotContains(response, "NextDay")

    def test_audit_log_ignores_malformed_date_params_instead_of_erroring(self):
        self.create_log(object_repr="Fresh")
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"), {"date_from": "not-a-date", "date_to": "also-bad"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fresh")

    def test_audit_log_uses_shared_admin_multiselect_component(self):
        self.create_log(object_repr="Shared component")
        self.client.login(username="admin", password="pass12345")

        response = self.client.get(reverse("audit_log"), {"action": AuditLog.Action.UPDATE})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="dropdown admin-multiselect audit-multiselect"')
        self.assertContains(response, 'data-admin-multiselect-label')
        self.assertContains(response, 'data-admin-multiselect-input')
        self.assertContains(response, "Выбрать все")
        self.assertContains(response, "Снять все")
        self.assertContains(response, 'name="action" value="update" data-admin-multiselect-input checked')
        self.assertNotContains(response, "audit-multiselect-trigger")

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
        self.assertContains(response, 'name="action" value="create" data-admin-multiselect-input checked')
        self.assertContains(response, 'name="action" value="update" data-admin-multiselect-input checked')

    def test_audit_log_filters_by_department_and_object_type(self):
        self.create_log(model_name="TmcRequest", object_repr="TMC request")
        self.create_log(model_name="TerritorialOrganPhoto", object_repr="Photo item")
        self.create_log(model_name="TerritorialOrganPhotoFolder", object_repr="Folder item")
        self.client.login(username="admin", password="pass12345")

        department_response = self.client.get(reverse("audit_log"), {"department": "tmc"})
        self.assertContains(department_response, "TMC request")
        self.assertNotContains(department_response, "Photo item")
        self.assertNotContains(department_response, "Folder item")
        self.assertContains(department_response, 'name="department" value="tmc" data-admin-multiselect-input checked')
        self.assertNotContains(department_response, 'name="department" value="photos"')

        object_response = self.client.get(reverse("audit_log"), {"object": "folder"})
        self.assertContains(object_response, "Folder item")
        self.assertNotContains(object_response, "TMC request")
        self.assertNotContains(object_response, "Photo item")
        self.assertContains(object_response, 'name="object" value="folder" data-admin-multiselect-input checked')
