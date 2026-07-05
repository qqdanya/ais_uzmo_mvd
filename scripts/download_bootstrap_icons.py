from pathlib import Path
from urllib.request import urlretrieve

BOOTSTRAP_ICONS_VERSION = "1.11.3"

FILES = {
    "bootstrap-icons.css": (
        f"https://cdn.jsdelivr.net/npm/bootstrap-icons@{BOOTSTRAP_ICONS_VERSION}/font/bootstrap-icons.css"
    ),
    "fonts/bootstrap-icons.woff": (
        f"https://cdn.jsdelivr.net/npm/bootstrap-icons@{BOOTSTRAP_ICONS_VERSION}/font/fonts/bootstrap-icons.woff"
    ),
    "fonts/bootstrap-icons.woff2": (
        f"https://cdn.jsdelivr.net/npm/bootstrap-icons@{BOOTSTRAP_ICONS_VERSION}/font/fonts/bootstrap-icons.woff2"
    ),
}

BASE_DIR = Path(__file__).resolve().parents[1]
TARGET_DIR = BASE_DIR / "static" / "vendor" / "bootstrap-icons"


def main() -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    for relative_path, url in FILES.items():
        target_path = TARGET_DIR / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"Downloading {url}")
        urlretrieve(url, target_path)
        print(f"Saved to {target_path}")

    print("\nBootstrap Icons downloaded successfully.")
    print(f"Version: {BOOTSTRAP_ICONS_VERSION}")
    print(f"Target: {TARGET_DIR}")


if __name__ == "__main__":
    main()