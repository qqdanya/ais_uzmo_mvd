from django import forms

from .models import TerritorialOrganPhoto, TerritorialOrganPhotoFolder


def photo_folder_path_label(folder):
    path = []
    current = folder
    while current:
        path.append(current.name)
        current = current.parent
    return " / ".join(reversed(path))


class TerritorialOrganPhotoForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        organ = kwargs.pop("organ", None)
        super().__init__(*args, **kwargs)
        if organ:
            self.fields["folder"].queryset = organ.photo_folders.select_related("parent").filter(is_deleted=False)
        self.fields["folder"].empty_label = "Без папки"
        self.fields["folder"].label_from_instance = photo_folder_path_label
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
        if self.instance.pk:
            excluded_ids = self.descendant_ids(self.instance)
            self.fields["parent"].label = "Расположение"
            self.fields["parent"].empty_label = "Корень"
            self.fields["parent"].queryset = (
                self.organ.photo_folders.select_related("parent").filter(is_deleted=False).exclude(pk__in=excluded_ids)
                if self.organ
                else TerritorialOrganPhotoFolder.objects.none()
            )
            self.fields["parent"].label_from_instance = photo_folder_path_label
            self.fields["parent"].widget.attrs.setdefault("class", "form-select")
        else:
            self.fields.pop("parent", None)

    @staticmethod
    def descendant_ids(folder):
        folder_ids = [folder.pk]
        pending = [folder.pk]
        while pending:
            child_ids = list(TerritorialOrganPhotoFolder.objects.filter(parent_id__in=pending, is_deleted=False).values_list("pk", flat=True))
            folder_ids.extend(child_ids)
            pending = child_ids
        return folder_ids

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        parent = self.cleaned_data.get("parent") if "parent" in self.cleaned_data else self.parent
        if self.instance.pk and self.is_bound and "parent" not in self.data:
            parent = self.parent
        if self.organ:
            duplicate = TerritorialOrganPhotoFolder.objects.filter(territorial_organ=self.organ, parent=parent, name__iexact=name, is_deleted=False)
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise forms.ValidationError("Папка с таким наименованием уже есть на этом уровне.")
        return name

    class Meta:
        model = TerritorialOrganPhotoFolder
        fields = ("name", "parent")
