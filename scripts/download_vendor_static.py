"""Download pinned frontend vendor assets into static/vendor/.

This script intentionally pins the exact CDN versions currently used by the project.
Run it from the project root before switching templates from CDN to local vendor files,
or as a verification step when refreshing vendor assets.
"""
from __future__ import annotations

import shutil
import sys
import urllib.request
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = ROOT / "static" / "vendor"

ASSETS = [
    (
        "Bootstrap CSS 5.3.3",
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
        VENDOR_ROOT / "bootstrap" / "bootstrap.min.css",
    ),
    (
        "Bootstrap JS bundle 5.3.3",
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
        VENDOR_ROOT / "bootstrap" / "bootstrap.bundle.min.js",
    ),
    (
        "HTMX 1.9.12",
        "https://unpkg.com/htmx.org@1.9.12",
        VENDOR_ROOT / "htmx" / "htmx.min.js",
    ),
    (
        "Chart.js 4.4.3 UMD",
        "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js",
        VENDOR_ROOT / "chartjs" / "chart.umd.min.js",
    ),
]

BOOTSTRAP_ICONS_ZIP_URL = "https://github.com/twbs/icons/releases/download/v1.11.3/bootstrap-icons-1.11.3.zip"
BOOTSTRAP_ICONS_DIR = VENDOR_ROOT / "bootstrap-icons"


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - pinned HTTPS URLs.
        destination.write_bytes(response.read())


def download_bootstrap_icons() -> None:
    archive_path = VENDOR_ROOT / "bootstrap-icons-1.11.3.zip"
    download(BOOTSTRAP_ICONS_ZIP_URL, archive_path)
    temp_dir = VENDOR_ROOT / "_bootstrap-icons-extract"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    with ZipFile(archive_path) as archive:
        archive.extractall(temp_dir)

    source_root = temp_dir / "bootstrap-icons-1.11.3" / "font"
    if not source_root.exists():
        raise RuntimeError("Unexpected Bootstrap Icons archive structure")

    BOOTSTRAP_ICONS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_root / "bootstrap-icons.css", BOOTSTRAP_ICONS_DIR / "bootstrap-icons.css")
    fonts_dir = BOOTSTRAP_ICONS_DIR / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    for font_file in (source_root / "fonts").iterdir():
        if font_file.is_file():
            shutil.copy2(font_file, fonts_dir / font_file.name)

    archive_path.unlink(missing_ok=True)
    shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> int:
    try:
        for label, url, destination in ASSETS:
            print(f"Downloading {label} -> {destination.relative_to(ROOT)}")
            download(url, destination)
        print(f"Downloading Bootstrap Icons 1.11.3 -> {BOOTSTRAP_ICONS_DIR.relative_to(ROOT)}")
        download_bootstrap_icons()
    except Exception as exc:  # pragma: no cover - command-line failure path.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Vendor static assets downloaded successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
