from types import SimpleNamespace

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.directory.models import (
    Department,
    TerritorialOrgan,
    TerritorialOrganPhoto,
    TerritorialOrganPhotoFolder,
)
from apps.requests_app.models import RequestPhotoLink, TmcRequest, TmcRequestItem

from .admin_audit import model_audit_snapshot
from .models import AuditLog


class DjangoAdminAuditTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.admin_user = self.User.objects.create_superuser(
            "root-admin",
            password="pass12345",
            first_name="Анна",
            last_name="Руководитель",
        )
        UserProfile.objects.create(user=self.admin_user, role=UserProfile.Role.ADMIN)
        self.factory = RequestFactory()

    def admin_request(self, method="post", path="/admin/", data=None):
        request = getattr(self.factory, method)(
            path,
            data=data or {},
            REMOTE_ADDR="203.0.113.24",
            HTTP_USER_AGENT="Audit test browser",
        )
        request.user = self.admin_user
        return request

    def test_department_admin_create_update_delete_has_real_snapshots_and_request_metadata(self):
        self.client.force_login(self.admin_user)
        AuditLog.objects.all().delete()

        response = self.client.post(
            reverse("admin:directory_department_add"),
            {
                "name": "Материальное обеспечение",
                "slug": "assets",
                "order_number": "3",
                "description": "Первоначальное описание",
                "is_active": "on",
                "_save": "Сохранить",
            },
            REMOTE_ADDR="203.0.113.24",
            HTTP_USER_AGENT="Audit test browser",
        )
        self.assertEqual(response.status_code, 302)
        department = Department.objects.get(slug="assets")
        created = AuditLog.objects.get(
            action=AuditLog.Action.CREATE,
            model_name="Department",
            object_id=str(department.pk),
        )
        self.assertIsNone(created.old_values)
        self.assertEqual(created.new_values["name"], "Материальное обеспечение")
        self.assertEqual(created.user, self.admin_user)
        self.assertEqual(str(created.ip_address), "203.0.113.24")
        self.assertEqual(created.user_agent, "Audit test browser")

        response = self.client.post(
            reverse("admin:directory_department_change", args=[department.pk]),
            {
                "name": "Материальная база",
                "slug": "assets",
                "order_number": "3",
                "description": "Новое описание",
                "is_active": "on",
                "_save": "Сохранить",
            },
            REMOTE_ADDR="203.0.113.24",
            HTTP_USER_AGENT="Audit test browser",
        )
        self.assertEqual(response.status_code, 302)
        updated = AuditLog.objects.get(
            action=AuditLog.Action.UPDATE,
            model_name="Department",
            object_id=str(department.pk),
        )
        self.assertEqual(updated.old_values["name"], "Материальное обеспечение")
        self.assertEqual(updated.new_values["name"], "Материальная база")
        self.assertEqual(updated.old_values["description"], "Первоначальное описание")
        self.assertEqual(updated.new_values["description"], "Новое описание")

        response = self.client.post(
            reverse("admin:directory_department_delete", args=[department.pk]),
            {"post": "yes"},
            REMOTE_ADDR="203.0.113.24",
            HTTP_USER_AGENT="Audit test browser",
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Department.objects.filter(pk=department.pk).exists())
        deleted = AuditLog.objects.get(
            action=AuditLog.Action.DELETE,
            model_name="Department",
            object_id=str(department.pk),
        )
        self.assertEqual(deleted.old_values["name"], "Материальная база")
        self.assertEqual(deleted.event_type, AuditLog.EventType.RECORD_PURGED)
        self.assertEqual(deleted.new_values, {"audit_event": AuditLog.EventType.RECORD_PURGED})

    def test_user_admin_snapshot_includes_profile_and_m2m_without_secrets(self):
        organ_before = TerritorialOrgan.objects.create(name="До изменения", order_number=1)
        organ_after = TerritorialOrgan.objects.create(name="После изменения", order_number=2)
        department_before = Department.objects.create(name="Отдел до", slug="before")
        department_after = Department.objects.create(name="Отдел после", slug="after")
        group_before = Group.objects.create(name="Группа до")
        group_after = Group.objects.create(name="Группа после")
        employee = self.User.objects.create_user(
            "employee",
            password="employee-pass",
            first_name="Олег",
            last_name="Оператор",
        )
        profile = UserProfile.objects.create(
            user=employee,
            role=UserProfile.Role.OPERATOR,
            activation_code="must-never-be-logged",
        )
        profile.allowed_organs.set([organ_before])
        profile.allowed_departments.set([department_before])
        employee.groups.set([group_before])

        model_admin = admin.site._registry[self.User]
        request = self.admin_request()
        stored_employee = self.User.objects.get(pk=employee.pk)
        stored_employee.first_name = "Пётр"
        fake_form = SimpleNamespace(instance=stored_employee)
        model_admin.save_model(request, stored_employee, fake_form, change=True)

        profile = UserProfile.objects.get(user=employee)
        profile.role = UserProfile.Role.ADMIN
        profile.middle_name = "Петрович"
        profile.save()
        profile.allowed_organs.set([organ_after])
        profile.allowed_departments.set([department_after])
        stored_employee.groups.set([group_after])
        model_admin.finalize_admin_audit(request, fake_form)

        log = AuditLog.objects.get(
            action=AuditLog.Action.UPDATE,
            event_type=AuditLog.EventType.EMPLOYEE_PERMISSIONS,
            model_name="User",
            object_id=str(employee.pk),
        )
        self.assertEqual(log.old_values["first_name"], "Олег")
        self.assertEqual(log.new_values["first_name"], "Пётр")
        self.assertEqual(log.old_values["role"], UserProfile.Role.OPERATOR)
        self.assertEqual(log.new_values["role"], UserProfile.Role.ADMIN)
        self.assertEqual(log.old_values["allowed_organs"], [str(organ_before)])
        self.assertEqual(log.new_values["allowed_organs"], [str(organ_after)])
        self.assertEqual(log.old_values["allowed_departments"], [str(department_before)])
        self.assertEqual(log.new_values["allowed_departments"], [str(department_after)])
        self.assertEqual(log.old_values["django_groups"], [str(group_before)])
        self.assertEqual(log.new_values["django_groups"], [str(group_after)])
        serialized = f"{log.old_values!r}{log.new_values!r}"
        self.assertNotIn("password", serialized)
        self.assertNotIn("activation_code", serialized)
        self.assertNotIn("must-never-be-logged", serialized)
        self.assertEqual(log.user, self.admin_user)
        self.assertEqual(str(log.ip_address), "203.0.113.24")

    def test_tmc_inline_update_and_delete_are_audited_with_parent_organ(self):
        organ = TerritorialOrgan.objects.create(name="МО МВД России", order_number=1)
        request_obj = TmcRequest.objects.create(
            territorial_organ=organ,
            request_number="ТМЦ-1",
            request_date="2026-07-15",
        )
        item = TmcRequestItem.objects.create(
            request=request_obj,
            name="Бумага",
            quantity=2,
            unit="пач.",
        )
        model_admin = admin.site._registry[TmcRequest]
        inline = model_admin.get_inline_instances(self.admin_request("get"), request_obj)[0]
        formset_class = inline.get_formset(self.admin_request("get"), request_obj)
        prefix = formset_class.get_default_prefix()

        update_data = {
            f"{prefix}-TOTAL_FORMS": "1",
            f"{prefix}-INITIAL_FORMS": "1",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
            f"{prefix}-0-id": str(item.pk),
            f"{prefix}-0-request": str(request_obj.pk),
            f"{prefix}-0-product": "",
            f"{prefix}-0-name": "Бумага офисная",
            f"{prefix}-0-quantity": "5",
            f"{prefix}-0-unit": "пач.",
        }
        update_formset = formset_class(update_data, instance=request_obj, prefix=prefix)
        self.assertTrue(update_formset.is_valid(), update_formset.errors)
        model_admin.save_formset(
            self.admin_request(data=update_data),
            SimpleNamespace(instance=request_obj),
            update_formset,
            change=True,
        )
        updated = AuditLog.objects.get(action=AuditLog.Action.UPDATE, model_name="TmcRequestItem")
        self.assertEqual(updated.old_values["name"], "Бумага")
        self.assertEqual(updated.new_values["name"], "Бумага офисная")
        self.assertEqual(updated.old_values["quantity"], 2)
        self.assertEqual(updated.new_values["quantity"], 5)
        self.assertEqual(updated.territorial_organ, organ)

        delete_data = {
            **update_data,
            f"{prefix}-0-name": "Бумага офисная",
            f"{prefix}-0-quantity": "5",
            f"{prefix}-0-DELETE": "on",
        }
        delete_formset = formset_class(delete_data, instance=request_obj, prefix=prefix)
        self.assertTrue(delete_formset.is_valid(), delete_formset.errors)
        model_admin.save_formset(
            self.admin_request(data=delete_data),
            SimpleNamespace(instance=request_obj),
            delete_formset,
            change=True,
        )
        deleted = AuditLog.objects.get(action=AuditLog.Action.DELETE, model_name="TmcRequestItem")
        self.assertEqual(deleted.object_id, str(item.pk))
        self.assertEqual(deleted.event_type, AuditLog.EventType.RECORD_PURGED)
        self.assertEqual(deleted.old_values["name"], "Бумага офисная")
        self.assertEqual(deleted.territorial_organ, organ)
        self.assertFalse(TmcRequestItem.objects.filter(pk=item.pk).exists())

        create_data = {
            f"{prefix}-TOTAL_FORMS": "1",
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "1000",
            f"{prefix}-0-id": "",
            f"{prefix}-0-request": str(request_obj.pk),
            f"{prefix}-0-product": "",
            f"{prefix}-0-name": "Картридж",
            f"{prefix}-0-quantity": "1",
            f"{prefix}-0-unit": "шт.",
        }
        create_formset = formset_class(create_data, instance=request_obj, prefix=prefix)
        self.assertTrue(create_formset.is_valid(), create_formset.errors)
        model_admin.save_formset(
            self.admin_request(data=create_data),
            SimpleNamespace(instance=request_obj),
            create_formset,
            change=True,
        )
        created_item = TmcRequestItem.objects.get(request=request_obj, name="Картридж")
        created = AuditLog.objects.get(
            action=AuditLog.Action.CREATE,
            model_name="TmcRequestItem",
            object_id=str(created_item.pk),
        )
        self.assertEqual(created.new_values["name"], "Картридж")
        self.assertEqual(created.territorial_organ, organ)

    def test_photo_and_folder_admin_purge_events_keep_thumbnail_snapshots(self):
        organ = TerritorialOrgan.objects.create(name="Фотоорган", order_number=1)
        root = TerritorialOrganPhotoFolder.objects.create(
            territorial_organ=organ,
            name="Архив",
        )
        child = TerritorialOrganPhotoFolder.objects.create(
            territorial_organ=organ,
            parent=root,
            name="Вложенная папка",
        )
        photos = [
            TerritorialOrganPhoto(
                territorial_organ=organ,
                folder=root,
                image="",
                original_filename="root.jpg",
            ),
            TerritorialOrganPhoto(
                territorial_organ=organ,
                folder=child,
                image="",
                original_filename="child.jpg",
                is_deleted=True,
            ),
        ]
        TerritorialOrganPhoto.objects.bulk_create(photos)
        root_photo, child_photo = list(
            TerritorialOrganPhoto.objects.filter(territorial_organ=organ).order_by("original_filename")
        )

        folder_admin = admin.site._registry[TerritorialOrganPhotoFolder]
        request = self.admin_request()
        editable_root = TerritorialOrganPhotoFolder.objects.get(pk=root.pk)
        editable_root.name = "Архив 2026"
        fake_form = SimpleNamespace(instance=editable_root)
        folder_admin.save_model(request, editable_root, fake_form, change=True)
        folder_admin.finalize_admin_audit(request, fake_form)
        update_log = AuditLog.objects.get(
            action=AuditLog.Action.UPDATE,
            model_name="TerritorialOrganPhotoFolder",
            object_id=str(root.pk),
        )
        expected_ids = sorted([root_photo.pk, child_photo.pk])
        self.assertEqual(update_log.old_values["photo_count"], 2)
        self.assertEqual(update_log.new_values["photo_count"], 2)
        self.assertEqual(sorted(item["id"] for item in update_log.old_values["photo_items"]), expected_ids)
        self.assertEqual(sorted(item["id"] for item in update_log.new_values["photo_items"]), expected_ids)

        folder_admin.delete_model(
            self.admin_request(),
            TerritorialOrganPhotoFolder.objects.get(pk=root.pk),
        )
        folder_log = AuditLog.objects.get(
            action=AuditLog.Action.DELETE,
            model_name="TerritorialOrganPhotoFolder",
            object_id=str(root.pk),
        )
        self.assertEqual(folder_log.event_type, AuditLog.EventType.FOLDER_PURGED)
        self.assertEqual(folder_log.old_values["photo_count"], 2)
        self.assertEqual(sorted(item["id"] for item in folder_log.old_values["photo_items"]), expected_ids)

        standalone_photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=organ,
            image="",
        )
        TerritorialOrganPhoto.objects.filter(pk=standalone_photo.pk).update(original_filename="standalone.jpg")
        standalone_photo.refresh_from_db()
        standalone_photo_id = standalone_photo.pk
        photo_admin = admin.site._registry[TerritorialOrganPhoto]
        photo_admin.delete_model(self.admin_request(), standalone_photo)
        photo_log = AuditLog.objects.get(
            action=AuditLog.Action.DELETE,
            model_name="TerritorialOrganPhoto",
            object_id=str(standalone_photo_id),
        )
        self.assertEqual(photo_log.event_type, AuditLog.EventType.PHOTO_PURGED)
        self.assertEqual(photo_log.old_values["original_filename"], "standalone.jpg")

    def test_request_photo_link_admin_uses_attach_detach_events_and_photo_snapshot(self):
        organ = TerritorialOrgan.objects.create(name="Орган со связью", order_number=1)
        request_obj = TmcRequest.objects.create(
            territorial_organ=organ,
            request_number="ТМЦ-ФОТО-1",
            request_date="2026-07-15",
        )
        photo = TerritorialOrganPhoto.objects.create(territorial_organ=organ, image="")
        TerritorialOrganPhoto.objects.filter(pk=photo.pk).update(original_filename="linked.jpg")
        photo.refresh_from_db()
        link = RequestPhotoLink(
            territorial_organ=organ,
            content_type=ContentType.objects.get_for_model(request_obj),
            object_id=request_obj.pk,
            photo=photo,
            created_by=self.admin_user,
        )
        link_admin = admin.site._registry[RequestPhotoLink]
        fake_form = SimpleNamespace(instance=link)
        link_admin.save_model(self.admin_request(), link, fake_form, change=False)
        link_admin.finalize_admin_audit(self.admin_request(), fake_form)

        attach_log = AuditLog.objects.get(
            action=AuditLog.Action.CREATE,
            model_name="RequestPhotoLink",
            object_id=str(link.pk),
        )
        self.assertEqual(attach_log.event_type, AuditLog.EventType.PHOTOS_ATTACHED)
        self.assertEqual(attach_log.new_values["photo_count"], 1)
        self.assertEqual(attach_log.new_values["photo_items"], [{"id": photo.pk, "name": "linked.jpg"}])
        self.assertEqual(attach_log.territorial_organ, organ)

        link_id = link.pk
        link_admin.delete_model(self.admin_request(), link)
        detach_log = AuditLog.objects.get(
            action=AuditLog.Action.DELETE,
            model_name="RequestPhotoLink",
            object_id=str(link_id),
        )
        self.assertEqual(detach_log.event_type, AuditLog.EventType.PHOTOS_DETACHED)
        self.assertEqual(detach_log.old_values["photo_count"], 1)
        self.assertEqual(detach_log.old_values["photo_items"], [{"id": photo.pk, "name": "linked.jpg"}])

    def test_snapshot_serializer_never_contains_user_credentials(self):
        self.admin_user.profile.activation_code = "private-code"
        self.admin_user.profile.save(update_fields=["activation_code"])
        snapshot = model_audit_snapshot(self.admin_user)
        self.assertNotIn("password", snapshot)
        self.assertNotIn("activation_code", snapshot)
        self.assertNotIn("private-code", repr(snapshot))

    def test_admin_password_change_writes_one_safe_password_event(self):
        employee = self.User.objects.create_user(
            "password-user",
            password="old-secret-password",
            first_name="Павел",
            last_name="Сотрудник",
        )
        UserProfile.objects.create(user=employee, role=UserProfile.Role.OPERATOR)
        old_hash = employee.password
        self.client.force_login(self.admin_user)
        AuditLog.objects.all().delete()

        response = self.client.post(
            reverse("admin:auth_user_password_change", args=[employee.pk]),
            {
                "usable_password": "true",
                "password1": "new-secret-password-2026",
                "password2": "new-secret-password-2026",
            },
            REMOTE_ADDR="203.0.113.24",
            HTTP_USER_AGENT="Audit test browser",
        )
        self.assertEqual(response.status_code, 302)
        employee.refresh_from_db()
        self.assertTrue(employee.check_password("new-secret-password-2026"))

        logs = AuditLog.objects.filter(
            action=AuditLog.Action.UPDATE,
            event_type=AuditLog.EventType.PASSWORD_CHANGED,
            model_name="User",
            object_id=str(employee.pk),
        )
        self.assertEqual(logs.count(), 1)
        log = logs.get()
        self.assertNotIn("password", log.old_values)
        self.assertNotIn("password", log.new_values)
        serialized = f"{log.old_values!r}{log.new_values!r}"
        self.assertNotIn(old_hash, serialized)
        self.assertNotIn("old-secret-password", serialized)
        self.assertNotIn("new-secret-password", serialized)
        self.assertEqual(log.old_values["password_changed"], False)
        self.assertEqual(log.new_values["password_changed"], True)


class AuditLogAdminImmutabilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_superuser("audit-admin", password="pass12345")
        UserProfile.objects.create(user=self.admin_user, role=UserProfile.Role.ADMIN)
        self.log = AuditLog.objects.create(
            user=self.admin_user,
            action=AuditLog.Action.CREATE,
            model_name="Department",
            object_id="1",
            object_repr="Отдел",
            new_values={"name": "Отдел"},
        )
        self.client.force_login(self.admin_user)

    def test_audit_log_admin_allows_view_but_forbids_every_write_path(self):
        model_admin = admin.site._registry[AuditLog]
        request = RequestFactory().get("/admin/audit/auditlog/")
        request.user = self.admin_user
        self.assertTrue(model_admin.has_view_permission(request, self.log))
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request, self.log))
        self.assertFalse(model_admin.has_delete_permission(request, self.log))
        self.assertNotIn("delete_selected", model_admin.get_actions(request))

        self.assertEqual(self.client.get(reverse("admin:audit_auditlog_changelist")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("admin:audit_auditlog_change", args=[self.log.pk])).status_code,
            200,
        )
        self.assertEqual(self.client.get(reverse("admin:audit_auditlog_add")).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("admin:audit_auditlog_change", args=[self.log.pk]), {"action": "delete"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse("admin:audit_auditlog_delete", args=[self.log.pk]), {"post": "yes"}).status_code,
            403,
        )
        self.assertTrue(AuditLog.objects.filter(pk=self.log.pk).exists())
