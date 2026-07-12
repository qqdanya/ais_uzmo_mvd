from django.db import migrations, models


def populate_event_types(apps, schema_editor):
    AuditLog = apps.get_model("audit", "AuditLog")
    defaults = {
        "create": "record_created",
        "update": "record_updated",
        "delete": "moved_to_trash",
        "login": "login",
        "logout": "logout",
    }
    for log in AuditLog.objects.only("pk", "action", "new_values").iterator(chunk_size=1000):
        values = log.new_values if isinstance(log.new_values, dict) else {}
        event_type = values.get("audit_event") or defaults.get(log.action, "")
        AuditLog.objects.filter(pk=log.pk).update(event_type=event_type)


class Migration(migrations.Migration):
    dependencies = [("audit", "0002_auditlog_audit_audit_territo_b41ede_idx_and_more")]
    operations = [
        migrations.AddField(
            model_name="auditlog",
            name="event_type",
            field=models.CharField(blank=True, choices=[
                ("record_created", "Создание записи"), ("record_updated", "Изменение записи"),
                ("moved_to_trash", "Перемещение в корзину"), ("request_restored_from_trash", "Восстановление заявки"),
                ("photo_restored_from_trash", "Восстановление фотографии"), ("photo_folder_tree_restored_from_trash", "Восстановление папки"),
                ("photo_file_permanently_deleted", "Окончательное удаление фотографии"), ("photo_folder_tree_permanently_deleted", "Окончательное удаление папки"),
                ("request_status_changed", "Изменение статуса заявки"), ("request_photos_attached", "Прикрепление фотографий"),
                ("request_photos_detached", "Открепление фотографий"), ("tmc_item_added", "Добавление позиции ТМЦ"),
                ("tmc_item_removed", "Удаление позиции ТМЦ"), ("tmc_item_quantity_changed", "Изменение количества ТМЦ"),
                ("tmc_product_created", "Добавление наименования ТМЦ"), ("employee_created", "Создание сотрудника"),
                ("employee_permissions_updated", "Изменение прав сотрудника"), ("employee_blocked", "Блокировка сотрудника"),
                ("employee_unblocked", "Разблокировка сотрудника"), ("employee_activation_reset", "Сброс активации сотрудника"),
                ("employee_deleted", "Удаление сотрудника"), ("account_activated", "Активация учётной записи"),
                ("settings_updated", "Изменение настроек"), ("settings_reset", "Сброс настроек"),
                ("table_exported", "Экспорт таблицы"), ("photo_archive_downloaded", "Скачивание архива фотографий"),
                ("personal_trash_item_removed", "Удаление из личной корзины"), ("personal_trash_cleared", "Очистка личной корзины"),
                ("login", "Вход в систему"), ("logout", "Выход из системы"),
            ], db_index=True, max_length=64, verbose_name="тип события"),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="operation_id",
            field=models.CharField(blank=True, db_index=True, max_length=36, verbose_name="операция"),
        ),
        migrations.RunPython(populate_event_types, migrations.RunPython.noop),
    ]
