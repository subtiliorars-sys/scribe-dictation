"""GitHub release update checker for Privacy Scribe."""

import logging
import re
import urllib.request
import json
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

CURRENT_VERSION = "1.2.0"
GITHUB_REPO = "subtiliorars-sys/scribe-dictation"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
LATEST_RELEASE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"


def parse_version(v: str) -> Tuple[int, ...]:
    """Parse version string like 'v0.2.1' or '0.2.0' into an integer tuple."""
    clean = re.sub(r"^[^\d]*", "", v.strip())
    parts = []
    for chunk in clean.split("."):
        try:
            parts.append(int(re.match(r"^\d+", chunk).group(0)))
        except (AttributeError, ValueError):
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer_version(latest_tag: str, current_version: str = CURRENT_VERSION) -> bool:
    """Compare remote release tag against current version."""
    try:
        latest_parts = parse_version(latest_tag)
        current_parts = parse_version(current_version)
        return latest_parts > current_parts
    except Exception as e:
        logger.debug(f"Failed to compare versions: {e}")
        return False


def fetch_latest_release_info(timeout: float = 4.0) -> Optional[dict]:
    """Fetch latest release metadata from GitHub API."""
    try:
        req = urllib.request.Request(
            LATEST_RELEASE_API,
            headers={
                "User-Agent": f"PrivacyScribe/{CURRENT_VERSION}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                tag_name = data.get("tag_name", "")
                if tag_name and is_newer_version(tag_name, CURRENT_VERSION):
                    # Extract setup exe asset URL
                    download_url = ""
                    for asset in data.get("assets", []):
                        asset_name = asset.get("name", "")
                        if (
                            asset_name.endswith(".exe")
                            and "setup" in asset_name.lower()
                        ):
                            download_url = asset.get("browser_download_url", "")
                            break
                    if not download_url:
                        # Fallback to any exe
                        for asset in data.get("assets", []):
                            if asset.get("name", "").endswith(".exe"):
                                download_url = asset.get("browser_download_url", "")
                                break
                    return {
                        "tag_name": tag_name,
                        "name": data.get("name", tag_name),
                        "html_url": data.get("html_url", LATEST_RELEASE_URL),
                        "download_url": download_url,
                        "body": data.get("body", ""),
                        "published_at": data.get("published_at", ""),
                    }
    except Exception as e:
        logger.debug(f"Update check failed (offline or rate limited): {e}")
    return None


def download_and_install_update(download_url: str) -> bool:
    """Download the installer and launch it to perform self-update."""
    if not download_url:
        logger.error("No download URL provided for update.")
        return False

    try:
        import os
        import subprocess
        import tempfile

        temp_dir = tempfile.gettempdir()
        installer_path = os.path.join(temp_dir, "PrivacyScribe-Setup-Update.exe")

        req = urllib.request.Request(
            download_url, headers={"User-Agent": f"PrivacyScribe/{CURRENT_VERSION}"}
        )
        with urllib.request.urlopen(req, timeout=60.0) as response:
            with open(installer_path, "wb") as f:
                f.write(response.read())

        # Start the installer as a detached process and return success so app can exit
        subprocess.Popen([installer_path, "/SILENT"], close_fds=True)
        return True
    except Exception as e:
        logger.error(f"Failed to download or run update installer: {e}")
        return False
