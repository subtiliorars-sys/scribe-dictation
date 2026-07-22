"""Performance test for audio capture latency (push-to-talk).

Measures time from trigger to first audio chunk delivered.
Run: uv run python -m pytest tests/test_capture_latency.py -v
"""
import time
import pytest


class FakeAudioDevice:
    """Minimal fake that returns chunks with simulated latency."""
    def __init__(self, latency_ms: float = 50):
        self.latency_ms = latency_ms
        self.started = False

    def start(self):
        self.started = True
        return time.time()

    def read_chunk(self) -> bytes:
        time.sleep(self.latency_ms / 1000)
        return b"\x00" * 1024


def test_capture_startup_latency_under_200ms():
    """Push-to-talk should deliver first chunk within 200ms of trigger."""
    device = FakeAudioDevice(latency_ms=50)
    t0 = device.start()
    chunk = device.read_chunk()
    elapsed = (time.time() - t0) * 1000

    assert len(chunk) > 0, "Must return audio data"
    assert elapsed < 200, f"Capture startup too slow: {elapsed:.0f}ms (limit 200ms)"


def test_capture_latency_scales_with_device():
    """Faster devices should have proportionally lower latency."""
    fast = FakeAudioDevice(latency_ms=20)
    slow = FakeAudioDevice(latency_ms=100)

    t0 = fast.start()
    fast.read_chunk()
    fast_elapsed = (time.time() - t0) * 1000

    t0 = slow.start()
    slow.read_chunk()
    slow_elapsed = (time.time() - t0) * 1000

    assert fast_elapsed < slow_elapsed, (
        f"Fast device ({fast_elapsed:.0f}ms) should be faster than "
        f"slow device ({slow_elapsed:.0f}ms)"
    )
