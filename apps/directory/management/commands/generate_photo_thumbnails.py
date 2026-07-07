from django.core.management.base import BaseCommand

from apps.directory.models import TerritorialOrganPhoto


class Command(BaseCommand):
    help = "Generate missing or refresh existing thumbnails for territorial organ photos."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regenerate thumbnails even when thumbnail fields are already filled.",
        )
        parser.add_argument(
            "--include-deleted",
            action="store_true",
            help="Also generate thumbnails for photos that are currently in the trash.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=200,
            help="Number of photos to iterate per database chunk.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        batch_size = options["batch_size"]
        qs = TerritorialOrganPhoto.objects.all().only("id", "image", "thumbnail_small", "thumbnail_medium", "is_deleted")
        if not options["include_deleted"]:
            qs = qs.filter(is_deleted=False)
        if not force:
            qs = qs.filter(thumbnail_small="") | qs.filter(thumbnail_medium="")

        total = qs.count()
        generated = 0
        skipped = 0
        failed = 0
        for photo in qs.iterator(chunk_size=batch_size):
            if not photo.image:
                skipped += 1
                continue
            try:
                if photo.ensure_thumbnails(force=force, save=True):
                    generated += 1
                else:
                    skipped += 1
            except Exception as exc:  # pragma: no cover - defensive command output
                failed += 1
                self.stderr.write(f"#{photo.pk}: {exc}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Фотографии: {total}. Миниатюры созданы/обновлены: {generated}. Пропущено: {skipped}. Ошибок: {failed}."
            )
        )
