from django import forms

from .models import TerritorialOrganPhoto, TerritorialOrganPhotoFolder


class TerritorialOrganPhotoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        organ = kwargs.pop("organ", None)
        super().__init__(*args, **kwargs)
        if organ:
            self.fields["folder"].queryset = organ.photo_folders.all()
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
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.setdefault("class", "form-control")

    class Meta:
        model = TerritorialOrganPhotoFolder
        fields = ("name",)
