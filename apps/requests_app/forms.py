from django import forms
from django.utils import timezone

from .models import ACTIVE_NEED_STATUS_CHOICES, TmcRequest
from .registry import TABLE_BY_KEY


class BootstrapModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.instance.pk and "request_date" in self.fields:
            self.fields["request_date"].initial = timezone.localdate
        if "status" in self.fields:
            self.fields["status"].choices = ACTIVE_NEED_STATUS_CHOICES
            if not self.is_bound and not self.instance.pk:
                self.fields["status"].initial = ACTIVE_NEED_STATUS_CHOICES[0][0]
        if "equipment_type" in self.fields:
            self.fields["equipment_type"].empty_label = "Выберите тип техники"
            choices = list(self.fields["equipment_type"].choices)
            if choices and choices[0][0] == "":
                self.fields["equipment_type"].choices = [("", "Выберите тип техники"), *choices[1:]]
        for field in self.fields.values():
            css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            if isinstance(field.widget, (forms.CheckboxInput, forms.ClearableFileInput)):
                css = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            field.widget.attrs.setdefault("class", css)
            if isinstance(field.widget, forms.DateInput):
                field.widget.attrs.setdefault("type", "date")


def form_for_table(table_key):
    table = TABLE_BY_KEY[table_key]
    model = table["model"]
    editable_fields = table["form_fields"]
    widgets = {field.name: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d") for field in model._meta.fields if field.get_internal_type() == "DateField"}
    meta = type("Meta", (), {"model": model, "fields": editable_fields, "widgets": widgets})
    return type(f"{model.__name__}Form", (BootstrapModelForm,), {"Meta": meta})


class TmcRequestForm(BootstrapModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due_date"].label = "Дата исполнения"

    class Meta:
        model = TmcRequest
        fields = ["request_number", "request_date", "status", "due_date", "comment"]
        widgets = {
            "request_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
