from .tests_base import *


class PhotoAssetTests(RequestAppTestCase):

    def assert_audit_detail_has_photo_thumbnail(self, log, photo):
        response = self.client.get(
            reverse("audit_detail", args=[log.pk]),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "request-photo-thumbnails")
        self.assertContains(response, "data-lightbox-photo")
        self.assertContains(
            response,
            reverse("photo_thumbnail", args=[self.organ.pk, photo.pk, "small"]),
        )
        self.assertContains(
            response,
            reverse("photo_preview", args=[self.organ.pk, photo.pk]),
        )
        return response

    def test_tmc_request_can_attach_and_show_photos(self):
        photo = self.create_photo("request-photo.png")
        photo.description = "Repair evidence"
        photo.save(update_fields=["description"])
        self.client.login(username="operator", password="pass12345")

        form_response = self.client.get(reverse("record_create", args=[self.organ.pk, "tmc-requests"]), HTTP_HX_REQUEST="true")
        self.assertContains(form_response, "Прикрепить фотографии")
        self.assertContains(form_response, "request-photo.png")

        response = self.client.post(
            reverse("record_create", args=[self.organ.pk, "tmc-requests"]),
            {
                "request_number": "15-Photo/TMC",
                "request_date": "2026-06-27",
                "status": "in_work",
                "comment": "With photo",
                "item_name": ["Desk"],
                "item_quantity": ["1"],
                "item_unit": ["шт."],
                "attached_photos": [str(photo.pk)],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        request_obj = TmcRequest.objects.get(request_number="15-Photo/TMC")
        self.assertTrue(RequestPhotoLink.objects.filter(photo=photo, object_id=request_obj.pk).exists())
        self.assertContains(response, "request-photo-count")
        self.assertContains(response, "Прикрепленные фотографии (1 шт.)")
        self.assertNotContains(response, "<span>1</span>", html=True)

        photos_response = self.client.get(reverse("request_photos", args=[self.organ.pk, "tmc-requests", request_obj.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(photos_response, "Repair evidence")
        self.assertContains(photos_response, "request-photo.png")
        self.assertContains(photos_response, "Открепить")
        self.assertContains(photos_response, "Скачать все")
        self.assertContains(photos_response, "Прикрепить еще")

        download_response = self.client.get(reverse("request_photos_download", args=[self.organ.pk, "tmc-requests", request_obj.pk]))
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(download_response["Content-Type"], "application/zip")
        archive_data = b"".join(download_response.streaming_content)
        with zipfile.ZipFile(BytesIO(archive_data)) as archive:
            self.assertTrue(any(name.endswith(".png") for name in archive.namelist()))
        archive_log = AuditLog.objects.get(event_type=AuditLog.EventType.PHOTO_ARCHIVE_DOWNLOADED)
        self.assertEqual(archive_log.model_name, "TmcRequest")
        self.assertEqual(archive_log.object_id, str(request_obj.pk))
        self.assertEqual(archive_log.territorial_organ, self.organ)
        self.assertEqual(archive_log.new_values["scope"], "request")
        self.assertEqual(
            archive_log.new_values["photo_items"],
            [{"id": photo.pk, "name": "request-photo.png"}],
        )
        self.assertEqual(archive_log.new_values["photo_count"], 1)
        self.assert_audit_detail_has_photo_thumbnail(archive_log, photo)


    def test_table_request_photo_thumbnails_stay_compact(self):
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            updated_by=self.user,
            request_number="15-Compact/TMC",
            request_date="2026-06-27",
            status="in_work",
            comment="Compact thumbnails",
        )
        TmcRequestItem.objects.create(request=request_obj, name="Desk", quantity=1, unit="шт.")
        photos = [self.create_photo(f"compact-{index}.png") for index in range(5)]
        for photo in photos:
            RequestPhotoLink.objects.create(territorial_organ=self.organ, photo=photo, request=request_obj, created_by=self.user)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "request-photo-thumbnails")
        self.assertEqual(content.count("request-photo-thumbnail-hidden"), 2)
        self.assertContains(response, "+2")
        self.assertNotContains(response, "data-request-photo-thumbnails")
        self.assertNotContains(response, "data-request-photo-thumbnail-item")

    def test_request_photos_modal_can_replace_attached_photos(self):
        first = self.create_photo("first-proof.png")
        first.description = "First proof"
        first.save(update_fields=["description"])
        second = self.create_photo("second-proof.png")
        second.description = "Second proof"
        second.save(update_fields=["description"])
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            updated_by=self.user,
            request_number="15-Replace/TMC",
            request_date="2026-06-27",
            status="in_work",
        )
        TmcRequestItem.objects.create(request=request_obj, name="Desk", quantity=1, unit="шт.")
        self.client.login(username="operator", password="pass12345")
        self.client.post(
            reverse("request_photos", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
            {"attached_photos": [str(first.pk)]},
            HTTP_HX_REQUEST="true",
        )
        self.assertTrue(RequestPhotoLink.objects.filter(photo=first, object_id=request_obj.pk).exists())

        response = self.client.post(
            reverse("request_photos", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
            {"attached_photos": [str(second.pk)]},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(RequestPhotoLink.objects.filter(photo=first, object_id=request_obj.pk).exists())
        self.assertTrue(RequestPhotoLink.objects.filter(photo=second, object_id=request_obj.pk).exists())
        self.assertContains(response, "Second proof")
        self.assertContains(response, f'data-request-linked-photo="{second.pk}"')
        self.assertNotContains(response, f'data-request-linked-photo="{first.pk}"')
        self.assertIn("requestPhotosChanged", response["HX-Trigger"])

    def test_request_photo_audit_events_store_ordered_photo_snapshots(self):
        zulu_photo = self.create_photo("zulu-proof.png")
        alpha_photo = self.create_photo("alpha-proof.png")
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            updated_by=self.user,
            request_number="15-AuditPhotos/TMC",
            request_date="2026-06-27",
            status="in_work",
        )
        TmcRequestItem.objects.create(request=request_obj, name="Desk", quantity=1, unit="шт.")
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("request_photos", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
            {"attached_photos": [str(zulu_photo.pk), str(alpha_photo.pk)]},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        attached_event = AuditLog.objects.get(event_type=AuditLog.EventType.PHOTOS_ATTACHED)
        self.assertEqual(
            attached_event.new_values["photo_items"],
            [
                {"id": alpha_photo.pk, "name": "alpha-proof.png"},
                {"id": zulu_photo.pk, "name": "zulu-proof.png"},
            ],
        )
        self.assertNotIn("photo_items", attached_event.old_values)
        attached_detail = self.client.get(
            reverse("audit_detail", args=[attached_event.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(attached_detail, "Прикрепленные фотографии")
        self.assertContains(attached_detail, "request-photo-thumbnails")
        self.assertContains(
            attached_detail,
            reverse("photo_thumbnail", args=[self.organ.pk, alpha_photo.pk, "small"]),
        )
        self.assertContains(
            attached_detail,
            reverse("photo_preview", args=[self.organ.pk, zulu_photo.pk]),
        )
        self.assertNotContains(attached_detail, ">Photos<")

        response = self.client.post(
            reverse("request_photos", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
            {"attached_photos": []},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        detached_event = AuditLog.objects.get(event_type=AuditLog.EventType.PHOTOS_DETACHED)
        self.assertEqual(
            detached_event.old_values["photo_items"],
            [
                {"id": alpha_photo.pk, "name": "alpha-proof.png"},
                {"id": zulu_photo.pk, "name": "zulu-proof.png"},
            ],
        )
        self.assertNotIn("photo_items", detached_event.new_values)
        detached_detail = self.client.get(
            reverse("audit_detail", args=[detached_event.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(detached_detail, "Открепленные фотографии")
        self.assertContains(
            detached_detail,
            reverse("photo_thumbnail", args=[self.organ.pk, alpha_photo.pk, "small"]),
        )

    def test_legacy_request_photo_audit_event_reuses_unique_existing_thumbnail(self):
        photo = self.create_photo("legacy-audit-proof.png")
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            updated_by=self.user,
            request_number="15-LegacyAuditPhoto/TMC",
            request_date="2026-06-27",
            status="in_work",
        )
        log = AuditLog.objects.create(
            user=self.user,
            action=AuditLog.Action.UPDATE,
            event_type=AuditLog.EventType.PHOTOS_ATTACHED,
            model_name="TmcRequest",
            object_id=str(request_obj.pk),
            object_repr=str(request_obj),
            old_values={"photos": ""},
            new_values={
                "audit_event": AuditLog.EventType.PHOTOS_ATTACHED,
                "photos": photo.original_filename,
            },
            territorial_organ=self.organ,
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("audit_detail", args=[log.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, "Прикрепленные фотографии")
        self.assertContains(
            response,
            reverse("photo_thumbnail", args=[self.organ.pk, photo.pk, "small"]),
        )
        self.assertNotContains(response, ">Photos<")

    def test_request_photos_ignore_photos_from_other_organ(self):
        other_organ = TerritorialOrgan.objects.create(name="Other photo organ", order_number=2)
        request_obj = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            updated_by=self.user,
            request_number="15-CrossPhoto/TMC",
            request_date="2026-06-27",
            status="in_work",
        )
        TmcRequestItem.objects.create(request=request_obj, name="Desk", quantity=1, unit="шт.")
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        foreign_photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=other_organ,
            image=SimpleUploadedFile("foreign-request-photo.png", buffer.getvalue(), content_type="image/png"),
            description="Foreign evidence",
            created_by=self.user,
            updated_by=self.user,
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("request_photos", args=[self.organ.pk, "tmc-requests", request_obj.pk]),
            {"attached_photos": [str(foreign_photo.pk)]},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(RequestPhotoLink.objects.filter(photo=foreign_photo, object_id=request_obj.pk).exists())
        self.assertNotContains(response, "Foreign evidence")
        self.assertContains(response, "К заявке фотографии не прикреплены")

    def test_request_lightbox_groups_are_isolated_per_request(self):
        first = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            request_number="15-Lightbox-1/TMC",
            request_date="2026-06-27",
            status="in_work",
        )
        second = TmcRequest.objects.create(
            territorial_organ=self.organ,
            created_by=self.user,
            request_number="15-Lightbox-2/TMC",
            request_date="2026-06-28",
            status="in_work",
        )
        TmcRequestItem.objects.create(request=first, name="Desk", quantity=1, unit="шт.")
        TmcRequestItem.objects.create(request=second, name="Chair", quantity=1, unit="шт.")
        first_photo = self.create_photo("first-lightbox.png")
        second_photo = self.create_photo("second-lightbox.png")
        content_type = ContentType.objects.get_for_model(TmcRequest, for_concrete_model=False)
        RequestPhotoLink.objects.create(
            territorial_organ=self.organ,
            photo=first_photo,
            content_type=content_type,
            object_id=first.pk,
            created_by=self.user,
        )
        RequestPhotoLink.objects.create(
            territorial_organ=self.organ,
            photo=second_photo,
            content_type=content_type,
            object_id=second.pk,
            created_by=self.user,
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("table_data", args=[self.organ.pk, "tmc-requests"]))
        content = response.content.decode()
        first_group = f'request-{self.organ.pk}-tmc-requests-{first.pk}'
        second_group = f'request-{self.organ.pk}-tmc-requests-{second.pk}'

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-lightbox-group="{first_group}"')
        self.assertContains(response, f'data-lightbox-group="{second_group}"')
        self.assertContains(response, "first-lightbox.png")
        self.assertContains(response, "second-lightbox.png")
        self.assertGreaterEqual(content.count(f'data-lightbox-group="{first_group}"'), 2)
        self.assertGreaterEqual(content.count(f'data-lightbox-group="{second_group}"'), 2)

    def test_request_photo_picker_filters_paginates_without_moving_selected_between_folders(self):
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Evidence")
        selected = self.create_photo("selected-proof.png")
        selected.description = "Already selected"
        selected.save(update_fields=["description"])
        folder_photo = self.create_photo("folder-proof.png")
        folder_photo.folder = folder
        folder_photo.description = "Folder proof"
        folder_photo.save(update_fields=["folder", "description"])
        root_photo = self.create_photo("root-proof.png")
        root_photo.description = "Root proof"
        root_photo.save(update_fields=["description"])
        for index in range(14):
            photo = self.create_photo(f"page-photo-{index}.png")
            photo.description = f"Page photo {index}"
            photo.save(update_fields=["description"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("request_photo_picker", args=[self.organ.pk]), {"attached_photos": [selected.pk], "photo_q": "folder"})
        self.assertContains(response, "input changed delay:1200ms from:#request-photo-search-input")
        self.assertContains(response, 'hx-target="#request-photo-results"')
        self.assertContains(response, 'hx-sync="this:replace"')
        self.assertNotContains(response, "selected-proof.png")
        self.assertContains(response, "folder-proof.png")
        self.assertNotContains(response, "root-proof.png")

        response = self.client.get(
            reverse("request_photo_picker", args=[self.organ.pk]),
            {"photo_folder": folder.pk, "attached_photos": [selected.pk]},
        )
        self.assertContains(response, "folder-proof.png")
        self.assertNotContains(response, "selected-proof.png")
        self.assertNotContains(response, "root-proof.png")

        response = self.client.get(reverse("request_photo_picker", args=[self.organ.pk]), {"photo_page": 2})
        self.assertContains(response, "request-photo-grid")
        self.assertContains(response, "photo_page=1")
        self.assertContains(response, 'class="pagination-jump"')
        self.assertContains(response, 'name="photo_page"')

    def test_photo_upload_and_soft_delete(self):
        self.client.login(username="operator", password="pass12345")
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        image = SimpleUploadedFile("photo.png", buffer.getvalue(), content_type="image/png")
        response = self.client.post(reverse("photo_create", args=[self.organ.pk]), {"image": image, "description": "Facade"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        photo = TerritorialOrganPhoto.objects.get()
        response = self.client.post(reverse("photo_delete", args=[self.organ.pk, photo.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        photo.refresh_from_db()
        self.assertTrue(photo.is_deleted)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.DELETE, model_name="TerritorialOrganPhoto").exists())

    def test_photo_create_audit_detail_uses_existing_thumbnail_and_lightbox(self):
        self.client.login(username="operator", password="pass12345")
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        image = SimpleUploadedFile("audit-created-photo.png", buffer.getvalue(), content_type="image/png")

        response = self.client.post(
            reverse("photo_create", args=[self.organ.pk]),
            {"image": image, "description": "Created for audit"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        photo = TerritorialOrganPhoto.objects.get(original_filename="audit-created-photo.png")
        log = AuditLog.objects.get(
            action=AuditLog.Action.CREATE,
            model_name="TerritorialOrganPhoto",
            object_id=str(photo.pk),
        )
        self.assert_audit_detail_has_photo_thumbnail(log, photo)

    def test_photo_description_and_folder_change_audit_details_use_thumbnail(self):
        target_folder = TerritorialOrganPhotoFolder.objects.create(
            territorial_organ=self.organ,
            name="Target",
            created_by=self.user,
            updated_by=self.user,
            created_department=self.department,
        )
        photo = self.create_photo("audit-updated-photo.png")
        photo.created_department = self.department
        photo.description = "Before update"
        photo.save(update_fields=["created_department", "description"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("photo_update", args=[self.organ.pk, photo.pk]),
            {"folder": "", "description": "After update"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        description_log = AuditLog.objects.get(
            action=AuditLog.Action.UPDATE,
            model_name="TerritorialOrganPhoto",
            object_id=str(photo.pk),
        )
        self.assert_audit_detail_has_photo_thumbnail(description_log, photo)

        response = self.client.post(
            reverse("photo_update", args=[self.organ.pk, photo.pk]),
            {"folder": target_folder.pk, "description": "After update"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        move_log = (
            AuditLog.objects.filter(
                action=AuditLog.Action.UPDATE,
                model_name="TerritorialOrganPhoto",
                object_id=str(photo.pk),
            )
            .order_by("-pk")
            .first()
        )
        self.assertEqual(move_log.new_values["folder"], str(target_folder.pk))
        self.assert_audit_detail_has_photo_thumbnail(move_log, photo)

    def test_photo_soft_delete_audit_detail_keeps_thumbnail_available(self):
        photo = self.create_photo("audit-deleted-photo.png")
        photo.created_department = self.department
        photo.save(update_fields=["created_department"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("photo_delete", args=[self.organ.pk, photo.pk]),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        photo.refresh_from_db()
        self.assertTrue(photo.is_deleted)
        log = AuditLog.objects.get(
            action=AuditLog.Action.DELETE,
            model_name="TerritorialOrganPhoto",
            object_id=str(photo.pk),
        )
        self.assert_audit_detail_has_photo_thumbnail(log, photo)

    def test_legacy_photo_audit_log_resolves_thumbnail_from_object_id(self):
        photo = self.create_photo("legacy-object-id-photo.png")
        photo.created_department = self.department
        photo.save(update_fields=["created_department"])
        log = AuditLog.objects.create(
            user=self.user,
            action=AuditLog.Action.UPDATE,
            model_name="TerritorialOrganPhoto",
            object_id=str(photo.pk),
            object_repr=str(photo),
            old_values={"description": "Old description", "created_department": str(self.department.pk)},
            new_values={"description": "New description", "created_department": str(self.department.pk)},
            territorial_organ=self.organ,
        )
        self.client.login(username="operator", password="pass12345")

        self.assert_audit_detail_has_photo_thumbnail(log, photo)

    def test_photo_form_uses_custom_single_file_picker(self):
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photo_create", args=[self.organ.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, "data-single-file-picker")
        self.assertContains(response, "Выбрать изображение")
        self.assertContains(response, 'type="file"')

    def test_photo_edit_form_shows_preview_and_custom_folder_select(self):
        parent = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Parent")
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=parent, name="Folder")
        photo = self.create_photo("edit-preview.png")
        photo.folder = folder
        photo.description = "Preview description"
        photo.save(update_fields=["folder", "description"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photo_update", args=[self.organ.pk, photo.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, "photo-edit-preview")
        self.assertContains(response, "edit-preview.png")
        self.assertContains(response, "Preview description")
        self.assertContains(response, "photo-edit-replace")
        self.assertContains(response, "data-single-file-preview")
        self.assertContains(response, "Выбрать изображение")
        self.assertContains(response, '<i class="bi bi-image" aria-hidden="true"></i> Выбрать изображение', html=True)
        self.assertContains(response, "Parent / Folder")
        self.assertContains(response, "data-folder-picker-box")
        self.assertContains(response, "data-folder-picker-hidden")
        self.assertContains(response, f'value="{folder.pk}"')
        self.assertContains(response, "custom-select-native", count=0)

    def test_photo_replace_updates_upload_date(self):
        photo = self.create_photo("old-photo.png")
        old_created_at = timezone.now() - timedelta(days=3)
        TerritorialOrganPhoto.objects.filter(pk=photo.pk).update(created_at=old_created_at)
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "blue").save(buffer, format="PNG")
        image = SimpleUploadedFile("new-photo.png", buffer.getvalue(), content_type="image/png")
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("photo_update", args=[self.organ.pk, photo.pk]),
            {"image": image, "description": "Updated photo"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        photo.refresh_from_db()
        self.assertGreater(photo.created_at, old_created_at)
        self.assertEqual(photo.original_filename, "new-photo.png")

    def test_photo_assets_can_be_managed_only_by_author_department(self):
        User = get_user_model()
        fire_department = Department.objects.create(name="Fire", slug="fire", order_number=2)
        transport_department = Department.objects.create(name="Transport", slug="transport", order_number=3)
        fire_user = User.objects.create_user("fire-photo", password="pass12345")
        transport_user = User.objects.create_user("transport-photo", password="pass12345")
        fire_profile = UserProfile.objects.create(user=fire_user, role=UserProfile.Role.OPERATOR)
        transport_profile = UserProfile.objects.create(user=transport_user, role=UserProfile.Role.OPERATOR)
        fire_profile.allowed_departments.set([fire_department])
        fire_profile.allowed_organs.set([self.organ])
        fire_profile.writable_departments.set([fire_department])
        fire_profile.writable_organs.set([self.organ])
        transport_profile.allowed_departments.set([transport_department])
        transport_profile.allowed_organs.set([self.organ])
        transport_profile.writable_departments.set([transport_department])
        transport_profile.writable_organs.set([self.organ])
        folder = TerritorialOrganPhotoFolder.objects.create(
            territorial_organ=self.organ,
            name="Fire folder",
            created_by=fire_user,
            updated_by=fire_user,
            created_department=fire_department,
        )
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        image = SimpleUploadedFile("fire-photo.png", buffer.getvalue(), content_type="image/png")
        photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=self.organ,
            folder=folder,
            image=image,
            created_by=fire_user,
            updated_by=fire_user,
            created_department=fire_department,
        )

        self.client.login(username="transport-photo", password="pass12345")

        response = self.client.get(reverse("photo_update", args=[self.organ.pk, photo.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse("photo_delete", args=[self.organ.pk, photo.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 404)
        response = self.client.get(reverse("photo_folder_update", args=[self.organ.pk, folder.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse("photo_folder_delete", args=[self.organ.pk, folder.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 404)

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"folder": folder.pk})
        self.assertContains(response, "fire-photo.png")
        self.assertNotContains(response, reverse("photo_update", args=[self.organ.pk, photo.pk]))
        self.assertNotContains(response, reverse("photo_folder_update", args=[self.organ.pk, folder.pk]))

        self.client.logout()
        self.client.login(username="fire-photo", password="pass12345")
        response = self.client.get(reverse("photo_update", args=[self.organ.pk, photo.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("photo_folder_update", args=[self.organ.pk, folder.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)

    def test_photo_upload_stores_author_department(self):
        fire_department = Department.objects.create(name="Fire", slug="fire", order_number=2)
        self.user.profile.allowed_departments.set([fire_department])
        self.user.profile.writable_departments.set([fire_department])
        self.client.login(username="operator", password="pass12345")
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        image = SimpleUploadedFile("department-photo.png", buffer.getvalue(), content_type="image/png")

        response = self.client.post(reverse("photo_create", args=[self.organ.pk]), {"image": image, "description": "Department photo"}, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        photo = TerritorialOrganPhoto.objects.get(original_filename="department-photo.png")
        self.assertEqual(photo.created_by, self.user)
        self.assertEqual(photo.created_department, fire_department)

    def test_photo_upload_and_nested_folder_creation_are_denied_in_foreign_folder(self):
        User = get_user_model()
        fire_department = Department.objects.create(name="Fire", slug="fire", order_number=2)
        transport_department = Department.objects.create(name="Transport", slug="transport", order_number=3)
        fire_user = User.objects.create_user("fire-folder-owner", password="pass12345")
        fire_profile = UserProfile.objects.create(user=fire_user, role=UserProfile.Role.OPERATOR)
        self.user.profile.allowed_departments.set([transport_department])
        self.user.profile.writable_departments.set([transport_department])
        fire_profile.allowed_departments.set([fire_department])
        fire_profile.allowed_organs.set([self.organ])
        fire_profile.writable_departments.set([fire_department])
        fire_profile.writable_organs.set([self.organ])
        foreign_folder = TerritorialOrganPhotoFolder.objects.create(
            territorial_organ=self.organ,
            name="Foreign folder",
            created_by=fire_user,
            updated_by=fire_user,
            created_department=fire_department,
        )
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photo_bulk_upload", args=[self.organ.pk]), {"folder": foreign_folder.pk}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 404)

        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        image = SimpleUploadedFile("foreign-folder-upload.png", buffer.getvalue(), content_type="image/png")
        response = self.client.post(
            reverse("photo_bulk_upload", args=[self.organ.pk]),
            {"images": [image], "folder": foreign_folder.pk},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(TerritorialOrganPhoto.objects.filter(original_filename="foreign-folder-upload.png").exists())

        response = self.client.post(
            reverse("photo_folder_create", args=[self.organ.pk]),
            {"name": "Nested denied", "parent": foreign_folder.pk},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(TerritorialOrganPhotoFolder.objects.filter(name="Nested denied").exists())

    def test_photo_cannot_be_moved_to_foreign_folder(self):
        User = get_user_model()
        fire_department = Department.objects.create(name="Fire", slug="fire", order_number=2)
        transport_department = Department.objects.create(name="Transport", slug="transport", order_number=3)
        fire_user = User.objects.create_user("fire-move-owner", password="pass12345")
        fire_profile = UserProfile.objects.create(user=fire_user, role=UserProfile.Role.OPERATOR)
        fire_profile.allowed_departments.set([fire_department])
        fire_profile.allowed_organs.set([self.organ])
        fire_profile.writable_departments.set([fire_department])
        fire_profile.writable_organs.set([self.organ])
        self.user.profile.allowed_departments.set([transport_department])
        self.user.profile.writable_departments.set([transport_department])
        foreign_folder = TerritorialOrganPhotoFolder.objects.create(
            territorial_organ=self.organ,
            name="Foreign move target",
            created_by=fire_user,
            updated_by=fire_user,
            created_department=fire_department,
        )
        photo = self.create_photo("own-photo.png")
        photo.created_department = transport_department
        photo.save(update_fields=["created_department"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("photo_update", args=[self.organ.pk, photo.pk]),
            {"folder": foreign_folder.pk, "description": "Move attempt"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        photo.refresh_from_db()
        self.assertIsNone(photo.folder)
        self.assertNotEqual(photo.description, "Move attempt")
        self.assertContains(response, "Выберите корректный вариант")

    def test_photo_download_single_and_zip(self):
        photo = self.create_photo()
        self.profile.role = UserProfile.Role.ADMIN
        self.profile.save(update_fields=["role"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photo_download", args=[self.organ.pk, photo.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        download_log = AuditLog.objects.get(event_type=AuditLog.EventType.PHOTO_DOWNLOADED)
        self.assertEqual(download_log.model_name, "TerritorialOrganPhoto")
        self.assertEqual(download_log.object_id, str(photo.pk))
        self.assertEqual(download_log.territorial_organ, self.organ)
        self.assertEqual(download_log.new_values["scope"], "photo")
        self.assertEqual(
            download_log.new_values["photo_items"],
            [{"id": photo.pk, "name": "photo.png"}],
        )
        self.assertEqual(download_log.new_values["photo_count"], 1)
        download_detail = self.assert_audit_detail_has_photo_thumbnail(download_log, photo)
        self.assertContains(download_detail, "Скачанная фотография")

        response = self.client.get(reverse("photos_download_all", args=[self.organ.pk]), {"download_token": "photostest"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("download-ready-photostest", response.cookies)
        archive_data = b"".join(response.streaming_content)
        with zipfile.ZipFile(BytesIO(archive_data)) as archive:
            self.assertTrue(any(name.endswith(".png") for name in archive.namelist()))
        log = AuditLog.objects.get(event_type=AuditLog.EventType.PHOTO_ARCHIVE_DOWNLOADED)
        self.assertEqual(log.territorial_organ, self.organ)
        self.assertEqual(log.new_values["scope"], "organ")
        self.assertEqual(
            log.new_values["photo_items"],
            [{"id": photo.pk, "name": "photo.png"}],
        )
        self.assertEqual(log.new_values["photo_count"], 1)
        detail_response = self.assert_audit_detail_has_photo_thumbnail(log, photo)
        self.assertContains(detail_response, "Фотографии в архиве")

    def test_photo_archive_audit_snapshot_is_limited_and_detail_shows_extra_count(self):
        photos = [self.create_photo(f"audit-limit-{index:02d}.png") for index in range(27)]
        self.profile.role = UserProfile.Role.ADMIN
        self.profile.save(update_fields=["role"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos_download_all", args=[self.organ.pk]))

        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        log = AuditLog.objects.get(event_type=AuditLog.EventType.PHOTO_ARCHIVE_DOWNLOADED)
        self.assertEqual(log.new_values["photo_count"], 27)
        self.assertEqual(len(log.new_values["photo_items"]), 24)
        self.assertEqual(
            log.new_values["photo_items"],
            [
                {"id": photo.pk, "name": f"audit-limit-{index:02d}.png"}
                for index, photo in enumerate(photos[:24])
            ],
        )

        detail_response = self.client.get(
            reverse("audit_detail", args=[log.pk]),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "data-lightbox-photo", count=24)
        self.assertContains(detail_response, "request-photo-thumbnail-more")
        self.assertContains(detail_response, "+3")
        self.assertNotContains(
            detail_response,
            reverse("photo_thumbnail", args=[self.organ.pk, photos[24].pk, "small"]),
        )

    def test_photo_preview_and_thumbnail_are_permission_gated(self):
        photo = self.create_photo()
        other_organ = TerritorialOrgan.objects.create(name="Other territorial organ", order_number=2)
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        foreign_photo = TerritorialOrganPhoto.objects.create(
            territorial_organ=other_organ,
            image=SimpleUploadedFile("foreign.png", buffer.getvalue(), content_type="image/png"),
            created_by=self.user,
            updated_by=self.user,
        )
        self.client.login(username="operator", password="pass12345")

        preview_response = self.client.get(reverse("photo_preview", args=[self.organ.pk, photo.pk]))
        self.assertEqual(preview_response.status_code, 200)
        self.assertNotIn("attachment", preview_response.get("Content-Disposition", ""))

        # No dedicated thumbnail_small/medium was generated by create_photo(),
        # so these must fall back to serving the original image rather than 404.
        small_response = self.client.get(reverse("photo_thumbnail", args=[self.organ.pk, photo.pk, "small"]))
        self.assertEqual(small_response.status_code, 200)
        medium_response = self.client.get(reverse("photo_thumbnail", args=[self.organ.pk, photo.pk, "medium"]))
        self.assertEqual(medium_response.status_code, 200)

        self.assertFalse(AuditLog.objects.filter(event_type=AuditLog.EventType.PHOTO_DOWNLOADED).exists())

        self.assertEqual(self.client.get(reverse("photo_thumbnail", args=[self.organ.pk, photo.pk, "huge"])).status_code, 404)

        # An organ the operator isn't assigned to must 404, same as photo_download.
        self.assertEqual(self.client.get(reverse("photo_preview", args=[other_organ.pk, foreign_photo.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("photo_thumbnail", args=[other_organ.pk, foreign_photo.pk, "small"])).status_code, 404)

    def test_soft_deleted_photo_preview_is_available_to_asset_manager_and_admin(self):
        photo = self.create_photo()
        photo.is_deleted = True
        photo.save(update_fields=["is_deleted"])

        # The operator who can manage the asset needs its preview in the trash.
        self.client.login(username="operator", password="pass12345")
        self.assertEqual(self.client.get(reverse("photo_preview", args=[self.organ.pk, photo.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("photo_thumbnail", args=[self.organ.pk, photo.pk, "small"])).status_code, 200)
        self.client.logout()

        User = get_user_model()
        admin = User.objects.create_superuser("photo-admin", password="pass12345")
        self.client.login(username="photo-admin", password="pass12345")
        self.assertEqual(self.client.get(reverse("photo_preview", args=[self.organ.pk, photo.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("photo_thumbnail", args=[self.organ.pk, photo.pk, "small"])).status_code, 200)

    def test_photo_folder_download_includes_nested_photos(self):
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Folder")
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=folder, name="Child")
        parent_photo = self.create_photo("folder-parent-download.png")
        parent_photo.folder = folder
        parent_photo.save(update_fields=["folder"])
        child_photo = self.create_photo("folder-child-download.png")
        child_photo.folder = child
        child_photo.save(update_fields=["folder"])
        outside_photo = self.create_photo("folder-outside-marker.png")
        outside_photo.save()
        self.profile.role = UserProfile.Role.ADMIN
        self.profile.save(update_fields=["role"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photo_folder_download", args=[self.organ.pk, folder.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        archive_data = b"".join(response.streaming_content)
        with zipfile.ZipFile(BytesIO(archive_data)) as archive:
            names = archive.namelist()
            self.assertTrue(any(name.endswith("folder-parent-download.png") for name in names))
            self.assertTrue(any(name.startswith("Child/") and name.endswith("folder-child-download.png") for name in names))
            self.assertFalse(any("outside-marker" in name for name in names))
        log = AuditLog.objects.get(event_type=AuditLog.EventType.PHOTO_ARCHIVE_DOWNLOADED)
        self.assertEqual(log.new_values["scope"], "folder")
        self.assertEqual(
            log.new_values["photo_items"],
            [
                {"id": child_photo.pk, "name": "folder-child-download.png"},
                {"id": parent_photo.pk, "name": "folder-parent-download.png"},
            ],
        )
        self.assertEqual(log.new_values["photo_count"], 2)
        detail_response = self.assert_audit_detail_has_photo_thumbnail(log, parent_photo)
        self.assertContains(
            detail_response,
            reverse("photo_thumbnail", args=[self.organ.pk, child_photo.pk, "small"]),
        )
        self.assertContains(
            detail_response,
            reverse("photo_preview", args=[self.organ.pk, child_photo.pk]),
        )
        self.assertNotContains(
            detail_response,
            reverse("photo_thumbnail", args=[self.organ.pk, outside_photo.pk, "small"]),
        )

    def test_photos_direct_visit_renders_full_page_htmx_returns_fragment(self):
        # /organs/<id>/photos/ is a real, shareable URL - a direct/bookmarked
        # visit (no HX-Request header) must render a full page (base.html's
        # header/nav/static assets), not the bare partials/photos.html
        # fragment htmx swaps into #workspace.
        self.create_photo("shared-link.png")
        self.client.login(username="operator", password="pass12345")

        direct_response = self.client.get(reverse("photos", args=[self.organ.pk]))
        self.assertEqual(direct_response.status_code, 200)
        self.assertContains(direct_response, "<!doctype html>")
        self.assertContains(direct_response, "shared-link.png")
        self.assertContains(direct_response, 'id="workspace"')

        htmx_response = self.client.get(reverse("photos", args=[self.organ.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(htmx_response.status_code, 200)
        self.assertNotContains(htmx_response, "<!doctype html>")
        self.assertContains(htmx_response, "shared-link.png")

    def test_photos_direct_visit_without_access_shows_full_page_message(self):
        other_organ = TerritorialOrgan.objects.create(name="Foreign territorial organ for deep link", order_number=2)
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos", args=[other_organ.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<!doctype html>")
        self.assertContains(response, "Нет доступа к этому территориальному органу")

    def test_photos_are_paginated_and_filterable(self):
        for index in range(25):
            photo = self.create_photo(f"photo-{index}.png")
            photo.description = f"Photo {index}"
            photo.save(update_fields=["description"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos", args=[self.organ.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["photo_page"].object_list), 24)
        self.assertContains(response, 'data-download-preparing="Подготовка архива..."')
        self.assertContains(response, "photo-page-number")
        self.assertContains(response, 'class="pagination-jump"')
        self.assertContains(response, 'data-pagination-scroll="self"')
        self.assertContains(response, 'name="page"')
        self.assertContains(response, "page=2")
        self.assertNotContains(response, "Описание не добавлено")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"q": "photo-24", "sort": "oldest"})
        self.assertContains(response, "photo-24")

    def test_photos_search_uses_filename_not_storage_path(self):
        photo = self.create_photo("target-name.png")
        photo.description = "Filename check"
        photo.save(update_fields=["description"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"q": "target-name"})
        self.assertContains(response, "Filename check")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"q": "territorial_organs"})
        self.assertNotContains(response, "Filename check")

    def test_photo_bulk_upload_creates_folder_and_descriptions(self):
        self.client.login(username="operator", password="pass12345")
        files = []
        for name in ["bulk-1.png", "bulk-2.png"]:
            buffer = BytesIO()
            Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
            files.append(SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png"))

        response = self.client.post(
            reverse("photo_bulk_upload", args=[self.organ.pk]),
            {"images": files, "descriptions": ["First photo", "Second photo"], "new_folder": "Check"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        folder = TerritorialOrganPhotoFolder.objects.get(name="Check")
        uploaded_photos = list(TerritorialOrganPhoto.objects.filter(folder=folder).order_by("original_filename", "pk"))
        self.assertEqual(len(uploaded_photos), 2)
        self.assertTrue(TerritorialOrganPhoto.objects.filter(description="First photo").exists())
        folder_log = AuditLog.objects.get(
            action=AuditLog.Action.CREATE,
            model_name="TerritorialOrganPhotoFolder",
            object_id=str(folder.pk),
        )
        self.assertEqual(
            folder_log.new_values["photo_items"],
            [
                {"id": uploaded_photos[0].pk, "name": "bulk-1.png"},
                {"id": uploaded_photos[1].pk, "name": "bulk-2.png"},
            ],
        )
        self.assertEqual(folder_log.new_values["photo_count"], 2)
        detail_response = self.assert_audit_detail_has_photo_thumbnail(folder_log, uploaded_photos[0])
        self.assertContains(
            detail_response,
            reverse("photo_thumbnail", args=[self.organ.pk, uploaded_photos[1].pk, "small"]),
        )

        extra_buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(extra_buffer, format="PNG")
        extra_image = SimpleUploadedFile("bulk-3.png", extra_buffer.getvalue(), content_type="image/png")
        second_response = self.client.post(
            reverse("photo_bulk_upload", args=[self.organ.pk]),
            {"images": [extra_image], "new_folder": "Check"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            AuditLog.objects.filter(
                action=AuditLog.Action.CREATE,
                model_name="TerritorialOrganPhotoFolder",
                object_id=str(folder.pk),
            ).count(),
            1,
        )

    def test_photo_bulk_upload_form_has_progress_state(self):
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photo_bulk_upload", args=[self.organ.pk]), HTTP_HX_REQUEST="true")

        self.assertContains(response, "data-bulk-upload-progress")
        self.assertContains(response, "data-bulk-refresh-url")
        self.assertContains(response, "data-bulk-upload-submit")

    def test_photo_bulk_upload_batch_returns_json(self):
        self.client.login(username="operator", password="pass12345")
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        image = SimpleUploadedFile("batch.png", buffer.getvalue(), content_type="image/png")

        response = self.client.post(
            reverse("photo_bulk_upload", args=[self.organ.pk]),
            {"images": [image], "descriptions": ["Batch photo"]},
            HTTP_X_BULK_PHOTO_BATCH="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json()["created"], 1)
        self.assertEqual(response.json()["failed"], 0)
        self.assertTrue(TerritorialOrganPhoto.objects.filter(description="Batch photo").exists())

    def test_photo_bulk_upload_accepts_more_than_300_files(self):
        self.client.login(username="operator", password="pass12345")
        files = []
        for index in range(301):
            buffer = BytesIO()
            Image.new("RGB", (1, 1), "white").save(buffer, format="PNG")
            files.append(SimpleUploadedFile(f"many-{index}.png", buffer.getvalue(), content_type="image/png"))

        response = self.client.post(
            reverse("photo_bulk_upload", args=[self.organ.pk]),
            {"images": files},
            HTTP_X_BULK_PHOTO_BATCH="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 301)
        self.assertEqual(response.json()["failed"], 0)
        self.assertEqual(TerritorialOrganPhoto.objects.count(), 301)

    def test_photo_bulk_upload_uses_current_folder(self):
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Current")
        self.client.login(username="operator", password="pass12345")
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        image = SimpleUploadedFile("current-folder.png", buffer.getvalue(), content_type="image/png")

        response = self.client.post(
            reverse("photo_bulk_upload", args=[self.organ.pk]),
            {"images": [image], "descriptions": ["In current folder"], "folder": folder.pk},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(TerritorialOrganPhoto.objects.filter(folder=folder, description="In current folder").exists())

    def test_photo_folder_can_be_created_inside_folder(self):
        parent = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Parent")
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(
            reverse("photo_folder_create", args=[self.organ.pk]),
            {"name": "Nested", "parent": parent.pk},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        nested = TerritorialOrganPhotoFolder.objects.get(name="Nested")
        self.assertEqual(nested.parent, parent)
        self.assertContains(response, "Nested")
        self.assertEqual(response.context["selected_folder"], parent)

    def test_photo_folder_can_be_renamed(self):
        parent = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Parent")
        folder = TerritorialOrganPhotoFolder.objects.create(
            territorial_organ=self.organ,
            parent=parent,
            name="Old name",
            created_by=self.user,
            updated_by=self.user,
            created_department=self.department,
        )
        photo = self.create_photo("renamed-folder-photo.png")
        photo.folder = folder
        photo.save(update_fields=["folder"])
        self.client.login(username="operator", password="pass12345")

        form_response = self.client.get(reverse("photo_folder_update", args=[self.organ.pk, folder.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(form_response, "Old name")
        self.assertContains(form_response, "Сохранить")

        response = self.client.post(
            reverse("photo_folder_update", args=[self.organ.pk, folder.pk]),
            {"name": "New name"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        folder.refresh_from_db()
        self.assertEqual(folder.name, "New name")
        self.assertEqual(folder.parent, parent)
        self.assertContains(response, "New name")
        self.assertNotContains(response, "Old name")
        log = AuditLog.objects.get(
            action=AuditLog.Action.UPDATE,
            model_name="TerritorialOrganPhotoFolder",
            object_id=str(folder.pk),
        )
        self.assertEqual(
            log.new_values["photo_items"],
            [{"id": photo.pk, "name": "renamed-folder-photo.png"}],
        )
        self.assertEqual(log.new_values["photo_count"], 1)
        self.assert_audit_detail_has_photo_thumbnail(log, photo)

    def test_photo_folder_can_be_moved_to_another_folder(self):
        parent = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Parent")
        target = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Target")
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=parent, name="Child")
        folder = TerritorialOrganPhotoFolder.objects.create(
            territorial_organ=self.organ,
            parent=parent,
            name="Moved",
            created_by=self.user,
            updated_by=self.user,
            created_department=self.department,
        )
        nested = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=folder, name="Nested")
        direct_photo = self.create_photo("folder-move-direct.png")
        direct_photo.folder = folder
        direct_photo.save(update_fields=["folder"])
        nested_photo = self.create_photo("folder-move-nested.png")
        nested_photo.folder = nested
        nested_photo.save(update_fields=["folder"])
        outside_photo = self.create_photo("folder-move-outside.png")
        self.client.login(username="operator", password="pass12345")

        form_response = self.client.get(reverse("photo_folder_update", args=[self.organ.pk, folder.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(form_response, "Расположение")
        self.assertContains(form_response, "photo-folder-form")
        self.assertContains(form_response, "data-folder-picker-box")
        self.assertContains(form_response, "Target")
        self.assertContains(form_response, f"exclude={folder.pk}")

        picker_response = self.client.get(
            reverse("folder_picker", args=[self.organ.pk]),
            {"picker_folder": parent.pk, "exclude": folder.pk, "field_name": "parent"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(picker_response, "input changed delay:1200ms from:#folder-picker-search-parent")
        self.assertContains(picker_response, 'hx-target="next .folder-picker-results"')
        self.assertContains(picker_response, 'hx-sync="this:replace"')
        self.assertContains(picker_response, "Child")
        self.assertNotContains(picker_response, "Moved")

        response = self.client.post(
            reverse("photo_folder_update", args=[self.organ.pk, folder.pk]),
            {"name": "Moved", "parent": target.pk},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        folder.refresh_from_db()
        nested.refresh_from_db()
        self.assertEqual(folder.parent, target)
        self.assertEqual(nested.parent, folder)
        self.assertEqual(response.context["selected_folder"], target)
        log = AuditLog.objects.get(
            action=AuditLog.Action.UPDATE,
            model_name="TerritorialOrganPhotoFolder",
            object_id=str(folder.pk),
        )
        self.assertEqual(
            log.new_values["photo_items"],
            [
                {"id": direct_photo.pk, "name": "folder-move-direct.png"},
                {"id": nested_photo.pk, "name": "folder-move-nested.png"},
            ],
        )
        self.assertEqual(log.new_values["photo_count"], 2)
        detail_response = self.assert_audit_detail_has_photo_thumbnail(log, nested_photo)
        self.assertNotContains(
            detail_response,
            reverse("photo_thumbnail", args=[self.organ.pk, outside_photo.pk, "small"]),
        )

    def test_photo_folder_delete_soft_deletes_content(self):
        parent = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Parent")
        folder = TerritorialOrganPhotoFolder.objects.create(
            territorial_organ=self.organ,
            parent=parent,
            name="Delete me",
            created_by=self.user,
            updated_by=self.user,
            created_department=self.department,
        )
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=folder, name="Child")
        photo = self.create_photo("folder-photo.png")
        photo.folder = folder
        photo.description = "Folder photo"
        photo.created_department = self.department
        photo.save(update_fields=["folder", "description", "created_department"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.post(reverse("photo_folder_delete", args=[self.organ.pk, folder.pk]), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        folder.refresh_from_db()
        photo.refresh_from_db()
        child.refresh_from_db()
        self.assertTrue(folder.is_deleted)
        self.assertTrue(child.is_deleted)
        self.assertTrue(photo.is_deleted)
        self.assertEqual(photo.folder, folder)
        self.assertEqual(child.parent, folder)
        self.assertNotContains(response, "Folder photo")
        self.assertNotContains(response, "Delete me")
        log = AuditLog.objects.get(
            action=AuditLog.Action.DELETE,
            model_name="TerritorialOrganPhotoFolder",
            object_id=str(folder.pk),
        )
        self.assertEqual(
            log.old_values["photo_items"],
            [{"id": photo.pk, "name": "folder-photo.png"}],
        )
        self.assert_audit_detail_has_photo_thumbnail(log, photo)

    def test_photos_show_nested_folders_in_current_folder(self):
        parent = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Parent")
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=parent, name="Child")
        sibling = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Sibling")
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"folder": parent.pk})

        self.assertContains(response, child.name)
        self.assertNotContains(response, sibling.name)
        self.assertEqual(list(response.context["folder_path"]), [parent])

    def test_photo_bulk_upload_can_target_nested_folder(self):
        parent = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Parent")
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=parent, name="Child")
        self.client.login(username="operator", password="pass12345")
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        image = SimpleUploadedFile("nested-folder.png", buffer.getvalue(), content_type="image/png")

        response = self.client.post(
            reverse("photo_bulk_upload", args=[self.organ.pk]),
            {"images": [image], "descriptions": ["In nested folder"], "folder": child.pk},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(TerritorialOrganPhoto.objects.filter(folder=child, description="In nested folder").exists())

    def test_photo_card_shows_clickable_full_folder_path(self):
        parent = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Parent")
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=parent, name="Child")
        photo = self.create_photo("nested-path.png")
        photo.folder = child
        photo.description = "Nested path photo"
        photo.save(update_fields=["folder", "description"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"folder": child.pk})

        self.assertContains(response, "Parent")
        self.assertContains(response, "Child")
        self.assertContains(response, f"?folder={child.pk}")
        self.assertContains(response, "Nested path photo")
        self.assertContains(response, "bi-chevron-right")
        self.assertContains(response, "В папке Parent: 0 фотографий, 1 папок")
        self.assertContains(response, "В папке Child: 1 фотографий, 0 папок")

    def test_photos_root_shows_only_root_photos(self):
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Folder")
        child = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, parent=folder, name="Child")
        inside = self.create_photo("inside-folder.png")
        inside.folder = child
        inside.description = "Inside folder"
        inside.save(update_fields=["folder", "description"])
        root = self.create_photo("root-photo.png")
        root.description = "Root photo"
        root.save(update_fields=["description"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos", args=[self.organ.pk]))

        self.assertContains(response, "Root photo")
        self.assertContains(response, "Folder")
        self.assertContains(response, '<article class="folder-card"', html=False)
        self.assertContains(response, 'class="folder-card-open"')
        self.assertContains(response, f"folder={folder.pk}")
        self.assertContains(response, "folder-card-counts")
        self.assertNotContains(response, '<article class="folder-card" hx-get=', html=False)
        self.assertContains(response, "Редактировать папку")
        self.assertNotContains(response, "Inside folder")
        self.assertContains(response, "всего фотографий")
        self.assertContains(response, "всего папок")
        self.assertContains(response, "В корне: 1 фотографий, 1 папок")
        self.assertContains(response, 'id="photo-search-input"')
        self.assertContains(response, "input changed delay:1200ms from:#photo-search-input")
        self.assertContains(response, 'hx-sync="this:replace"')
        self.assertContains(response, '<strong>2</strong>', count=2, html=True)

    def test_photos_filter_by_folder(self):
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Facades")
        first = self.create_photo("facade.png")
        first.folder = folder
        first.description = "Inside folder"
        first.save(update_fields=["folder", "description"])
        second = self.create_photo("other.png")
        second.description = "Without folder"
        second.save(update_fields=["description"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"folder": folder.pk})

        self.assertContains(response, "Inside folder")
        self.assertNotContains(response, "Without folder")
        self.assertNotContains(response, "active-filter-bar")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"folder": folder.pk, "q": "inside", "sort": "oldest"})

        reset_url = f'{reverse("photos", args=[self.organ.pk])}?folder={folder.pk}'
        self.assertContains(response, "active-filter-bar")
        self.assertContains(response, "inside")
        self.assertContains(response, "oldest")
        self.assertContains(response, f'hx-get="{reset_url}"')

    def test_photos_can_prioritize_photos_before_folders(self):
        TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Folder")
        photo = self.create_photo("photo-first.png")
        photo.description = "Photo first"
        photo.save(update_fields=["description"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"order": "photos"})

        self.assertEqual(response.context["photo_item_order"], "photos")
        self.assertContains(response, "photo-order-photos")
        self.assertContains(response, "order=photos")
        self.assertContains(response, "порядок: сначала фотографии")
        self.assertContains(response, "Photo first")
        self.assertContains(response, "Folder")

    def test_photo_sort_applies_to_folders(self):
        older = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Older folder")
        newer = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Newer folder")
        TerritorialOrganPhotoFolder.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=3))
        TerritorialOrganPhotoFolder.objects.filter(pk=newer.pk).update(created_at=timezone.now())
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos", args=[self.organ.pk]))

        self.assertEqual(list(response.context["folders"])[0].name, "Newer folder")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"sort": "oldest"})

        self.assertEqual(list(response.context["folders"])[0].name, "Older folder")

    def test_photos_search_includes_folder_names(self):
        TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Assembly hall")
        TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Garage")
        photo = self.create_photo("hall-photo.png")
        photo.description = "Room photo"
        photo.save(update_fields=["description"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"q": "assembly"})

        self.assertContains(response, "Assembly hall")
        self.assertNotContains(response, "Garage")
        self.assertNotContains(response, "Room photo")

    def test_photos_search_is_case_insensitive_for_cyrillic(self):
        folder = TerritorialOrganPhotoFolder.objects.create(territorial_organ=self.organ, name="Фасад")
        photo = self.create_photo("facade-demo.png")
        photo.folder = folder
        photo.description = "Фасад административного здания"
        photo.save(update_fields=["folder", "description"])
        self.client.login(username="operator", password="pass12345")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"q": "фасад"})

        self.assertContains(response, "Фасад")
        self.assertNotContains(response, "Фасад административного здания")

        response = self.client.get(reverse("photos", args=[self.organ.pk]), {"folder": folder.pk, "q": "фасад"})

        self.assertContains(response, "Фасад административного здания")
