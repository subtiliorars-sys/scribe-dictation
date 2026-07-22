"""Tests for audio input device enumeration and stable-id resolution."""

from unittest.mock import patch

from scribe_dictation.audio.devices import (
    InputDevice,
    list_input_devices,
    resolve_device_index,
)

FAKE_DEVICES = [
    {"name": "Built-in Microphone", "max_input_channels": 2, "hostapi": 0},
    {"name": "USB Headset", "max_input_channels": 1, "hostapi": 0},
    {"name": "HDMI Output", "max_input_channels": 0, "hostapi": 0},  # output only
]
FAKE_HOSTAPIS = [{"name": "Core Audio"}]


class TestListInputDevices:
    """Tests for list_input_devices()."""

    @patch("scribe_dictation.audio.devices.sd.query_hostapis", return_value=FAKE_HOSTAPIS)
    @patch("scribe_dictation.audio.devices.sd.query_devices", return_value=FAKE_DEVICES)
    def test_lists_only_input_capable_devices(self, mock_query, mock_hostapis):
        devices = list_input_devices()
        names = [d.name for d in devices]
        assert names == ["Built-in Microphone", "USB Headset"]
        assert "HDMI Output" not in names

    @patch("scribe_dictation.audio.devices.sd.query_hostapis", return_value=FAKE_HOSTAPIS)
    @patch("scribe_dictation.audio.devices.sd.query_devices", return_value=FAKE_DEVICES)
    def test_preserves_index_and_hostapi(self, mock_query, mock_hostapis):
        devices = list_input_devices()
        assert devices[0].index == 0
        assert devices[1].index == 1
        assert devices[0].hostapi_name == "Core Audio"

    @patch("scribe_dictation.audio.devices.sd.query_devices", side_effect=RuntimeError("no backend"))
    def test_returns_empty_list_on_backend_error(self, mock_query):
        """A misbehaving audio backend must not crash enumeration."""
        assert list_input_devices() == []

    def test_stable_id_combines_name_and_hostapi(self):
        dev = InputDevice(index=5, name="Widget Mic", hostapi_name="ALSA")
        assert dev.stable_id == "Widget Mic::ALSA"

    def test_stable_id_independent_of_index(self):
        """Two InputDevice instances with the same name/hostapi but a
        different index (as happens across process restarts) must resolve
        to the same stable id."""
        dev_a = InputDevice(index=0, name="Widget Mic", hostapi_name="ALSA")
        dev_b = InputDevice(index=7, name="Widget Mic", hostapi_name="ALSA")
        assert dev_a.stable_id == dev_b.stable_id


class TestResolveDeviceIndex:
    """Tests for resolve_device_index()."""

    def _devices(self):
        return [
            InputDevice(index=0, name="Built-in Microphone", hostapi_name="Core Audio"),
            InputDevice(index=1, name="USB Headset", hostapi_name="Core Audio"),
        ]

    def test_empty_id_returns_none(self):
        """No saved selection => use the system default."""
        assert resolve_device_index("", self._devices()) is None
        assert resolve_device_index(None, self._devices()) is None

    def test_resolves_matching_device(self):
        devices = self._devices()
        index = resolve_device_index("USB Headset::Core Audio", devices)
        assert index == 1

    def test_missing_device_falls_back_to_none(self):
        """A saved device id that no longer exists (unplugged) must fall
        back to the default rather than raising or crashing."""
        devices = self._devices()
        index = resolve_device_index("Unplugged Mic::Core Audio", devices)
        assert index is None

    def test_index_shift_does_not_break_resolution(self):
        """Even if devices are reordered (index churn) between runs, the
        same stable id must resolve to the device's *current* index."""
        original = [
            InputDevice(index=0, name="Built-in Microphone", hostapi_name="Core Audio"),
            InputDevice(index=1, name="USB Headset", hostapi_name="Core Audio"),
        ]
        saved_id = original[1].stable_id  # "USB Headset::Core Audio"

        reordered = [
            InputDevice(index=0, name="USB Headset", hostapi_name="Core Audio"),
            InputDevice(index=1, name="Built-in Microphone", hostapi_name="Core Audio"),
        ]
        assert resolve_device_index(saved_id, reordered) == 0

    @patch("scribe_dictation.audio.devices.list_input_devices")
    def test_queries_live_devices_when_none_provided(self, mock_list):
        mock_list.return_value = self._devices()
        index = resolve_device_index("USB Headset::Core Audio")
        assert index == 1
        mock_list.assert_called_once()
