import csv
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

from django.http import FileResponse, StreamingHttpResponse


XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOWNLOAD_READY_COOKIE_PREFIX = "download-ready-"


class TemporaryDownloadFile:
    def __init__(self, path):
        self.path = path
        self.file = open(path, "rb")

    def __getattr__(self, name):
        return getattr(self.file, name)

    def close(self):
        try:
            self.file.close()
        finally:
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass


def temporary_download_response(path, filename, content_type):
    return FileResponse(TemporaryDownloadFile(path), as_attachment=True, filename=filename, content_type=content_type)


def download_ready_response(request, response):
    token = request.GET.get("download_token", "").strip()
    if token and all(char.isalnum() or char in "-_" for char in token):
        response.set_cookie(f"{DOWNLOAD_READY_COOKIE_PREFIX}{token}", "1", max_age=120, path="/", samesite="Lax")
    return response


def workbook_file_response(workbook, filename):
    temp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    path = temp.name
    temp.close()
    try:
        workbook.save(path)
    except Exception:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        raise
    return temporary_download_response(path, filename, XLSX_CONTENT_TYPE)


def csv_file_response(filename, rows):
    temp = tempfile.NamedTemporaryFile("w", suffix=".csv", newline="", encoding="utf-8-sig", delete=False)
    path = temp.name
    try:
        writer = csv.writer(temp)
        writer.writerows(rows)
    except Exception:
        temp.close()
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        raise
    temp.close()
    return temporary_download_response(path, filename, "text/csv; charset=utf-8")


class CsvEcho:
    def write(self, value):
        return value


def csv_streaming_response(filename, rows):
    writer = csv.writer(CsvEcho())
    def stream():
        yield "\ufeff"
        for row in rows:
            yield writer.writerow(row)

    response = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
def safe_download_name(value, fallback):
    name = "".join(char if char.isalnum() or char in "._- " else "_" for char in value).strip()
    return name or fallback


def photo_download_name(photo):
    return safe_download_name(photo.original_filename or Path(photo.image.name).name, f"photo-{photo.pk}")


def unique_archive_name(relative_name, photo_pk, used_names):
    path = PurePosixPath(relative_name)
    parent = "" if str(path.parent) == "." else f"{path.parent}/"
    source_name = path.name
    stem = Path(source_name).stem
    suffix = Path(source_name).suffix
    archive_name = relative_name
    counter = 1
    while archive_name in used_names:
        extra = f"-{photo_pk}" if counter == 1 else f"-{photo_pk}-{counter}"
        archive_name = f"{parent}{stem}{extra}{suffix}"
        counter += 1
    used_names.add(archive_name)
    return archive_name


def photos_zip_response(photos, filename, archive_path_builder=None):
    temp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    path = temp.name
    temp.close()
    used_names = set()
    try:
        # ZIP_STORED instead of ZIP_DEFLATED: uploads are restricted to
        # JPEG/PNG/WebP, which are already compressed, so deflate burns CPU on
        # every download for a ~0% size gain and is the main reason large
        # archives risk the gunicorn request timeout.
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zip_file:
            for index, photo in enumerate(photos, start=1):
                if not photo.image:
                    continue
                source_name = photo_download_name(photo)
                relative_name = archive_path_builder(photo, source_name) if archive_path_builder else f"{index:03d}-{source_name}"
                archive_name = unique_archive_name(relative_name, photo.pk, used_names)
                member = zipfile.ZipInfo(archive_name, date_time=time.localtime(time.time())[:6])
                member.external_attr = 0o600 << 16
                try:
                    # Chunked copy keeps memory flat instead of loading each
                    # photo fully into memory via file_handle.read().
                    with photo.image.open("rb") as file_handle, zip_file.open(member, "w") as target:
                        shutil.copyfileobj(file_handle, target, 256 * 1024)
                except FileNotFoundError:
                    continue
    except Exception:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        raise
    return temporary_download_response(path, filename, "application/zip")
