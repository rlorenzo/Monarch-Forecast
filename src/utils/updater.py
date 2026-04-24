"""Auto-update checker using GitHub releases."""

import json
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

try:
    CURRENT_VERSION = version("monarch-forecast")
    _VERSION_KNOWN = True
except PackageNotFoundError:
    # Running from source without installed metadata (e.g. pytest, bare
    # `python -m src.main`). Use a neutral sentinel and skip remote update
    # checks so we never report spurious "update available" banners against
    # whatever the real shipping version is.
    CURRENT_VERSION = "0.0.0"
    _VERSION_KNOWN = False
GITHUB_REPO = "rlorenzo/Monarch-Forecast"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def get_current_version() -> str:
    return CURRENT_VERSION


def check_for_update() -> dict[str, Any] | None:
    """Check GitHub releases for a newer version.

    Returns:
        Dict with 'version', 'download_url', 'release_notes' if update available,
        None if current version is latest or check fails.
    """
    if not _VERSION_KNOWN:
        return None
    try:
        req = Request(
            RELEASES_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"Monarch-Forecast/{CURRENT_VERSION}",
            },
        )
        # RELEASES_URL is a hardcoded https://api.github.com constant — no
        # attacker-controlled scheme is reachable here.
        with urlopen(req, timeout=10) as resp:  # nosec B310  # nosemgrep: dynamic-urllib-use-detected
            data = json.loads(resp.read().decode())
    except (URLError, json.JSONDecodeError, OSError):
        return None

    tag = data.get("tag_name", "")
    latest_version = tag.lstrip("v")

    if not latest_version or not _is_newer(latest_version, CURRENT_VERSION):
        return None

    # Find the best download asset for the current platform
    download_url = _find_platform_asset(data.get("assets", []))
    if not download_url:
        download_url = data.get("html_url", "")

    return {
        "version": latest_version,
        "download_url": download_url,
        "release_notes": data.get("body", ""),
        "html_url": data.get("html_url", ""),
    }


def _is_newer(latest: str, current: str) -> bool:
    """Compare semver strings. Returns True if latest > current."""
    try:
        latest_parts = [int(x) for x in latest.split(".")]
        current_parts = [int(x) for x in current.split(".")]
        return latest_parts > current_parts
    except (ValueError, AttributeError):
        return False


def _find_platform_asset(assets: list[dict]) -> str:
    """Find the download URL for the current platform from release assets."""
    import sys

    platform = sys.platform
    platform_keywords: list[str] = []

    if platform == "darwin":
        platform_keywords = ["macos", "darwin", ".dmg"]
    elif platform == "win32":
        platform_keywords = ["windows", ".msix", ".exe"]
    elif platform.startswith("linux"):
        platform_keywords = ["linux", ".appimage", ".deb"]

    for asset in assets:
        name = asset.get("name", "").lower()
        if any(kw in name for kw in platform_keywords):
            return asset.get("browser_download_url", "")

    return ""
