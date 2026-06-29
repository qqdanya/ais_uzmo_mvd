from django import forms

from .models import TerritorialOrganPhoto, TerritorialOrganPhotoFolder


class TerritorialOrganPhotoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        organ = kwargs.pop("organ", None)
        super().__init__(*args, **kwargs)
        if organ:
            self.fields["folder"].queryset = organ.photo_folders.filter(is_deleted=False)
        self.fields["folder"].empty_label = "Без папки"
        for field_name, field in self.fields.items():
            css_class = "form-select" if field_name == "folder" else "form-control"
            field.widget.attrs.setdefault("class", css_class)

    class Meta:
        model = TerritorialOrganPhoto
        fields = ("folder", "image", "description")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class TerritorialOrganPhotoFolderForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.organ = kwargs.pop("organ", None)
        self.parent = kwargs.pop("parent", None)
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.setdefault("class", "form-control")

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.organ:
            duplicate = TerritorialOrganPhotoFolder.objects.filter(territorial_organ=self.organ, parent=self.parent, name__iexact=name, is_deleted=False)
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise forms.ValidationError("Папка с таким наименованием уже есть на этом уровне.")
        return name

    class Meta:
        model = TerritorialOrganPhotoFolder
        fields = ("name",)
