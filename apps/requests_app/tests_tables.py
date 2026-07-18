from .tests_base import *


class DepartmentTableTests(RequestAppTestCase):

    def test_status_history_button_is_hidden_without_history(self):
        request_without_history = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="18/TMC",
            request_date="2026-06-26",
            status="in_work",
        )
        request_with_history = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="19/TMC",
            request_date="2026-06-27",
            status="done",
        )
        RequestStatusHistory.objects.create(
            content_type=ContentType.objects.get_for_model(request_with_history, for_concrete_model=False),
            object_id=request_with_history.pk,
            old_status="in_work",
            new_status="done",
            changed_by=self.user,
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))

        self.assertNotContains(response, reverse("tmc_status_history", args=[self.organ.pk, request_without_history.pk]))
        self.assertContains(response, reverse("tmc_status_history", args=[self.organ.pk, request_with_history.pk]))


    def test_table_date_cells_do_not_wrap_date_text(self):
        TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="20/TMC",
            request_date="2026-07-06",
            status="in_work",
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))

        self.assertContains(response, 'class="tmc-request-cell table-date-cell', html=False)
        self.assertContains(response, '<span class="table-date-value">06.07.2026</span>', html=False)

    def test_created_status_history_label_is_capitalized(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            request_number="21/TMC",
            request_date="2026-07-06",
            status="in_work",
        )
        history = RequestStatusHistory.objects.create(
            content_type=ContentType.objects.get_for_model(request_obj, for_concrete_model=False),
            object_id=request_obj.pk,
            old_status=None,
            new_status="in_work",
            changed_by=self.user,
        )

        self.assertEqual(str(history), "Создана -> В работе")

    def test_citsizi_filter_by_equipment_type(self):
        CitsiziEquipment.objects.create(territorial_organ=self.organ, request_number="C-1", request_date="2026-06-20", equipment_type="communication", quantity=1)
        CitsiziEquipment.objects.create(territorial_organ=self.organ, request_number="C-2", request_date="2026-06-20", equipment_type="computing", quantity=1)
        self.client.login(username="operator", password="pass12345")
        response = self.client.get(reverse("table_data", args=[self.organ.pk, "citsizi-equipment"]), {"equipment_type": "communication"})
        self.assertContains(response, "C-1")
        self.assertContains(response, "Средства связи")
        self.assertNotContains(response, "C-2")

    def test_citsizi_form_includes_sound_alert_equipment_type(self):
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("record_create", args=[self.organ.pk, "citsizi-equipment"]), HTTP_HX_REQUEST="true")

        self.assertContains(response, 'hx-target="#table-area"')
        self.assertContains(response, "novalidate")
        self.assertEqual(response.content.decode().count("<form"), 1)
        self.assertNotContains(response, '<form class="pagination-jump"', html=False)
        self.assertContains(response, "Выберите тип техники")
        self.assertNotContains(response, "---------")
        self.assertContains(response, f'value="{EquipmentType.SOUND_ALERT}"')

    def test_citsizi_equipment_type_is_required(self):
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_create", args=[self.organ.pk, "citsizi-equipment"]),
            {
                "request_number": "C-empty",
                "request_date": "2026-06-20",
                "quantity": "1",
                "status": "in_work",
                "equipment_type": "",
                "comment": "",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Выберите тип техники")
        self.assertContains(response, 'hx-target="#table-area"')
        self.assertEqual(response["HX-Retarget"], "#modal-content")
        self.assertIn("equipment_type", response.context["form"].errors)
        self.assertFalse(CitsiziEquipment.objects.filter(request_number="C-empty").exists())

    def test_citsizi_valid_create_retargets_table_area(self):
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_create", args=[self.organ.pk, "citsizi-equipment"]),
            {
                "request_number": "C-valid",
                "request_date": "2026-06-20",
                "quantity": "1",
                "status": "in_work",
                "equipment_type": EquipmentType.COMMUNICATION,
                "comment": "",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HX-Retarget", response)
        self.assertTrue(CitsiziEquipment.objects.filter(request_number="C-valid").exists())
        self.assertContains(response, "C-valid")

    def test_citsizi_request_table_history_filters_and_styled_export(self):
        included = CitsiziEquipment.objects.create(territorial_organ=self.organ, request_number="C-10", request_date="2026-06-20", equipment_type="communication", quantity=3, status="in_work", comment="Install radio")
        excluded = CitsiziEquipment.objects.create(territorial_organ=self.organ, request_number="C-11", request_date="2026-06-20", equipment_type="computing", quantity=2, status="done")
        self.create_status_history_entry(included)
        self.client.login(username="operator", password="pass12345")

        table_response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "citsizi-equipment"]),
            {"status": "in_work", "equipment_type": "communication", "date_from": "2026-06-01", "date_to": "2026-06-30", "q": "C-10"},
        )
        self.assertContains(table_response, "<th>Номер</th>", html=True)
        self.assertContains(table_response, "<th>Дата</th>", html=True)
        self.assertContains(table_response, "<th>Количество</th>", html=True)
        self.assertContains(table_response, "<th>Исполнение</th>", html=True)
        self.assertContains(table_response, "<th>Тип техники</th>", html=True)
        self.assertContains(table_response, "<th>Описание</th>", html=True)
        self.assertContains(table_response, "Install radio")
        self.assertContains(table_response, included.request_number)
        self.assertNotContains(table_response, excluded.request_number)
        self.assertContains(table_response, "equipment_type=communication")
        self.assertContains(table_response, "bi-clock-history")

        update_response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "citsizi-equipment", included.pk]),
            {
                "request_number": "C-10",
                "request_date": "2026-06-20",
                "quantity": "3",
                "status": "done",
                "equipment_type": "communication",
                "due_date": "2026-06-29",
                "comment": "Install radio completed",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(update_response.status_code, 200)
        history = self.status_history(included).get(old_status="in_work", new_status="done")
        self.assertEqual(history.completed_at.isoformat(), "2026-06-29")

        modal = self.client.get(reverse("citsizi_status_history", args=[self.organ.pk, included.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(modal, "История изменений статуса заявки C-10")

        export_response = self.client.get(reverse("export_table", args=[self.organ.pk, "citsizi-equipment", "xlsx"]), {"status": "done", "equipment_type": "communication"})
        workbook = self.response_workbook(export_response)
        sheet = workbook.active
        self.assertEqual(sheet["A1"].value, "Номер")
        self.assertEqual(sheet["E1"].value, "Тип техники")
        self.assertEqual(sheet["F1"].value, "Описание")
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet["F1"].border.right.style, "medium")

    def test_regular_table_headers_start_with_capital_letter(self):
        VehicleInventory.objects.create(territorial_organ=self.organ, required_count=5, available_count=4, broken_count=1, writeoff_count=0)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "vehicle-inventory"]))

        self.assertContains(response, "<th>Положено</th>", html=True)
        self.assertNotContains(response, "<th>положено</th>", html=True)

        export_response = self.client.get(reverse("export_table", args=[self.organ.pk, "vehicle-inventory", "xlsx"]))
        workbook = self.response_workbook(export_response)
        sheet = workbook.active
        self.assertEqual(sheet["B1"].value, "Положено")
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet["A1"].fill.fgColor.rgb, "00D6EAF7")
        self.assertEqual(sheet["A1"].border.bottom.style, "medium")

    def test_vehicle_inventory_has_date_as_first_column(self):
        VehicleInventory.objects.create(
            territorial_organ=self.organ,
            state_date="2026-06-27",
            required_count=5,
            available_count=4,
            broken_count=1,
            writeoff_count=0,
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "vehicle-inventory"]))

        self.assertContains(response, "<th>Дата</th>", html=True)
        self.assertContains(response, "table-vehicle-inventory")

        export_response = self.client.get(reverse("export_table", args=[self.organ.pk, "vehicle-inventory", "xlsx"]))
        workbook = self.response_workbook(export_response)
        sheet = workbook.active
        self.assertEqual(sheet["A1"].value, "Дата")
        self.assertEqual(sheet["B1"].value, "Положено")
        self.assertEqual(sheet.column_dimensions["E"].width, 38)
        self.assertEqual(sheet["A2"].alignment.horizontal, "center")
        self.assertEqual(sheet["E2"].border.right.style, "medium")

    def test_vehicle_repair_request_shows_comment_column(self):
        request_obj = VehicleRepairRequest.objects.create(
            territorial_organ=self.organ,
            request_number="R-1",
            request_date="2026-06-27",
            status="in_work",
            comment="Needs diagnostics",
        )
        self.create_status_history_entry(request_obj)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "vehicle-repair"]))

        self.assertNotContains(response, "<th>Дата исполнения / отклонения</th>", html=True)
        self.assertContains(response, "<th>Описание</th>", html=True)
        self.assertContains(response, "Needs diagnostics")
        self.assertContains(response, "table-vehicle-repair")
        self.assertContains(response, "table-row-actions")
        self.assertContains(response, "bi-clock-history")

        export_response = self.client.get(reverse("export_table", args=[self.organ.pk, "vehicle-repair", "xlsx"]))
        workbook = self.response_workbook(export_response)
        sheet = workbook.active
        self.assertEqual(sheet["D1"].value, "Описание")
        self.assertEqual(sheet["D2"].value, "Needs diagnostics")
        self.assertIsNone(sheet["E1"].value)
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet["D1"].fill.fgColor.rgb, "00D6EAF7")
        self.assertEqual(sheet["D1"].border.right.style, "medium")
        self.assertEqual(sheet["A2"].alignment.horizontal, "center")
        self.assertIsNone(sheet["D2"].alignment.horizontal)

    def test_request_date_defaults_to_today_in_create_form(self):
        today = timezone.localdate()
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("record_create", args=[self.organ.pk, "vehicle-repair"]), HTTP_HX_REQUEST="true")

        self.assertContains(response, 'name="request_date"')
        self.assertContains(response, f'value="{today.isoformat()}"')
        self.assertContains(response, 'name="completed_at"')
        self.assertContains(response, "Дата исполнения / отклонения")

    def test_vehicle_repair_status_history_records_completed_date(self):
        request_obj = VehicleRepairRequest.objects.create(
            territorial_organ=self.organ,
            request_number="R-2",
            request_date="2026-06-27",
            status="in_work",
            comment="Initial",
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "vehicle-repair", request_obj.pk]),
            {
                "request_number": "R-2",
                "request_date": "2026-06-27",
                "status": "done",
                "completed_at": "2026-06-29",
                "comment": "Completed",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        history = self.status_history(request_obj).get(old_status="in_work", new_status="done")
        self.assertEqual(history.completed_at.isoformat(), "2026-06-29")

        modal = self.client.get(reverse("vehicle_repair_status_history", args=[self.organ.pk, request_obj.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(modal, "История изменений статуса заявки R-2")
        self.assertContains(modal, "Дата исполнения / отклонения")
        self.assertContains(modal, "29.06.2026")

    def test_vehicle_repair_terminal_statuses_default_completion_date_to_today(self):
        self.client.login(username="operator", password="pass12345")

        for index, status in enumerate(("done", "rejected"), start=1):
            with self.subTest(status=status):
                request_obj = VehicleRepairRequest.objects.create(
                    territorial_organ=self.organ,
                    request_number=f"R-AUTO-{index}",
                    request_date="2026-06-27",
                    status="in_work",
                    comment="Initial",
                )

                response = self.client.post(
                    reverse("record_update", args=[self.organ.pk, "vehicle-repair", request_obj.pk]),
                    {
                        "request_number": request_obj.request_number,
                        "request_date": "2026-06-27",
                        "status": status,
                        "completed_at": "",
                        "comment": "Initial",
                    },
                    HTTP_HX_REQUEST="true",
                )

                self.assertEqual(response.status_code, 200)
                request_obj.refresh_from_db()
                self.assertEqual(request_obj.completed_at, timezone.localdate())
                history = self.status_history(request_obj).get(old_status="in_work", new_status=status)
                self.assertEqual(history.completed_at, timezone.localdate())

    def test_vehicle_repair_in_work_status_clears_completion_date(self):
        request_obj = VehicleRepairRequest.objects.create(
            territorial_organ=self.organ,
            request_number="R-REOPEN",
            request_date="2026-06-27",
            status="done",
            completed_at="2026-06-29",
            comment="Initial",
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "vehicle-repair", request_obj.pk]),
            {
                "request_number": request_obj.request_number,
                "request_date": "2026-06-27",
                "status": "in_work",
                "completed_at": "2026-06-29",
                "comment": "Initial",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        request_obj.refresh_from_db()
        self.assertIsNone(request_obj.completed_at)
        history = self.status_history(request_obj).get(old_status="done", new_status="in_work")
        self.assertIsNone(history.completed_at)

    def test_status_change_creates_one_audit_event_with_completion_date(self):
        request_obj = VehicleRepairRequest.objects.create(
            territorial_organ=self.organ,
            request_number="R-AUDIT-1",
            request_date="2026-06-27",
            status="in_work",
            comment="Initial",
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "vehicle-repair", request_obj.pk]),
            {
                "request_number": "R-AUDIT-1",
                "request_date": "2026-06-27",
                "status": "done",
                "completed_at": "2026-06-29",
                "comment": "Initial",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        logs = AuditLog.objects.filter(model_name="VehicleRepairRequest", object_id=str(request_obj.pk))
        self.assertEqual(
            logs.count(),
            1,
            list(logs.values("event_type", "old_values", "new_values")),
        )
        log = logs.get()
        self.assertEqual(log.event_type, AuditLog.EventType.STATUS_CHANGED)
        self.assertEqual(log.old_values["status"], "in_work")
        self.assertEqual(log.new_values["status"], "done")
        self.assertEqual(log.new_values["completed_at"], "2026-06-29")
        self.assertNotIn("comment", log.new_values)
        self.assertFalse(logs.filter(event_type=AuditLog.EventType.RECORD_UPDATED).exists())

    def test_status_change_and_comment_edit_create_two_distinct_audit_events(self):
        request_obj = VehicleRepairRequest.objects.create(
            territorial_organ=self.organ,
            request_number="R-AUDIT-2",
            request_date="2026-06-27",
            status="in_work",
            comment="Initial",
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "vehicle-repair", request_obj.pk]),
            {
                "request_number": "R-AUDIT-2",
                "request_date": "2026-06-27",
                "status": "done",
                "completed_at": "2026-06-29",
                "comment": "Updated description",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        logs = AuditLog.objects.filter(model_name="VehicleRepairRequest", object_id=str(request_obj.pk))
        self.assertEqual(logs.count(), 2)
        status_log = logs.get(event_type=AuditLog.EventType.STATUS_CHANGED)
        update_log = logs.get(event_type=AuditLog.EventType.RECORD_UPDATED)
        self.assertTrue(status_log.operation_id)
        self.assertEqual(status_log.operation_id, update_log.operation_id)
        self.assertEqual(status_log.old_values["status"], "in_work")
        self.assertEqual(status_log.new_values["status"], "done")
        self.assertEqual(status_log.new_values["completed_at"], "2026-06-29")
        self.assertNotIn("comment", status_log.new_values)
        self.assertEqual(update_log.old_values["comment"], "Initial")
        self.assertEqual(update_log.new_values["comment"], "Updated description")
        self.assertNotIn("status", update_log.new_values)
        self.assertNotIn("completed_at", update_log.new_values)

    def test_vehicle_repair_filters_by_status_date_range_and_text(self):
        matching = VehicleRepairRequest.objects.create(territorial_organ=self.organ, request_number="R-10", request_date="2026-06-20", status="in_work", comment="Diagnostics")
        wrong_status = VehicleRepairRequest.objects.create(territorial_organ=self.organ, request_number="R-11", request_date="2026-06-20", status="done", comment="Diagnostics")
        wrong_date = VehicleRepairRequest.objects.create(territorial_organ=self.organ, request_number="R-12", request_date="2026-05-20", status="in_work", comment="Diagnostics")
        wrong_text = VehicleRepairRequest.objects.create(territorial_organ=self.organ, request_number="R-13", request_date="2026-06-20", status="in_work", comment="Oil")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "vehicle-repair"]),
            {"status": "in_work", "date_from": "2026-06-01", "date_to": "2026-06-30", "q": "Diagnostics"},
        )

        self.assertContains(response, matching.request_number)
        self.assertNotContains(response, wrong_status.request_number)
        self.assertNotContains(response, wrong_date.request_number)
        self.assertNotContains(response, wrong_text.request_number)
        self.assertContains(response, "status=in_work")
        self.assertContains(response, "date_from=2026-06-01")
        self.assertContains(response, "date_to=2026-06-30")
        self.assertContains(response, "q=Diagnostics")
        self.assertContains(response, "В работе")
        self.assertNotContains(response, 'value="new"')
        self.assertNotContains(response, "Новых")
        self.assertContains(response, "Исполнено")
        self.assertContains(response, "Отклонено")

    def test_vehicle_repair_xlsx_export_uses_current_filters(self):
        included = VehicleRepairRequest.objects.create(territorial_organ=self.organ, request_number="R-20", request_date="2026-06-20", status="in_work", comment="Transmission")
        excluded = VehicleRepairRequest.objects.create(territorial_organ=self.organ, request_number="R-21", request_date="2026-06-20", status="done", comment="Transmission")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("export_table", args=[self.organ.pk, "vehicle-repair", "xlsx"]), {"status": "in_work", "q": "Transmission"})

        workbook = self.response_workbook(response)
        values = [cell.value for row in workbook.active.iter_rows() for cell in row]
        self.assertIn(included.request_number, values)
        self.assertNotIn(excluded.request_number, values)

    def test_request_tables_support_date_and_organ_grouping(self):
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        VehicleRepairRequest.objects.create(territorial_organ=self.organ, request_number="R-30", request_date="2026-06-20", status="in_work", comment="Diagnostics")
        VehicleRepairRequest.objects.create(territorial_organ=other_organ, request_number="R-31", request_date="2026-06-20", status="done", comment="Diagnostics")
        VehicleRepairRequest.objects.create(territorial_organ=other_organ, request_number="R-32", request_date="2026-06-21", status="rejected", comment="Oil")
        self.client.login(username="operator", password="pass12345")

        date_response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "vehicle-repair"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "group": "dates"},
        )
        self.assertContains(date_response, "По заявкам")
        self.assertContains(date_response, "По дате")
        self.assertContains(date_response, "По территориальному органу")
        self.assertNotContains(date_response, "По ТМЦ")
        self.assertContains(date_response, "20.06.2026")
        self.assertContains(date_response, "21.06.2026")
        self.assertContains(date_response, "В работе")
        self.assertContains(date_response, "Исполнено")
        self.assertContains(date_response, "Отклонено")
        self.assertContains(date_response, "группировка: По дате")
        self.assertNotContains(date_response, "R-30")

        organ_response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "vehicle-repair"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "group": "organs"},
        )
        self.assertContains(organ_response, "Test territorial organ")
        self.assertContains(organ_response, "Other territorial organ")
        self.assertContains(organ_response, "группировка: По территориальному органу")
        self.assertNotContains(organ_response, "R-31")

        export_response = self.client.get(
            reverse("export_table", args=[self.organ.pk, "vehicle-repair", "csv"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "group": "dates"},
        )
        rows = list(csv.reader(self.response_bytes(export_response).decode("utf-8-sig").splitlines()))
        self.assertEqual(rows[0], ["Дата", "Заявок", "Территориальных органов", "В работе", "Исполнено", "Отклонено"])
        self.assertIn(["20.06.2026", "2", "2", "1", "1", "0"], rows)
        self.assertNotIn("R-30", ",".join(",".join(row) for row in rows))

    def test_vehicle_fuel_request_matches_vehicle_repair_table_behavior(self):
        request_obj = VehicleFuelRequest.objects.create(
            territorial_organ=self.organ,
            request_number="GSM-1",
            request_date="2026-06-27",
            status="in_work",
            comment="Fuel cards",
        )
        self.create_status_history_entry(request_obj)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "vehicle-fuel"]))

        self.assertContains(response, "<th>Описание</th>", html=True)
        self.assertContains(response, "Fuel cards")
        self.assertContains(response, "table-vehicle-fuel")
        self.assertContains(response, "bi-clock-history")

        export_response = self.client.get(reverse("export_table", args=[self.organ.pk, "vehicle-fuel", "xlsx"]))
        workbook = self.response_workbook(export_response)
        sheet = workbook.active
        self.assertEqual(sheet["A1"].value, "Номер")
        self.assertEqual(sheet["D1"].value, "Описание")
        self.assertEqual(sheet["D2"].value, "Fuel cards")
        self.assertEqual(sheet["D1"].border.right.style, "medium")

    def test_vehicle_fuel_status_history_records_completed_date(self):
        request_obj = VehicleFuelRequest.objects.create(
            territorial_organ=self.organ,
            request_number="GSM-2",
            request_date="2026-06-27",
            status="in_work",
            comment="Initial",
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "vehicle-fuel", request_obj.pk]),
            {
                "request_number": "GSM-2",
                "request_date": "2026-06-27",
                "status": "done",
                "completed_at": "2026-06-29",
                "comment": "Completed",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        history = self.status_history(request_obj).get(old_status="in_work", new_status="done")
        self.assertEqual(history.completed_at.isoformat(), "2026-06-29")

        modal = self.client.get(reverse("vehicle_fuel_status_history", args=[self.organ.pk, request_obj.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(modal, "История изменений статуса заявки GSM-2")
        self.assertContains(modal, "Дата исполнения / отклонения")
        self.assertContains(modal, "29.06.2026")

    def test_fire_inventory_tabs_have_date_short_headers_and_styled_export(self):
        FireExtinguisher.objects.create(territorial_organ=self.organ, state_date="2026-06-27", required_count=10, available_count=8, expiry_date="2026-12-31", writeoff_count=1)
        FireAlarm.objects.create(territorial_organ=self.organ, state_date="2026-06-27", required_objects=5, equipped_objects=4, broken_objects=1)
        SecurityAlarm.objects.create(territorial_organ=self.organ, state_date="2026-06-27", required_objects=6, equipped_objects=5, broken_objects=1)
        self.client.login(username="operator", password="pass12345")

        extinguishers = self.client.get(reverse("table_data", args=[self.organ.pk, "fire-extinguishers"]))
        self.assertContains(extinguishers, "<th>Дата</th>", html=True)

        fire_alarm = self.client.get(reverse("table_data", args=[self.organ.pk, "fire-alarm"]))
        self.assertContains(fire_alarm, "Подлежит оборудованию ПС")
        self.assertContains(fire_alarm, "Оборудовано ПС объектов")
        self.assertContains(fire_alarm, "Объектов с неисправной ПС")

        security_alarm = self.client.get(reverse("table_data", args=[self.organ.pk, "security-alarm"]))
        self.assertContains(security_alarm, "Подлежит оборудованию ОС")
        self.assertContains(security_alarm, "Оборудовано ОС объектов")
        self.assertContains(security_alarm, "Объектов с неисправной ОС")

        export_response = self.client.get(reverse("export_table", args=[self.organ.pk, "fire-alarm", "xlsx"]))
        workbook = self.response_workbook(export_response)
        sheet = workbook.active
        self.assertEqual(sheet["A1"].value, "Дата")
        self.assertEqual(sheet["B1"].value, "Подлежит оборудованию ПС")
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet["A1"].fill.fgColor.rgb, "00D6EAF7")
        self.assertEqual(sheet["D2"].border.right.style, "medium")

    def test_fire_extinguisher_expiry_warning_is_cell_badge_only(self):
        today = timezone.localdate()
        FireExtinguisher.objects.create(territorial_organ=self.organ, state_date=today, required_count=10, available_count=8, expiry_date=today - timedelta(days=1), writeoff_count=1)
        FireExtinguisher.objects.create(territorial_organ=self.organ, state_date=today, required_count=10, available_count=8, expiry_date=today + timedelta(days=10), writeoff_count=1)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "fire-extinguishers"]), {"state_mode": "history"})

        self.assertContains(response, "Истек")
        self.assertContains(response, "Скоро истекает")
        self.assertContains(response, "status-rejected")
        self.assertContains(response, "status-in_work")
        self.assertNotContains(response, "row-expired")
        self.assertNotContains(response, "row-expiring")

    def test_state_snapshot_tables_show_current_records_by_default_and_history_on_request(self):
        other_organ = TerritorialOrgan.objects.create(name="Second territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        FireExtinguisher.objects.create(territorial_organ=self.organ, state_date="2026-06-01", required_count=10, available_count=6, expiry_date="2026-07-10", writeoff_count=1)
        FireExtinguisher.objects.create(territorial_organ=self.organ, state_date="2026-07-01", required_count=10, available_count=8, expiry_date="2026-12-31", writeoff_count=0)
        FireExtinguisher.objects.create(territorial_organ=other_organ, state_date="2026-07-02", required_count=12, available_count=9, expiry_date="2026-08-01", writeoff_count=1)
        FireAlarm.objects.create(territorial_organ=self.organ, state_date="2026-06-01", required_objects=5, equipped_objects=3, broken_objects=2)
        FireAlarm.objects.create(territorial_organ=self.organ, state_date="2026-07-01", required_objects=5, equipped_objects=5, broken_objects=0)
        SecurityAlarm.objects.create(territorial_organ=self.organ, state_date="2026-06-01", required_objects=7, equipped_objects=4, broken_objects=2)
        SecurityAlarm.objects.create(territorial_organ=self.organ, state_date="2026-07-01", required_objects=7, equipped_objects=6, broken_objects=1)
        ServiceHousing.objects.create(territorial_organ=self.organ, state_date="2026-06-01", total_count=10, used_by_staff=4, ready_to_move=6)
        ServiceHousing.objects.create(territorial_organ=self.organ, state_date="2026-07-01", total_count=10, used_by_staff=8, ready_to_move=2)
        self.client.login(username="operator", password="pass12345")

        extinguishers = self.client.get(
            reverse("table_data", args=[self.organ.pk, "fire-extinguishers"]),
            {"organ_ids": [self.organ.pk, other_organ.pk]},
        )
        self.assertContains(extinguishers, "Последняя запись")
        self.assertContains(extinguishers, "Second territorial organ")
        self.assertContains(extinguishers, "31.12.2026")
        self.assertNotContains(extinguishers, "10.07.2026")

        history = self.client.get(
            reverse("table_data", args=[self.organ.pk, "fire-extinguishers"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "state_mode": "history"},
        )
        self.assertContains(history, "режим: История записей")
        self.assertContains(history, "10.07.2026")
        self.assertContains(history, "31.12.2026")

        for table_key, old_value, current_value in (
            ("fire-alarm", "3", "5"),
            ("security-alarm", "4", "6"),
            ("service-housing", "4", "8"),
        ):
            response = self.client.get(reverse("table_data", args=[self.organ.pk, table_key]))
            self.assertContains(response, "Последняя запись")
            self.assertContains(response, current_value)
            self.assertNotContains(response, old_value)

    def test_fire_extinguishers_can_filter_sort_and_export_by_expiry(self):
        today = timezone.localdate()
        other_organ = TerritorialOrgan.objects.create(name="Second territorial organ", order_number=2)
        self.user.profile.allowed_organs.add(other_organ)
        FireExtinguisher.objects.create(territorial_organ=self.organ, state_date=today, required_count=10, available_count=8, expiry_date=today + timedelta(days=10), writeoff_count=1)
        FireExtinguisher.objects.create(territorial_organ=self.organ, state_date=today, required_count=5, available_count=5, expiry_date=today + timedelta(days=90), writeoff_count=0)
        FireExtinguisher.objects.create(territorial_organ=other_organ, state_date=today, required_count=12, available_count=7, expiry_date=today - timedelta(days=5), writeoff_count=2)
        FireExtinguisher.objects.create(territorial_organ=other_organ, state_date=today, required_count=6, available_count=4, expiry_date=today + timedelta(days=20), writeoff_count=0)
        self.client.login(username="operator", password="pass12345")

        grouped_response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "fire-extinguishers"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "expiry_state": "soon", "expiry_order": "soonest"},
        )

        self.assertContains(grouped_response, "Second territorial organ")
        self.assertContains(grouped_response, "data-date-range-picker")
        self.assertContains(grouped_response, 'name="expiry_from"')
        self.assertContains(grouped_response, 'name="expiry_to"')
        self.assertContains(grouped_response, "Скоро истекает")
        self.assertContains(grouped_response, (today + timedelta(days=20)).strftime("%d.%m.%Y"))
        self.assertNotContains(grouped_response, (today + timedelta(days=10)).strftime("%d.%m.%Y"))
        self.assertNotContains(grouped_response, (today + timedelta(days=90)).strftime("%d.%m.%Y"))
        self.assertNotContains(grouped_response, (today - timedelta(days=5)).strftime("%d.%m.%Y"))

        export_response = self.client.get(
            reverse("export_table", args=[self.organ.pk, "fire-extinguishers", "xlsx"]),
            {"organ_ids": [self.organ.pk, other_organ.pk], "expiry_state": "soon", "expiry_order": "soonest"},
        )
        workbook = self.response_workbook(export_response)
        sheet = workbook.active
        self.assertEqual(sheet.max_row, 2)
        self.assertEqual(sheet["D1"].value, "Срок годности (эксплуатации)")
        self.assertEqual(sheet["D2"].value, (today + timedelta(days=20)).strftime("%d.%m.%Y"))

    def test_fire_request_has_comment_history_filters_and_styled_export(self):
        included = FireDepartmentRequest.objects.create(territorial_organ=self.organ, request_number="F-1", request_date="2026-06-20", status="in_work", comment="Recharge")
        excluded = FireDepartmentRequest.objects.create(territorial_organ=self.organ, request_number="F-2", request_date="2026-06-20", status="done", comment="Recharge")
        self.create_status_history_entry(included)
        self.client.login(username="operator", password="pass12345")

        table_response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "fire-requests"]),
            {"status": "in_work", "date_from": "2026-06-01", "date_to": "2026-06-30", "q": "Recharge"},
        )
        self.assertContains(table_response, "<th>Описание</th>", html=True)
        self.assertContains(table_response, "bi-clock-history")
        self.assertContains(table_response, included.request_number)
        self.assertNotContains(table_response, excluded.request_number)
        self.assertContains(table_response, "status=in_work")
        self.assertContains(table_response, "В работе")

        update_response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "fire-requests", included.pk]),
            {
                "request_number": "F-1",
                "request_date": "2026-06-20",
                "status": "done",
                "completed_at": "2026-06-29",
                "comment": "Completed",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(update_response.status_code, 200)
        history = self.status_history(included).get(old_status="in_work", new_status="done")
        self.assertEqual(history.completed_at.isoformat(), "2026-06-29")

        modal = self.client.get(reverse("fire_request_status_history", args=[self.organ.pk, included.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(modal, "История изменений статуса заявки F-1")
        self.assertContains(modal, "Дата исполнения / отклонения")

        export_response = self.client.get(reverse("export_table", args=[self.organ.pk, "fire-requests", "xlsx"]), {"status": "done", "q": "Completed"})
        workbook = self.response_workbook(export_response)
        sheet = workbook.active
        self.assertEqual(sheet["D1"].value, "Описание")
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet["D1"].border.right.style, "medium")

    def test_anti_terror_request_table_history_filters_and_styled_export(self):
        included = AntiTerrorMeasure.objects.create(territorial_organ=self.organ, request_number="A-1", request_date="2026-06-20", status="in_work", comment="Survey act")
        excluded = AntiTerrorMeasure.objects.create(territorial_organ=self.organ, request_number="A-2", request_date="2026-06-20", status="done", comment="Survey act")
        self.create_status_history_entry(included)
        self.client.login(username="operator", password="pass12345")

        table_response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "anti-terror"]),
            {"status": "in_work", "date_from": "2026-06-01", "date_to": "2026-06-30", "q": "Survey"},
        )
        self.assertContains(table_response, "<th>Номер</th>", html=True)
        self.assertContains(table_response, "<th>Дата</th>", html=True)
        self.assertContains(table_response, "<th>Исполнение</th>", html=True)
        self.assertContains(table_response, "<th>Описание</th>", html=True)
        self.assertNotContains(table_response, "Потребность финансирования")
        self.assertContains(table_response, "bi-clock-history")
        self.assertContains(table_response, included.request_number)
        self.assertNotContains(table_response, excluded.request_number)
        self.assertContains(table_response, "status=in_work")

        update_response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "anti-terror", included.pk]),
            {
                "request_number": "A-1",
                "request_date": "2026-06-20",
                "status": "done",
                "completed_at": "2026-06-29",
                "comment": "Completed",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(update_response.status_code, 200)
        history = self.status_history(included).get(old_status="in_work", new_status="done")
        self.assertEqual(history.completed_at.isoformat(), "2026-06-29")

        modal = self.client.get(reverse("anti_terror_status_history", args=[self.organ.pk, included.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(modal, "История изменений статуса заявки A-1")

        export_response = self.client.get(reverse("export_table", args=[self.organ.pk, "anti-terror", "xlsx"]), {"status": "done", "q": "Completed"})
        workbook = self.response_workbook(export_response)
        sheet = workbook.active
        self.assertEqual(sheet["A1"].value, "Номер")
        self.assertEqual(sheet["D1"].value, "Описание")
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet["D1"].border.right.style, "medium")

    def test_uoto_service_housing_has_date_without_status(self):
        ServiceHousing.objects.create(territorial_organ=self.organ, state_date="2026-06-27", total_count=10, used_by_staff=7, ready_to_move=3)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "service-housing"]))

        self.assertContains(response, "<th>Дата</th>", html=True)
        self.assertContains(response, "<th>Общее количество</th>", html=True)
        self.assertNotContains(response, "<th>Статус</th>", html=True)
        self.assertContains(response, "table-service-housing")

        export_response = self.client.get(reverse("export_table", args=[self.organ.pk, "service-housing", "xlsx"]))
        workbook = self.response_workbook(export_response)
        sheet = workbook.active
        self.assertEqual(sheet["A1"].value, "Дата")
        self.assertEqual(sheet["D1"].value, "Готово к заселению")
        self.assertEqual(sheet.freeze_panes, "A2")

    def test_business_count_validation_rejects_illogical_values(self):
        invalid_vehicle = VehicleInventory(
            territorial_organ=self.organ,
            state_date="2026-06-27",
            required_count=5,
            available_count=8,
            broken_count=1,
            writeoff_count=0,
        )
        with self.assertRaises(ValidationError):
            invalid_vehicle.full_clean()

        invalid_housing = ServiceHousing(
            territorial_organ=self.organ,
            state_date="2026-06-27",
            total_count=10,
            used_by_staff=8,
            ready_to_move=4,
        )
        with self.assertRaises(ValidationError):
            invalid_housing.full_clean()

        invalid_alarm = FireAlarm(
            territorial_organ=self.organ,
            state_date="2026-06-27",
            required_objects=4,
            equipped_objects=5,
            broken_objects=0,
        )
        with self.assertRaises(ValidationError):
            invalid_alarm.full_clean()

    def test_citsizi_quantity_must_be_positive(self):
        request_obj = CitsiziEquipment(
            territorial_organ=self.organ,
            request_number="C-0",
            request_date="2026-06-27",
            equipment_type="communication",
            quantity=0,
        )
        with self.assertRaises(ValidationError):
            request_obj.full_clean()

    def test_uoto_building_repair_nested_request_history_filters_and_export(self):
        included = BuildingRepairRequest.objects.create(territorial_organ=self.organ, request_number="B-1", request_date="2026-06-20", status="in_work", comment="Roof")
        excluded = BuildingRepairRequest.objects.create(territorial_organ=self.organ, request_number="B-2", request_date="2026-06-20", status="done", comment="Roof")
        self.create_status_history_entry(included)
        uoto_department = Department.objects.create(name="UOTO", slug="uoto", order_number=2)
        self.user.profile.allowed_departments.add(uoto_department)
        self.client.login(username="operator", password="pass12345")

        panel = self.client.get(reverse("department_tables", args=[self.organ.pk, "uoto"]))
        self.assertContains(panel, "Текущий ремонт зданий, помещений, сооружений")

        response = self.client.get(
            reverse("table_data", args=[self.organ.pk, "building-repair"]),
            {"status": "in_work", "date_from": "2026-06-01", "date_to": "2026-06-30", "q": "B-1"},
        )

        self.assertContains(response, "nested-table-tabs")
        self.assertContains(response, "Заявка")
        self.assertContains(response, "<th>Номер</th>", html=True)
        self.assertContains(response, "<th>Дата</th>", html=True)
        self.assertContains(response, "<th>Исполнение заявки</th>", html=True)
        self.assertContains(response, included.request_number)
        self.assertContains(response, included.comment)
        self.assertNotContains(response, excluded.request_number)
        self.assertContains(response, "bi-clock-history")

        update_response = self.client.post(
            reverse("record_update", args=[self.organ.pk, "building-repair", included.pk]),
            {
                "request_number": "B-1",
                "request_date": "2026-06-20",
                "status": "done",
                "completed_at": "2026-06-29",
                "comment": "Roof",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(update_response.status_code, 200)
        history = self.status_history(included).get(old_status="in_work", new_status="done")
        self.assertEqual(history.completed_at.isoformat(), "2026-06-29")

        modal = self.client.get(reverse("building_repair_status_history", args=[self.organ.pk, included.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(modal, "История изменений статуса заявки B-1")

        export_response = self.client.get(reverse("export_table", args=[self.organ.pk, "building-repair", "xlsx"]), {"status": "done", "q": "B-1"})
        workbook = self.response_workbook(export_response)
        sheet = workbook.active
        self.assertEqual(sheet["A1"].value, "Номер")
        self.assertEqual(sheet["C1"].value, "Исполнение заявки")
        self.assertEqual(sheet["D1"].value, "Описание")
        self.assertEqual(sheet["D2"].value, "Roof")
        self.assertEqual(sheet.freeze_panes, "A2")

    def test_table_shows_only_business_fields_and_status(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            updated_by=self.user,
            request_number="16/TMC",
            request_date="2026-06-27",
            status="in_work",
        )
        TmcRequestItem.objects.create(request=request_obj, name="Cartridge", quantity=2, unit="pcs")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))

        self.assertContains(response, "Сведения о потребности ТМЦ")
        self.assertContains(response, "Заявка")
        self.assertContains(response, "Наименование")
        self.assertContains(response, "Количество")
        self.assertContains(response, "Номер")
        self.assertContains(response, "Дата")
        self.assertContains(response, "Исполнение заявки")
        self.assertContains(response, "Описание")
        self.assertContains(response, "16/TMC")
        self.assertContains(response, "Cartridge")
        self.assertContains(response, "2 pcs")
        self.assertContains(response, request_obj.get_status_display())
        self.assertNotContains(response, "operator")

    def test_deleted_record_disappears_from_table_for_admin(self):
        admin = get_user_model().objects.create_superuser("admin2", password="pass12345")
        UserProfile.objects.create(user=admin, role=UserProfile.Role.ADMIN)
        item = TmcRequest.objects.create(territorial_organ=self.organ, request_number="17/TMC", request_date="2026-06-27", status="in_work")
        TmcRequestItem.objects.create(request=item, name="Deleted item", quantity=1, unit="pcs")
        self.client.login(username="admin2", password="pass12345")

        response = self.client.post(reverse("record_delete", args=[self.organ.pk, "tmc-requests", item.pk]), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertTrue(item.is_deleted)
        self.assertNotContains(response, "Deleted item")

    def test_delete_confirmation_uses_common_modal_style(self):
        item = TmcRequest.objects.create(territorial_organ=self.organ, request_number="18/TMC", request_date="2026-06-27", status="in_work")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("record_delete", args=[self.organ.pk, "tmc-requests", item.pk]), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "delete-confirmation")
        self.assertContains(response, "Подтверждение удаления")
        self.assertContains(response, "bi-exclamation-triangle")

    def test_department_tabs_are_separate_tables(self):
        self.assertEqual(TABLES["tmc"][0]["title"], "Заявка")
        self.assertEqual(TABLES["antiterror"][0]["title"], "Заявка (акт обследования)")
        self.assertEqual([item["key"] for item in TABLES["tmc"]], ["tmc-requests"])
        self.assertEqual([item["key"] for item in TABLES["transport"]], ["vehicle-repair", "vehicle-fuel"])
        self.assertIn("vehicle-inventory", TABLE_BY_KEY)
        self.assertEqual([item["key"] for item in TABLES["fire"]], ["fire-extinguishers", "fire-alarm", "security-alarm", "fire-requests"])
        self.assertEqual([item["key"] for item in TABLES["uoto"]], ["service-housing", "building-repair"])
