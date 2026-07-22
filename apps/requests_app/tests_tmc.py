from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from .services.exports import export_objects
from .services.table_filters import request_table_queryset
from .tests_base import *


class TmcRequestTests(RequestAppTestCase):

    def test_saving_unchanged_tmc_request_does_not_create_update_event(self):
        product = TmcProduct.objects.create(name="Chair", unit="pcs")
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="14/TMC",
            request_date="2026-06-27",
            status="in_work",
            comment="Unchanged",
        )
        TmcRequestItem.objects.create(
            request=request_obj,
            product=product,
            name=product.name,
            quantity=1,
            unit=product.unit,
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
            {
                "request_number": "14/TMC",
                "request_date": "2026-06-27",
                "status": "in_work",
                "due_date": "",
                "comment": "Unchanged",
                "item_product": [str(product.pk)],
                "item_name": [product.name],
                "item_quantity": ["1"],
                "item_unit": [product.unit],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            AuditLog.objects.filter(
                model_name="TmcRequest",
                object_id=str(request_obj.pk),
                event_type=AuditLog.EventType.RECORD_UPDATED,
            ).exists()
        )

    def test_tmc_status_change_creates_one_request_audit_event(self):
        product = TmcProduct.objects.create(name="Chair", unit="pcs")
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="14-STATUS/TMC",
            request_date="2026-06-27",
            status="in_work",
            comment="Status only",
        )
        TmcRequestItem.objects.create(
            request=request_obj,
            product=product,
            name=product.name,
            quantity=1,
            unit=product.unit,
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
            {
                "request_number": "14-STATUS/TMC",
                "request_date": "2026-06-27",
                "status": "done",
                "due_date": "2026-06-29",
                "comment": "Status only",
                "item_product": [str(product.pk)],
                "item_name": [product.name],
                "item_quantity": ["1"],
                "item_unit": [product.unit],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        logs = AuditLog.objects.filter(model_name="TmcRequest", object_id=str(request_obj.pk))
        self.assertEqual(logs.count(), 1)
        log = logs.get()
        self.assertEqual(log.event_type, AuditLog.EventType.STATUS_CHANGED)
        self.assertEqual(log.old_values["status"], "in_work")
        self.assertEqual(log.new_values["status"], "done")
        self.assertEqual(log.new_values["due_date"], "2026-06-29")

    def test_tmc_item_change_does_not_duplicate_generic_update_event(self):
        product = TmcProduct.objects.create(name="Chair", unit="pcs")
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="14-ITEM/TMC",
            request_date="2026-06-27",
            status="in_work",
            comment="Item only",
        )
        TmcRequestItem.objects.create(
            request=request_obj,
            product=product,
            name=product.name,
            quantity=1,
            unit=product.unit,
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
            {
                "request_number": "14-ITEM/TMC",
                "request_date": "2026-06-27",
                "status": "in_work",
                "due_date": "",
                "comment": "Item only",
                "item_product": [str(product.pk)],
                "item_name": [product.name],
                "item_quantity": ["2"],
                "item_unit": [product.unit],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        logs = AuditLog.objects.filter(model_name="TmcRequest", object_id=str(request_obj.pk))
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.get().event_type, AuditLog.EventType.TMC_QUANTITY_CHANGED)
        self.assertFalse(logs.filter(event_type=AuditLog.EventType.RECORD_UPDATED).exists())

    def test_crud_creates_tmc_request_with_multiple_items_and_audit_log(self):
        self.client.login(username="operator", password="pass12345")
        response = self.client.post(
            reverse("record_create", args=[self.organ.pk, "tmc-requests"]),
            {
                "request_number": "15/TMC",
                "request_date": "2026-06-27",
                "status": "in_work",
                "comment": "Urgent",
                "item_name": ["Paper", "Keyboard"],
                "item_quantity": ["10", "3"],
                "item_unit": ["pack", "pcs"],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        request_obj = TmcRequest.objects.get(request_number="15/TMC")
        self.assertEqual(request_obj.items.count(), 2)
        self.assertTrue(request_obj.items.filter(name="Paper", quantity=10, unit="pack").exists())
        self.assertTrue(request_obj.items.filter(name="Keyboard", quantity=3, unit="pcs").exists())
        self.assertTrue(TmcProduct.objects.filter(name="Paper", normalized_name="paper").exists())
        self.assertTrue(request_obj.items.filter(name="Paper", product__name="Paper").exists())
        self.assertTrue(self.status_history(request_obj).filter(old_status__isnull=True, new_status="in_work", changed_by=self.user).exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CREATE, model_name="TmcRequest").exists())
        self.assertNotContains(response, "request-photo-count")

    def test_tmc_request_uses_selected_product_from_suggestion(self):
        product = TmcProduct.objects.create(name="Стол компьютерный", unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_create", args=[self.organ.pk, "tmc-requests"]),
            {
                "request_number": "16/TMC",
                "request_date": "2026-06-27",
                "status": "in_work",
                "comment": "Selected product",
                "item_product": [str(product.pk)],
                "item_name": ["компьютерный стол"],
                "item_quantity": ["2"],
                "item_unit": ["шт."],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        item = TmcRequest.objects.get(request_number="16/TMC").items.get()
        self.assertEqual(item.product, product)
        self.assertEqual(item.name, "Стол компьютерный")
        self.assertEqual(TmcProduct.objects.count(), 1)

    def test_tmc_request_creates_new_product_when_suggestion_not_selected(self):
        TmcProduct.objects.create(name="Стол компьютерный", unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_create", args=[self.organ.pk, "tmc-requests"]),
            {
                "request_number": "17/TMC",
                "request_date": "2026-06-27",
                "status": "in_work",
                "comment": "Manual product",
                "item_product": [""],
                "item_name": ["Компьютерный стол"],
                "item_quantity": ["1"],
                "item_unit": ["шт."],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(TmcProduct.objects.filter(name="Компьютерный стол").exists())
        self.assertEqual(TmcProduct.objects.count(), 2)

    def test_request_create_form_uses_in_work_status_by_default(self):
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("record_create", args=[self.organ.pk, "tmc-requests"]), HTTP_HX_REQUEST="true")

        self.assertContains(response, 'hx-target="#table-area"')
        self.assertContains(response, "novalidate")
        self.assertContains(response, 'name="status"')
        self.assertContains(response, "Статус исполнения")
        self.assertNotContains(response, "Исполнение заявки")
        self.assertContains(response, 'value="in_work"')
        self.assertContains(response, "data-app-date-input")
        self.assertNotContains(response, 'type="date"')
        self.assertNotContains(response, 'value="new"')
        self.assertNotIn(("new", "Новая"), TmcRequest._meta.get_field("status").choices)
        self.assertNotIn(("new", "Новая"), ACTIVE_NEED_STATUS_CHOICES)

    def test_request_number_field_has_autofocus_only_on_create_form(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="18-AF/TMC",
            request_date="2026-06-27",
            status="in_work",
        )
        self.client.login(username="operator", password="pass12345")

        create_response = self.client.get(reverse("record_create", args=[self.organ.pk, "tmc-requests"]), HTTP_HX_REQUEST="true")
        update_response = self.client.get(reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(create_response, 'name="request_number"')
        self.assertContains(create_response, "autofocus")
        self.assertNotContains(update_response, "autofocus")

    def test_tmc_product_suggest_finds_words_in_any_order(self):
        TmcProduct.objects.create(name="Стол компьютерный", unit="шт.")
        TmcProduct.objects.create(name="Стол письменный", unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("tmc_product_suggest"), {"q": "компьютерный стол"})

        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.json()["results"]]
        self.assertEqual(names[0], "Стол компьютерный")

    def test_tmc_product_suggest_finds_typo_matches(self):
        TmcProduct.objects.create(name="Пылесос", unit="шт.")
        TmcProduct.objects.create(name="Пылесборник", unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("tmc_product_suggest"), {"q": "пылксос"})

        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.json()["results"]]
        self.assertEqual(names[0], "Пылесос")

    def test_tmc_product_suggest_requires_login(self):
        response = self.client.get(reverse("tmc_product_suggest"), {"q": "стол"})

        self.assertEqual(response.status_code, 302)

    def test_tmc_status_history_records_status_changes(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            updated_by=self.user,
            request_number="18/TMC",
            request_date="2026-06-27",
            status="in_work",
        )
        TmcRequestItem.objects.create(request=request_obj, name="Chair", quantity=1, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
            {
                "request_number": "18/TMC",
                "request_date": "2026-06-27",
                "status": "done",
                "due_date": "2026-06-29",
                "comment": "",
                "item_name": ["Chair"],
                "item_quantity": ["1"],
                "item_unit": ["pcs"],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.status_history(request_obj).filter(old_status="in_work", new_status="done", changed_by=self.user).exists())

    def test_tmc_edit_form_keeps_request_dates(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            updated_by=self.user,
            request_number="18-1/TMC",
            request_date="2026-06-27",
            due_date="2026-06-28",
            status="done",
        )
        TmcRequestItem.objects.create(request=request_obj, name="Chair", quantity=1, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, 'name="request_date"')
        self.assertContains(response, 'value="2026-06-27"')
        self.assertContains(response, 'name="due_date"')
        self.assertContains(response, 'value="2026-06-28"')
        self.assertContains(response, "Дата исполнения")
        self.assertNotContains(response, "Дата исполнения / отклонения")

    def test_tmc_done_status_history_stores_completed_date(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            updated_by=self.user,
            request_number="18-2/TMC",
            request_date="2026-06-27",
            status="in_work",
        )
        TmcRequestItem.objects.create(request=request_obj, name="Chair", quantity=1, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
            {
                "request_number": "18-2/TMC",
                "request_date": "2026-06-27",
                "status": "done",
                "due_date": "2026-06-29",
                "comment": "",
                "item_name": ["Chair"],
                "item_quantity": ["1"],
                "item_unit": ["pcs"],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        history = self.status_history(request_obj).get(old_status="in_work", new_status="done")
        self.assertEqual(history.completed_at.isoformat(), "2026-06-29")

        modal = self.client.get(reverse("tmc_status_history", args=[self.organ.pk, request_obj.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(modal, "Дата исполнения")
        self.assertNotContains(modal, "Дата исполнения / отклонения")
        self.assertContains(modal, "29.06.2026")

    def test_tmc_terminal_statuses_default_completion_date_to_today(self):
        self.client.login(username="operator", password="pass12345")

        for index, status in enumerate(("done", "rejected"), start=1):
            with self.subTest(status=status):
                product = TmcProduct.objects.create(name=f"Auto date item {index}", unit="pcs")
                request_obj = TmcRequest.objects.create(
                    territorial_organ=self.organ,
                    created_by=self.user,
                    updated_by=self.user,
                    request_number=f"AUTO-{index}/TMC",
                    request_date="2026-06-27",
                    status="in_work",
                )
                TmcRequestItem.objects.create(
                    request=request_obj,
                    product=product,
                    name=product.name,
                    quantity=1,
                    unit=product.unit,
                )

                response = self.client.post(
                    reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
                    {
                        "request_number": request_obj.request_number,
                        "request_date": "2026-06-27",
                        "status": status,
                        "due_date": "",
                        "comment": "",
                        "item_product": [str(product.pk)],
                        "item_name": [product.name],
                        "item_quantity": ["1"],
                        "item_unit": [product.unit],
                    },
                    HTTP_HX_REQUEST="true",
                )

                self.assertEqual(response.status_code, 200)
                request_obj.refresh_from_db()
                self.assertEqual(request_obj.due_date, timezone.localdate())
                history = self.status_history(request_obj).get(old_status="in_work", new_status=status)
                self.assertEqual(history.completed_at, timezone.localdate())
                modal = self.client.get(
                    reverse("tmc_status_history", args=[self.organ.pk, request_obj.pk]),
                    HTTP_HX_REQUEST="true",
                )
                expected_label = "Дата отклонения" if status == "rejected" else "Дата исполнения"
                self.assertContains(modal, expected_label)
                self.assertNotContains(modal, "Дата исполнения / отклонения")

    def test_tmc_in_work_status_clears_completion_date(self):
        product = TmcProduct.objects.create(name="Reopened item", unit="pcs")
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            updated_by=self.user,
            request_number="REOPEN/TMC",
            request_date="2026-06-27",
            status="rejected",
            due_date="2026-06-29",
        )
        TmcRequestItem.objects.create(
            request=request_obj,
            product=product,
            name=product.name,
            quantity=1,
            unit=product.unit,
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
            {
                "request_number": request_obj.request_number,
                "request_date": "2026-06-27",
                "status": "in_work",
                "due_date": "2026-06-29",
                "comment": "",
                "item_product": [str(product.pk)],
                "item_name": [product.name],
                "item_quantity": ["1"],
                "item_unit": [product.unit],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        request_obj.refresh_from_db()
        self.assertIsNone(request_obj.due_date)
        history = self.status_history(request_obj).get(old_status="rejected", new_status="in_work")
        self.assertIsNone(history.completed_at)

    def test_tmc_status_history_modal_is_available(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            updated_by=self.user,
            request_number="19/TMC",
            request_date="2026-06-27",
            status="done",
        )
        RequestStatusHistory.objects.create(
            content_type=ContentType.objects.get_for_model(request_obj, for_concrete_model=False),
            object_id=request_obj.pk,
            old_status="in_work",
            new_status="done",
            changed_by=self.user,
            note="Finished",
        )
        self.client.login(username="operator", password="pass12345")

        table_response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))
        self.assertContains(table_response, reverse("tmc_status_history", args=[self.organ.pk, request_obj.pk]))
        self.assertContains(table_response, "bi-clock-history")

        response = self.client.get(reverse("tmc_status_history", args=[self.organ.pk, request_obj.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(response, "История изменений статуса заявки 19/TMC")
        self.assertContains(response, request_obj.get_status_display())
        self.assertContains(response, f"<span>{request_obj.get_status_display()}</span>", html=True)
        self.assertContains(response, "Finished")

    def test_tmc_xlsx_export_has_grouped_document_layout(self):
        first = TmcRequest.objects.create(territorial_organ=self.organ, request_number="20/TMC", request_date="2026-06-27", status="in_work", comment="First comment")
        TmcRequestItem.objects.create(request=first, name="Desk", quantity=5, unit="pcs")
        TmcRequestItem.objects.create(request=first, name="Chair", quantity=5, unit="pcs")
        second = TmcRequest.objects.create(territorial_organ=self.organ, request_number="21/TMC", request_date="2026-06-26", status="in_work", comment="Second comment")
        TmcRequestItem.objects.create(request=second, name="Keyboard", quantity=3, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("export_table", args=[self.organ.pk, "tmc-requests", "xlsx"]))

        self.assertEqual(response.status_code, 200)
        workbook = self.response_workbook(response)
        sheet = workbook.active
        self.assertEqual(sheet["A1"].value, "Сведения о потребности ТМЦ")
        self.assertEqual(sheet["C1"].value, "Заявка")
        self.assertEqual(sheet["F1"].value, "Описание")
        self.assertIn("A1:B1", {str(item) for item in sheet.merged_cells.ranges})
        self.assertIn("C1:E1", {str(item) for item in sheet.merged_cells.ranges})
        self.assertIn("F1:F2", {str(item) for item in sheet.merged_cells.ranges})
        self.assertIn("C3:C4", {str(item) for item in sheet.merged_cells.ranges})
        self.assertEqual(sheet["A3"].value, "Desk")
        self.assertEqual(sheet["A4"].value, "Chair")
        self.assertEqual(sheet["C3"].value, "20/TMC")
        self.assertEqual(sheet["E3"].value, first.get_status_display())
        self.assertEqual(sheet["F3"].value, "First comment")
        self.assertEqual(sheet["B3"].border.right.style, "medium")
        self.assertEqual(sheet["E3"].border.right.style, "medium")
        self.assertEqual(sheet["F3"].border.right.style, "medium")
        self.assertEqual(sheet["A4"].border.bottom.style, "medium")

    def test_tmc_filters_by_status_date_range_and_text(self):
        matching = TmcRequest.objects.create(territorial_organ=self.organ, request_number="22/TMC", request_date="2026-06-20", status="in_work", comment="Office")
        TmcRequestItem.objects.create(request=matching, name="Monitor", quantity=2, unit="pcs")
        wrong_status = TmcRequest.objects.create(territorial_organ=self.organ, request_number="23/TMC", request_date="2026-06-20", status="done", comment="Office")
        TmcRequestItem.objects.create(request=wrong_status, name="Monitor", quantity=1, unit="pcs")
        wrong_date = TmcRequest.objects.create(territorial_organ=self.organ, request_number="24/TMC", request_date="2026-05-20", status="in_work", comment="Office")
        TmcRequestItem.objects.create(request=wrong_date, name="Monitor", quantity=1, unit="pcs")
        wrong_text = TmcRequest.objects.create(territorial_organ=self.organ, request_number="25/TMC", request_date="2026-06-20", status="in_work", comment="Warehouse")
        TmcRequestItem.objects.create(request=wrong_text, name="Printer", quantity=1, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
            {"status": "in_work", "date_from": "2026-06-01", "date_to": "2026-06-30", "q": "Monitor"},
        )

        self.assertContains(response, "22/TMC")
        self.assertNotContains(response, "23/TMC")
        self.assertNotContains(response, "24/TMC")
        self.assertNotContains(response, "25/TMC")
        self.assertContains(response, "status=in_work")
        self.assertContains(response, "date_from=2026-06-01")
        self.assertContains(response, "date_to=2026-06-30")
        self.assertContains(response, "q=Monitor")
        self.assertContains(response, "В работе")
        self.assertNotContains(response, 'value="new"')
        self.assertNotContains(response, "Новых")
        self.assertContains(response, "Исполнено")
        self.assertContains(response, "Отклонено")
        self.assertContains(response, "<strong>1</strong>", html=True)

    def test_zero_status_summary_pills_are_muted_consistently(self):
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))

        self.assertContains(response, "summary-pill-in-work is-zero")
        self.assertContains(response, "summary-pill-done is-zero")
        self.assertContains(response, "summary-pill-rejected is-zero")

    def test_tmc_table_supports_multi_organ_summary_mode(self):
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        first = TmcRequest.objects.create(territorial_organ=self.organ, request_number="40/TMC", request_date="2026-06-20", status="in_work", comment="Office")
        second = TmcRequest.objects.create(territorial_organ=other_organ, request_number="41/TMC", request_date="2026-06-21", status="in_work", comment="Office")
        TmcRequestItem.objects.create(request=first, name="Бумага А4", quantity=5, unit="пач.")
        TmcRequestItem.objects.create(request=second, name="Бумага А4", quantity=7, unit="пач.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "q": "Бумага А4"},
        )

        self.assertContains(response, "Территориальный орган")
        self.assertContains(response, "Test territorial organ")
        self.assertContains(response, "Other territorial organ")
        self.assertContains(response, "40/TMC")
        self.assertContains(response, "41/TMC")
        self.assertContains(response, f'name="organ_ids" value="{self.organ.pk}"')
        self.assertContains(response, f'name="organ_ids" value="{other_organ.pk}"')
        self.assertNotContains(response, "Добавить")

    def test_department_panel_preserves_multi_organ_querystring(self):
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("department_tables", args=[self.organ.pk, "tmc"]),
            {"organ_ids": [self.organ.pk, other_organ.pk]},
        )

        self.assertContains(response, "Сводный просмотр: 2 территориальных органов")
        self.assertContains(response, f"organ_ids={self.organ.pk}")
        self.assertContains(response, f"organ_ids={other_organ.pk}")

    def test_department_panel_restores_requested_table_and_filters(self):
        transport = Department.objects.create(name="Transport", slug="transport", order_number=2)
        self.user.profile.allowed_departments.add(transport)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("department_tables", args=[self.organ.pk, "transport"]),
            {"table": "vehicle-fuel", "status": "in_work", "q": "diesel"},
        )

        self.assertContains(response, 'data-table-key="vehicle-fuel"')
        self.assertContains(response, reverse("table_data", args=[self.organ.pk, "vehicle-fuel"]) + "?status=in_work&amp;q=diesel")
        self.assertContains(response, 'data-table-key="vehicle-fuel" hx-get')
        self.assertNotContains(response, reverse("table_data", args=[self.organ.pk, "vehicle-repair"]) + "?status=in_work")

    def test_multi_organ_summary_keeps_row_actions_for_writable_organs(self):
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        self.user.profile.writable_organs.add(other_organ)
        first = TmcRequest.objects.create(territorial_organ=self.organ, request_number="42/TMC", request_date="2026-06-20", status="in_work")
        second = TmcRequest.objects.create(territorial_organ=other_organ, request_number="43/TMC", request_date="2026-06-21", status="in_work")
        TmcRequestItem.objects.create(request=first, name="Paper", quantity=5, unit="pcs")
        TmcRequestItem.objects.create(request=second, name="Paper", quantity=7, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "q": "Paper"},
        )

        self.assertContains(response, reverse("record_update", args=[self.organ.pk, "tmc-requests", first.pk]))
        self.assertContains(response, reverse("record_update", args=[other_organ.pk, "tmc-requests", second.pk]))
        self.assertContains(response, reverse("record_delete", args=[self.organ.pk, "tmc-requests", first.pk]))
        self.assertContains(response, reverse("record_delete", args=[other_organ.pk, "tmc-requests", second.pk]))
        self.assertNotContains(response, reverse("record_create", args=[self.organ.pk, "tmc-requests"]))

    def test_tmc_table_can_group_products_across_selected_organs(self):
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        first = TmcRequest.objects.create(territorial_organ=self.organ, request_number="44/TMC", request_date="2026-06-20", status="in_work")
        second = TmcRequest.objects.create(territorial_organ=other_organ, request_number="45/TMC", request_date="2026-06-21", status="in_work")
        third = TmcRequest.objects.create(territorial_organ=other_organ, request_number="46/TMC", request_date="2026-06-22", status="done")
        TmcRequestItem.objects.create(request=first, name="Бумага А4", quantity=5, unit="пач.")
        TmcRequestItem.objects.create(request=second, name="Бумага А4", quantity=7, unit="пач.")
        TmcRequestItem.objects.create(request=third, name="Кресло офисное", quantity=1, unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "group": "products"},
        )

        self.assertContains(response, "По заявкам")
        self.assertContains(response, "По ТМЦ")
        self.assertContains(response, "По территориальному органу")
        self.assertContains(response, "По дате")
        self.assertContains(response, 'name="group"')
        self.assertContains(response, "Бумага А4")
        self.assertContains(response, "Кресло офисное")
        self.assertContains(response, "tmc-drilldown-link")
        self.assertContains(response, f"organ_ids={self.organ.pk}")
        self.assertContains(response, f"organ_ids={other_organ.pk}")
        self.assertContains(response, f"q={quote_plus('Бумага А4')}")
        self.assertContains(response, "<td class=\"text-center\">2</td>", html=True)
        self.assertContains(response, "<td class=\"text-center\">12</td>", html=True)
        self.assertContains(response, "позиций")
        self.assertContains(response, "Применены фильтры:")
        self.assertContains(response, "выборочно: 2 органов")
        self.assertContains(response, "группировка: По ТМЦ")
        self.assertContains(response, "Сбросить все")
        self.assertContains(response, "data-reset-table-state")
        self.assertContains(response, "Позиций найдено")
        self.assertContains(response, "Всего заявок")
        self.assertContains(response, "Всего органов")
        self.assertContains(response, "Общее количество")
        self.assertContains(response, 'data-download-preparing="Подготовка экспорта..."')
        self.assertContains(response, "<strong>2</strong>", count=3, html=True)
        self.assertContains(response, "<strong>3</strong>", html=True)
        self.assertContains(response, "<strong>13</strong>", html=True)
        self.assertNotContains(response, "summary-pill-in-work")
        self.assertNotContains(response, "summary-pill-new")
        self.assertNotContains(response, "summary-pill-done")
        self.assertNotContains(response, "summary-pill-rejected")
        self.assertNotContains(response, "Сбросить фильтры")
        self.assertNotContains(response, reverse("record_update", args=[self.organ.pk, "tmc-requests", first.pk]))

    def test_tmc_table_can_group_by_territorial_organs_when_multiple_selected(self):
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        first = TmcRequest.objects.create(territorial_organ=self.organ, request_number="51/TMC", request_date="2026-06-20", status="in_work")
        second = TmcRequest.objects.create(territorial_organ=other_organ, request_number="52/TMC", request_date="2026-06-21", status="in_work")
        third = TmcRequest.objects.create(territorial_organ=other_organ, request_number="53/TMC", request_date="2026-06-22", status="done")
        TmcRequestItem.objects.create(request=first, name="Бумага А4", quantity=5, unit="пач.")
        TmcRequestItem.objects.create(request=second, name="Бумага А4", quantity=7, unit="пач.")
        TmcRequestItem.objects.create(request=third, name="Кресло офисное", quantity=1, unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "group": "organs"},
        )

        self.assertContains(response, "Территориальный орган")
        self.assertContains(response, "Test territorial organ")
        self.assertContains(response, "Other territorial organ")
        self.assertContains(response, "Заявок")
        self.assertContains(response, "Позиций ТМЦ")
        self.assertContains(response, "Общее количество")
        self.assertContains(response, "группировка: По территориальному органу")
        self.assertContains(response, "органов")
        self.assertContains(response, "Органов найдено")
        self.assertContains(response, "<td class=\"text-center\">2</td>", html=True)
        self.assertNotContains(response, "tmc-drilldown-link")
        self.assertContains(response, "summary-pill-in-work")

    def test_tmc_organ_grouping_is_available_only_for_multi_organ_mode(self):
        request_obj = TmcRequest.objects.create(territorial_organ=self.organ, request_number="54/TMC", request_date="2026-06-20", status="in_work")
        TmcRequestItem.objects.create(request=request_obj, name="Сканер", quantity=2, unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]), {"group": "organs"})

        self.assertContains(response, "54/TMC")
        self.assertContains(response, "По территориальному органу")
        self.assertContains(response, "disabled")
        self.assertNotContains(response, "группировка: По территориальному органу")

    def test_tmc_table_can_group_by_request_date(self):
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        first = TmcRequest.objects.create(territorial_organ=self.organ, request_number="57/TMC", request_date="2026-06-20", status="in_work")
        second = TmcRequest.objects.create(territorial_organ=other_organ, request_number="58/TMC", request_date="2026-06-20", status="in_work")
        third = TmcRequest.objects.create(territorial_organ=other_organ, request_number="59/TMC", request_date="2026-06-21", status="done")
        TmcRequestItem.objects.create(request=first, name="Бумага А4", quantity=5, unit="пач.")
        TmcRequestItem.objects.create(request=second, name="Кресло офисное", quantity=2, unit="шт.")
        TmcRequestItem.objects.create(request=third, name="Сканер", quantity=1, unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "group": "dates"},
        )

        self.assertContains(response, "Дата")
        self.assertContains(response, "20.06.2026")
        self.assertContains(response, "21.06.2026")
        self.assertContains(response, "Территориальных органов")
        self.assertContains(response, "группировка: По дате")
        self.assertContains(response, "дней")
        self.assertContains(response, "Дней найдено")
        self.assertContains(response, "<td class=\"text-center\">2</td>", html=True)
        self.assertNotContains(response, "tmc-drilldown-link")
        self.assertContains(response, "summary-pill-in-work")

    def test_table_active_conditions_show_filters_and_reset(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="47/TMC",
            request_date="2026-06-20",
            status="in_work",
            comment="Office paper",
        )
        TmcRequestItem.objects.create(request=request_obj, name="Бумага А4", quantity=5, unit="пач.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
            {"q": "бумага", "status": "in_work", "date_from": "2026-06-01", "date_to": "2026-06-30"},
        )

        self.assertContains(response, "Применены фильтры:")
        self.assertContains(response, "поиск: бумага")
        self.assertContains(response, "исполнение: В работе")
        self.assertContains(response, "с 01.06.2026")
        self.assertContains(response, "по 30.06.2026")
        self.assertContains(response, "Сбросить все")
        self.assertContains(response, "data-reset-table-state")
        self.assertContains(response, 'hx-target="#workspace"')
        self.assertContains(response, f'{reverse("department_tables", args=[self.organ.pk, "tmc"])}?table=tmc-requests')
        self.assertNotContains(response, "Сбросить фильтры")

    def test_request_table_search_triggers_while_typing(self):
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))

        self.assertContains(response, 'id="table-search-tmc-requests"')
        self.assertContains(response, "input changed delay:1200ms from:#table-search-tmc-requests")
        self.assertContains(response, 'hx-sync="this:replace"')
        self.assertContains(response, "hx-preserve")
        self.assertContains(response, "data-preserve-search-focus")
        self.assertContains(response, "change")
        self.assertNotContains(response, "from:input")

    def test_tmc_search_is_case_insensitive_for_cyrillic(self):
        matching = TmcRequest.objects.create(territorial_organ=self.organ, request_number="32/TMC", request_date="2026-06-20", status="in_work", comment="Склад")
        TmcRequestItem.objects.create(request=matching, name="Стол письменный", quantity=2, unit="шт.")
        other = TmcRequest.objects.create(territorial_organ=self.organ, request_number="33/TMC", request_date="2026-06-20", status="in_work", comment="Кабинет")
        TmcRequestItem.objects.create(request=other, name="Кресло офисное", quantity=1, unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]), {"q": "стол"})

        self.assertContains(response, "32/TMC")
        self.assertContains(response, "Стол письменный")
        self.assertNotContains(response, "33/TMC")

    def test_tmc_in_work_counter_ignores_selected_status_filter(self):
        in_work = TmcRequest.objects.create(territorial_organ=self.organ, request_number="28/TMC", request_date="2026-06-20", status="in_work", comment="Office")
        TmcRequestItem.objects.create(request=in_work, name="Monitor", quantity=1, unit="pcs")
        done = TmcRequest.objects.create(territorial_organ=self.organ, request_number="29/TMC", request_date="2026-06-20", status="done", comment="Office")
        TmcRequestItem.objects.create(request=done, name="Monitor", quantity=1, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "tmc-requests"]),
            {"status": "done", "date_from": "2026-06-01", "date_to": "2026-06-30", "q": "Monitor"},
        )

        self.assertContains(response, "29/TMC")
        self.assertNotContains(response, "28/TMC")
        self.assertContains(response, "В работе")
        self.assertContains(response, "Исполнено")
        self.assertContains(response, "<strong>1</strong>", html=True)

    def test_tmc_date_filters_have_default_range(self):
        today = timezone.localdate()
        oldest_date = today - timedelta(days=10)
        oldest = TmcRequest.objects.create(territorial_organ=self.organ, request_number="30/TMC", request_date=oldest_date, status="in_work")
        TmcRequestItem.objects.create(request=oldest, name="Archive box", quantity=1, unit="pcs")
        future = TmcRequest.objects.create(territorial_organ=self.organ, request_number="31/TMC", request_date=today + timedelta(days=1), status="in_work")
        TmcRequestItem.objects.create(request=future, name="Future item", quantity=1, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))

        self.assertContains(response, f'value="{oldest_date.isoformat()}"')
        self.assertContains(response, f'value="{today.isoformat()}"')
        self.assertContains(response, f'data-default-date-from="{oldest_date.isoformat()}"')
        self.assertContains(response, f'data-default-date-to="{today.isoformat()}"')
        self.assertContains(response, "30/TMC")
        self.assertNotContains(response, "31/TMC")

    def test_tmc_date_filters_default_to_today_without_records(self):
        today = timezone.localdate()
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))

        self.assertContains(response, f'name="date_from" value="{today.isoformat()}"')
        self.assertContains(response, f'name="date_to" value="{today.isoformat()}"')
        self.assertContains(response, f'data-default-date-from="{today.isoformat()}"')
        self.assertContains(response, f'data-default-date-to="{today.isoformat()}"')
        self.assertContains(response, "data-date-range-picker")
        self.assertContains(response, "data-date-range-popover")

    def test_table_pagination_uses_photo_style_controls_above_table(self):
        for index in range(21):
            request_obj = TmcRequest.objects.create(
                territorial_organ=self.organ,
                request_number=f"PAGE-{index:02d}",
                request_date="2026-06-20",
                status="in_work",
            )
            TmcRequestItem.objects.create(request=request_obj, name="Paper", quantity=1, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))

        self.assertContains(response, 'class="table-pagination"')
        self.assertContains(response, 'class="photo-page-number is-active"')
        self.assertContains(response, "page=2")
        self.assertContains(response, 'class="pagination-jump"')
        self.assertContains(response, 'name="page"')
        self.assertContains(response, f"/ {response.context['page'].paginator.num_pages}")
        self.assertNotContains(response, "pagination-jump-submit")
        self.assertNotContains(response, "btn-group btn-group-sm")

    def test_tmc_xlsx_export_uses_current_filters(self):
        included = TmcRequest.objects.create(territorial_organ=self.organ, request_number="26/TMC", request_date="2026-06-20", status="in_work")
        TmcRequestItem.objects.create(request=included, name="Scanner", quantity=1, unit="pcs")
        excluded = TmcRequest.objects.create(territorial_organ=self.organ, request_number="27/TMC", request_date="2026-06-20", status="done")
        TmcRequestItem.objects.create(request=excluded, name="Scanner", quantity=1, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("export_table", args=[self.organ.pk, "tmc-requests", "xlsx"]), {"status": "in_work", "q": "Scanner", "download_token": "exporttest"})

        self.assertIn("download-ready-exporttest", response.cookies)
        workbook = self.response_workbook(response)
        sheet = workbook.active
        values = [cell.value for row in sheet.iter_rows() for cell in row]
        self.assertIn("26/TMC", values)
        self.assertNotIn("27/TMC", values)

    def test_tmc_xlsx_export_includes_organ_column_for_multi_organ_mode(self):
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        first = TmcRequest.objects.create(territorial_organ=self.organ, request_number="28/TMC", request_date="2026-06-20", status="in_work")
        second = TmcRequest.objects.create(territorial_organ=other_organ, request_number="29/TMC", request_date="2026-06-21", status="done")
        TmcRequestItem.objects.create(request=first, name="Бумага А4", quantity=5, unit="пач.")
        TmcRequestItem.objects.create(request=first, name="Папка-регистратор", quantity=2, unit="шт.")
        TmcRequestItem.objects.create(request=second, name="Кресло офисное", quantity=1, unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("export_table", args=[self.organ.pk, "tmc-requests", "xlsx"]),
            {"organ_ids": [self.organ.pk, other_organ.pk]},
        )

        workbook = self.response_workbook(response)
        sheet = workbook.active
        self.assertEqual(sheet["A1"].value, "Территориальный орган")
        self.assertEqual(sheet["B1"].value, "Сведения о потребности ТМЦ")
        self.assertEqual(sheet["D1"].value, "Заявка")
        self.assertEqual(sheet["G1"].value, "Описание")
        values = [cell.value for row in sheet.iter_rows() for cell in row]
        self.assertIn("Test territorial organ", values)
        self.assertIn("Other territorial organ", values)
        self.assertIn("28/TMC", values)
        self.assertIn("29/TMC", values)
        self.assertIn("Бумага А4", values)
        self.assertIn("Папка-регистратор", values)
        self.assertIn("Кресло офисное", values)

    def test_tmc_xlsx_export_objects_avoid_n_plus_one_on_items(self):
        # tmc_xlsx_response() (and every other styled export) iterates
        # querysets via export_objects(), which must not re-query items per
        # row. request_table_queryset() already prefetches "items" (see
        # REQUEST_TABLE_CONFIG); the thing actually worth pinning down is that
        # export_objects()'s qs.iterator(chunk_size=1000) doesn't silently
        # drop that prefetch — Django only started honoring
        # prefetch_related() under iterator() when chunk_size is given.
        request = RequestFactory().get("/")
        request.user = self.user

        def build_requests(count):
            for index in range(count):
                obj = TmcRequest.objects.create(
                    territorial_organ=self.organ,
                    request_number=f"nplusone-{index}",
                    request_date="2026-06-20",
                    status="in_work",
                )
                TmcRequestItem.objects.create(request=obj, name="Item A", quantity=1, unit="шт.")
                TmcRequestItem.objects.create(request=obj, name="Item B", quantity=2, unit="шт.")

        def touch_items(qs):
            for obj in export_objects(qs):
                list(obj.items.all())

        build_requests(3)
        qs_small = request_table_queryset(request, "tmc-requests", [self.organ], include_status=True)
        qs_small = qs_small.filter(request_number__startswith="nplusone-")
        with CaptureQueriesContext(connection) as small_queries:
            touch_items(qs_small)

        build_requests(12)
        qs_large = request_table_queryset(request, "tmc-requests", [self.organ], include_status=True)
        qs_large = qs_large.filter(request_number__startswith="nplusone-")
        with CaptureQueriesContext(connection) as large_queries:
            touch_items(qs_large)

        # If items were being re-fetched per request (N+1), query count would
        # scale with row count (3 vs 15 rows); with prefetch actually
        # respected, both chunks fit in a single iterator batch and the
        # query count stays flat regardless of how many rows are in it.
        self.assertEqual(len(small_queries.captured_queries), len(large_queries.captured_queries))

    def test_tmc_grouped_xlsx_export_matches_grouped_table(self):
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        first = TmcRequest.objects.create(territorial_organ=self.organ, request_number="48/TMC", request_date="2026-06-20", status="in_work")
        second = TmcRequest.objects.create(territorial_organ=other_organ, request_number="49/TMC", request_date="2026-06-21", status="in_work")
        TmcRequestItem.objects.create(request=first, name="Бумага А4", quantity=5, unit="пач.")
        TmcRequestItem.objects.create(request=second, name="Бумага А4", quantity=7, unit="пач.")
        TmcRequestItem.objects.create(request=second, name="Кресло офисное", quantity=1, unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("export_table", args=[self.organ.pk, "tmc-requests", "xlsx"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "group": "products"},
        )

        workbook = self.response_workbook(response)
        sheet = workbook.active
        self.assertEqual(sheet.title, "ТМЦ")
        self.assertEqual([sheet.cell(row=1, column=column).value for column in range(1, 6)], ["Наименование ТМЦ", "Заявок", "Территориальных органов", "Общее количество", "Единица измерения"])
        values = [cell.value for row in sheet.iter_rows() for cell in row]
        self.assertIn("Бумага А4", values)
        self.assertIn("Кресло офисное", values)
        self.assertIn(12, values)
        self.assertNotIn("48/TMC", values)
        self.assertNotIn("49/TMC", values)

    def test_tmc_grouped_csv_export_matches_grouped_table(self):
        request_obj = TmcRequest.objects.create(territorial_organ=self.organ, request_number="50/TMC", request_date="2026-06-20", status="in_work")
        TmcRequestItem.objects.create(request=request_obj, name="Сканер", quantity=2, unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("export_table", args=[self.organ.pk, "tmc-requests", "csv"]), {"group": "products"})

        rows = list(csv.reader(self.response_bytes(response).decode("utf-8-sig").splitlines()))
        self.assertEqual(rows[0], ["Наименование ТМЦ", "Заявок", "Общее количество", "Единица измерения"])
        self.assertEqual(rows[1], ["Сканер", "1", "2", "шт."])
        self.assertNotIn("50/TMC", ",".join(rows[1]))

    def test_tmc_organ_grouped_csv_export_matches_grouped_table(self):
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        first = TmcRequest.objects.create(territorial_organ=self.organ, request_number="55/TMC", request_date="2026-06-20", status="in_work")
        second = TmcRequest.objects.create(territorial_organ=other_organ, request_number="56/TMC", request_date="2026-06-21", status="in_work")
        TmcRequestItem.objects.create(request=first, name="Бумага А4", quantity=5, unit="пач.")
        TmcRequestItem.objects.create(request=second, name="Кресло офисное", quantity=2, unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("export_table", args=[self.organ.pk, "tmc-requests", "csv"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "group": "organs"},
        )

        rows = list(csv.reader(self.response_bytes(response).decode("utf-8-sig").splitlines()))
        self.assertEqual(rows[0], ["Территориальный орган", "Заявок", "Позиций ТМЦ", "Общее количество", "В работе", "Исполнено", "Отклонено"])
        self.assertIn(["Test territorial organ", "1", "1", "5", "1", "0", "0"], rows)
        self.assertIn(["Other territorial organ", "1", "1", "2", "1", "0", "0"], rows)
        self.assertNotIn("55/TMC", ",".join(",".join(row) for row in rows))

    def test_tmc_date_grouped_csv_export_matches_grouped_table(self):
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        first = TmcRequest.objects.create(territorial_organ=self.organ, request_number="60/TMC", request_date="2026-06-20", status="in_work")
        second = TmcRequest.objects.create(territorial_organ=other_organ, request_number="61/TMC", request_date="2026-06-20", status="in_work")
        TmcRequestItem.objects.create(request=first, name="Бумага А4", quantity=5, unit="пач.")
        TmcRequestItem.objects.create(request=second, name="Кресло офисное", quantity=2, unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("export_table", args=[self.organ.pk, "tmc-requests", "csv"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "group": "dates"},
        )

        rows = list(csv.reader(self.response_bytes(response).decode("utf-8-sig").splitlines()))
        self.assertEqual(rows[0], ["Дата", "Заявок", "Территориальных органов", "Позиций ТМЦ", "Общее количество", "В работе", "Исполнено", "Отклонено"])
        self.assertIn(["20.06.2026", "2", "2", "2", "7", "2", "0", "0"], rows)
        self.assertNotIn("60/TMC", ",".join(",".join(row) for row in rows))

    def test_tmc_item_errors_use_common_modal_style(self):
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_create", args=[self.organ.pk, "tmc-requests"]),
            {
                "request_number": "19/TMC",
                "request_date": "2026-06-27",
                "status": "in_work",
                "comment": "",
                "item_name": [""],
                "item_quantity": [""],
                "item_unit": ["шт."],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "modal-error-list tmc-item-errors")
        self.assertContains(response, "Добавьте хотя бы одну позицию заявки.")
        self.assertContains(response, "data-add-tmc-item")
        self.assertContains(response, "data-tmc-item-row")
        self.assertFalse(TmcRequest.objects.filter(request_number="19/TMC").exists())
