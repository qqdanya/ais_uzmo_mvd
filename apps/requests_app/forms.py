from django import forms
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .models import (
    ACTIVE_NEED_STATUS_CHOICES,
    NeedStatus,
    RequestResponse,
    TmcRequest,
    normalize_request_number,
)
from .registry import get_table_or_404


REQUEST_RESPONSE_DUPLICATE_MESSAGE = "Ответ с таким номером уже добавлен к этой заявке."


class BootstrapModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.instance.pk and "request_date" in self.fields:
            self.fields["request_date"].initial = timezone.localdate
        if "status" in self.fields:
            self.fields["status"].choices = ACTIVE_NEED_STATUS_CHOICES
            if not self.is_bound and not self.instance.pk:
                self.fields["status"].initial = ACTIVE_NEED_STATUS_CHOICES[0][0]
            if not self.instance.pk:
                self.fields["status"].label = "Статус исполнения"
        if not self.is_bound and not self.instance.pk and "request_number" in self.fields:
            self.fields["request_number"].widget.attrs["autofocus"] = "autofocus"
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
                field.widget.attrs["type"] = "hidden"
                field.widget.attrs["data-app-date-input"] = "true"


def form_for_table(table_key):
    table = get_table_or_404(table_key)
    model = table["model"]
    editable_fields = table["form_fields"]
    widgets = {field.name: forms.DateInput(attrs={"type": "hidden", "data-app-date-input": "true"}, format="%Y-%m-%d") for field in model._meta.fields if field.get_internal_type() == "DateField"}
    meta = type("Meta", (), {"model": model, "fields": editable_fields, "widgets": widgets})
    return type(f"{model.__name__}Form", (BootstrapModelForm,), {"Meta": meta})


class TmcRequestForm(BootstrapModelForm):
    class Meta:
        model = TmcRequest
        fields = ["request_number", "request_date", "status", "due_date", "comment"]
        widgets = {
            "request_date": forms.DateInput(attrs={"type": "hidden", "data-app-date-input": "true"}, format="%Y-%m-%d"),
            "due_date": forms.DateInput(attrs={"type": "hidden", "data-app-date-input": "true"}, format="%Y-%m-%d"),
        }


class RequestResponseForm(BootstrapModelForm):
    class Meta:
        model = RequestResponse
        fields = ["response_number", "response_date", "note"]
        widgets = {
            "response_date": forms.DateInput(
                attrs={"type": "hidden", "data-app-date-input": "true"},
                format="%Y-%m-%d",
            ),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, request_object, **kwargs):
        self.request_object = request_object
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.instance.pk:
            self.fields["response_date"].initial = timezone.localdate()
            self.fields["response_number"].widget.attrs["autofocus"] = "autofocus"

    def clean_response_number(self):
        value = " ".join((self.cleaned_data.get("response_number") or "").split())
        if not value:
            raise forms.ValidationError("Укажите номер ответа.")
        return value

    def clean(self):
        cleaned_data = super().clean()
        response_number = cleaned_data.get("response_number")
        response_date = cleaned_data.get("response_date")

        if response_date:
            if response_date > timezone.localdate():
                self.add_error("response_date", "Дата ответа не может быть позже сегодняшней.")

        if response_number:
            content_type = ContentType.objects.get_for_model(self.request_object, for_concrete_model=False)
            duplicate = RequestResponse.objects.filter(
                content_type=content_type,
                object_id=self.request_object.pk,
                normalized_response_number=normalize_request_number(response_number),
            )
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error("response_number", REQUEST_RESPONSE_DUPLICATE_MESSAGE)

        return cleaned_data


class QuickStatusUpdateForm(forms.Form):
    status = forms.ChoiceField(
        label="статус исполнения заявки",
        choices=ACTIVE_NEED_STATUS_CHOICES,
        widget=forms.RadioSelect,
    )
    completed_at = forms.DateField(
        label="Дата исполнения",
        required=False,
        widget=forms.DateInput(
            attrs={"type": "hidden", "data-app-date-input": "true"},
            format="%Y-%m-%d",
        ),
        input_formats=["%Y-%m-%d"],
    )

    def __init__(self, *args, current_status, current_completed_at=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_status = current_status

        if not self.is_bound:
            self.initial["status"] = current_status
            if current_status in {NeedStatus.DONE, NeedStatus.REJECTED}:
                self.initial["completed_at"] = current_completed_at

        selected_status = self.data.get("status") if self.is_bound else self.initial.get("status")
        if selected_status == NeedStatus.REJECTED:
            self.fields["completed_at"].label = "Дата отклонения"

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get("status")
        completed_at = cleaned_data.get("completed_at")
        is_terminal = status in {NeedStatus.DONE, NeedStatus.REJECTED}

        if status == self.current_status:
            self.add_error("status", "Выберите новый статус заявки.")
        if is_terminal and not completed_at:
            label = "дату отклонения" if status == NeedStatus.REJECTED else "дату исполнения"
            self.add_error("completed_at", f"Укажите {label}.")
        elif completed_at and completed_at > timezone.localdate():
            self.add_error("completed_at", "Дата не может быть позже сегодняшней.")

        if not is_terminal:
            cleaned_data["completed_at"] = None
        return cleaned_data
