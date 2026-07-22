"""
Audio input device enumeration and stable-identifier resolution.

sounddevice exposes devices by *index*, but indices are not stable across
runs (or even within a run, if a device is plugged/unplugged) — they are
simply positions in whatever list the current host API backend returns.
To persist a user's device choice reliably, we build a stable identifier
from the device name plus its host API name (e.g. "Microphone (Realtek
Audio)::MME"). That composite is what sounddevice actually keeps constant
for a given physical device across process restarts, even though the
numeric index can drift.
"""

from dataclasses import dataclass
from typing import Optional

import sounddevice as sd

DEFAULT_DEVICE_ID = ""  # sentinel meaning "use system default"


@dataclass(frozen=True)
class InputDevice:
    """A single audio input device available on the system."""

    index: int
    name: str
    hostapi_name: str

    @property
    def stable_id(self) -> str:
        """A stable identifier for persistence, robust to index churn."""
        return f"{self.name}::{self.hostapi_name}"

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.hostapi_name})"


def list_input_devices() -> list[InputDevice]:
    """Return all devices with at least one input channel.

    Any error querying the audio backend results in an empty list rather
    than raising, so callers (UI, startup wiring) never crash because of
    a misbehaving driver.
    """
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        return []

    result = []
    for i, dev in enumerate(devices):
        try:
            if dev.get("max_input_channels", 0) > 0:
                hostapi_index = dev.get("hostapi", 0)
                hostapi_name = hostapis[hostapi_index]["name"] if hostapi_index < len(hostapis) else ""
                result.append(InputDevice(index=i, name=dev["name"], hostapi_name=hostapi_name))
        except Exception:
            continue
    return result


def resolve_device_index(
    stable_id: Optional[str], devices: Optional[list[InputDevice]] = None
) -> Optional[int]:
    """Resolve a persisted stable device id to a current sounddevice index.

    Returns ``None`` (meaning "use the system default input device") when:
    - ``stable_id`` is empty/None (no selection was ever made), or
    - the previously-selected device is no longer present (e.g. unplugged).

    This is the graceful-fallback path required so a missing device never
    crashes capture — it silently reverts to default.
    """
    if not stable_id:
        return None

    if devices is None:
        devices = list_input_devices()

    for dev in devices:
        if dev.stable_id == stable_id:
            return dev.index

    return None
