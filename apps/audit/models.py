from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Создание"
        UPDATE = "update", "Изменение"
        DELETE = "delete", "Удаление"
        LOGIN = "login", "Вход"
        LOGOUT = "logout", "Выход"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="пользователь", null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField("действие", max_length=20, choices=Action.choices, db_index=True)
    model_name = models.CharField("модель", max_length=120, blank=True, db_index=True)
    object_id = models.CharField("ID объекта", max_length=64, blank=True)
    object_repr = models.CharField("объект", max_length=255, blank=True)
    old_values = models.JSONField("старые значения", null=True, blank=True)
    new_values = models.JSONField("новые значения", null=True, blank=True)
    territorial_organ = models.ForeignKey("directory.TerritorialOrgan", verbose_name="территориальный орган", null=True, blank=True, on_delete=models.SET_NULL)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.TextField("User-Agent", blank=True)
    created_at = models.DateTimeField("создано", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "запись аудита"
        verbose_name_plural = "журнал действий"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["action", "model_name", "created_at"]),
            # scope_logs_for_user()/filtered_logs() always narrow by
            # territorial_organ (non-admins) or user (employee detail,
            # activity stats) before ordering by -created_at - neither
            # column's default single-field index covers that combination.
            models.Index(fields=["territorial_organ", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.created_at:%d.%m.%Y %H:%M} {self.get_action_display()} {self.object_repr}"
