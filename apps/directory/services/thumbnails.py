from hashlib import blake2b
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError


PHOTO_THUMBNAIL_SIZES = {
    "small": (160, 160),
    "medium": (640, 480),
}
PHOTO_THUMBNAIL_FIELDS = {
    "small": "thumbnail_small",
    "medium": "thumbnail_medium",
}


def thumbnail_storage_name(photo, kind):
    source = Path(photo.image.name)
    digest = blake2b(f"{photo.pk}:{photo.image.name}:{kind}".encode("utf-8"), digest_size=8).hexdigest()
    stem = source.stem[:80] or f"photo-{photo.pk}"
    return f"territorial_organs/thumbnails/{kind}/{stem}-{digest}.jpg"


def _build_thumbnail_content(photo, kind):
    size = PHOTO_THUMBNAIL_SIZES[kind]
    photo.image.open("rb")
    try:
        with Image.open(photo.image) as source_image:
            image = ImageOps.exif_transpose(source_image)
            image.thumbnail(size, Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "L"}:
                background = Image.new("RGB", image.size, "white")
                if image.mode in {"RGBA", "LA"}:
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=82, optimize=True, progressive=True)
            return ContentFile(buffer.getvalue())
    finally:
        photo.image.close()


def ensure_thumbnails(photo, *, force=False, save=True):
    if not photo.pk or not photo.image:
        return False
    changed = False
    for kind, field_name in PHOTO_THUMBNAIL_FIELDS.items():
        field = getattr(photo, field_name)
        if field and not force:
            continue
        old_name = field.name if field else ""
        if old_name:
            field.storage.delete(old_name)
        try:
            content = _build_thumbnail_content(photo, kind)
        except (OSError, ValueError, UnidentifiedImageError):
            continue
        field.save(thumbnail_storage_name(photo, kind), content, save=False)
        changed = True
    if changed and save:
        type(photo).objects.filter(pk=photo.pk).update(
            thumbnail_small=photo.thumbnail_small.name,
            thumbnail_medium=photo.thumbnail_medium.name,
        )
    return changed


def delete_thumbnail_files(photo):
    for field_name in PHOTO_THUMBNAIL_FIELDS.values():
        field = getattr(photo, field_name)
        if field:
            field.delete(save=False)
