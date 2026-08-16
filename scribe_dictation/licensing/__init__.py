"""
Scribe Dictation licensing module.

Two-tier: (1) self-signed offline key verification (legacy), and
(2) Gumroad LicenseService for online-activated, machine-bound licenses.

Both share the same activation cache + UI.
"""

import hashlib
import hmac
import json
import secrets
from enum import Enum

from PySide6.QtCore import QSettings

from scribe_dictation.licensing.service import LicenseService
from scribe_dictation.licensing.hardware import get_machine_fingerprint


class LicenseTier(Enum):
    """Purchase tier. LIFETIME costs more up front (one-time) and unlocks
    everything PRO does, plus tier-gated features like an unbounded voice
    profile. Derived from the cached ``license_type`` string (the Gumroad
    product/variant name), so selling a new tier is a Gumroad-side change —
    no new key format needed."""

    FREE = 0
    PRO = 1
    LIFETIME = 2

    def at_least(self, other: "LicenseTier") -> bool:
        return self.value >= other.value


def get_active_license_tier() -> LicenseTier:
    """Determine the active tier from the cached activation, entirely offline.

    Falls back to the legacy self-signed cache (PRO, no lifetime distinction)
    when there's no v2 cache, so old keys keep working.
    """
    settings = QSettings(ORGANIZATION, APP_NAME)

    raw_v2 = settings.value("license_cache_v2", "")
    if raw_v2:
        try:
            cache = json.loads(raw_v2)
        except (TypeError, ValueError):
            cache = {}
        valid, _reason = LicenseService.validate_cached_activation(
            cache, get_machine_fingerprint()
        )
        if valid:
            license_type = str(cache.get("license_type", "")).lower()
            if "lifetime" in license_type:
                return LicenseTier.LIFETIME
            return LicenseTier.PRO

    if is_offline_cache_valid():
        return LicenseTier.PRO

    return LicenseTier.FREE


# ── Legacy self-signed constants ──────────────────────────
ORGANIZATION = "ScribeDictation"
APP_NAME = "Scribe Dictation"
SETTING_LICENSE_KEY = "license_key"
SETTING_LICENSE_SIGNATURE = "license_signature"
SETTING_MACHINE_UUID = "machine_uuid"
LICENSE_SECRET = "scribe-dictation-super-secret-salt-2026"
KEY_PREFIX = "SCRIBE"
BUY_URL = "https://gumroad.com/l/eyiexi"


def generate_signature(license_key: str, fingerprint: str) -> str:
    data = f"{license_key}:{fingerprint}:{LICENSE_SECRET}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def is_offline_cache_valid() -> bool:
    """Check locally cached activation (works offline, no network call)."""
    settings = QSettings(ORGANIZATION, APP_NAME)
    license_key = settings.value(SETTING_LICENSE_KEY, "")
    cached_sig = settings.value(SETTING_LICENSE_SIGNATURE, "")
    if not license_key or not cached_sig:
        return False
    fingerprint = get_machine_fingerprint()
    expected_sig = generate_signature(str(license_key), fingerprint)
    return cached_sig == expected_sig


def _checksum(body: str) -> str:
    return hmac.new(
        LICENSE_SECRET.encode("utf-8"), body.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:8]


def generate_license_key() -> str:
    body = "-".join(secrets.token_hex(2).upper() for _ in range(3))
    return f"{KEY_PREFIX}-{body}-{_checksum(body).upper()}"


def verify_license_key(license_key: str) -> bool:
    license_key = license_key.strip().upper()
    parts = license_key.split("-")
    if len(parts) != 5 or parts[0] != KEY_PREFIX:
        return False
    body = "-".join(parts[1:4])
    expected = _checksum(body).upper()
    return hmac.compare_digest(parts[4], expected)


def verify_license_online(license_key: str) -> bool:
    """Verify and cache a license. Try Gumroad first, fall back to self-signed."""
    key = license_key.strip()
    if not key:
        return False
    # Gumroad online path
    svc = LicenseService()
    valid, msg, meta = svc.verify_license_online(key, get_machine_fingerprint())
    if valid:
        cache = svc.build_cache(key, get_machine_fingerprint(), meta)
        cache_activation_v2(cache)
        return True
    # Self-signed offline fallback
    if verify_license_key(key):
        cache_activation(key)
        return True
    return False


def cache_activation(license_key: str):
    settings = QSettings(ORGANIZATION, APP_NAME)
    fingerprint = get_machine_fingerprint()
    signature = generate_signature(license_key, fingerprint)
    settings.setValue(SETTING_LICENSE_KEY, license_key)
    settings.setValue(SETTING_LICENSE_SIGNATURE, signature)


def cache_activation_v2(cache: dict):
    settings = QSettings(ORGANIZATION, APP_NAME)
    settings.setValue("license_cache_v2", json.dumps(cache))
    settings.setValue(SETTING_LICENSE_KEY, cache.get("key_hash", ""))
    settings.setValue(SETTING_LICENSE_SIGNATURE, cache.get("fingerprint", ""))


def deactivate_license():
    settings = QSettings(ORGANIZATION, APP_NAME)
    settings.remove(SETTING_LICENSE_KEY)
    settings.remove(SETTING_LICENSE_SIGNATURE)
    settings.remove("license_cache_v2")


__all__ = [
    "LicenseService",
    "get_machine_fingerprint",
    "is_offline_cache_valid",
    "verify_license_online",
    "verify_license_key",
    "generate_license_key",
    "cache_activation",
    "cache_activation_v2",
    "deactivate_license",
    "BUY_URL",
    "ORGANIZATION",
    "APP_NAME",
    "LicenseTier",
    "get_active_license_tier",
]
