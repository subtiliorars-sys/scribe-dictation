"""Property / fuzz tests for WAV header integrity in AudioRecorder.

The audio pipeline writes WAV files via ``soundfile`` (``AudioRecorder._save_wav``).
These tests fuzz the audio payload and recorder configuration, then parse the
resulting WAV header back to assert round-trip invariants:

- The declared sample rate matches what the recorder was configured with.
- The channel count matches the payload's channel count.
- The frame count matches the number of samples written.
- The file is a readable RIFF/WAVE container whose data round-trips.

These use Hypothesis to generate a wide range of shapes, rates, and amplitudes,
covering edge cases (empty audio, single sample, many channels, extreme values)
that fixed example-based tests would miss.
"""

import wave
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from scribe_dictation.audio.capture import AudioRecorder

# Realistic sample rates the app might use (Whisper prefers 16 kHz, but the
# recorder accepts any positive rate).
SAMPLE_RATES = st.sampled_from([8000, 11025, 16000, 22050, 44100, 48000])
CHANNEL_COUNTS = st.integers(min_value=1, max_value=4)
FRAME_COUNTS = st.integers(min_value=0, max_value=4096)


def _save(tmp_dir, monkeypatch, audio: np.ndarray, sample_rate: int, channels: int) -> str:
    """Save audio to a WAV under tmp_dir via the recorder's real _save_wav."""
    import scribe_dictation.audio.capture as capture

    monkeypatch.setattr(capture, "DATA_DIR", tmp_dir)
    rec = AudioRecorder(sample_rate=sample_rate, channels=channels)
    return rec._save_wav(audio)


class TestWavHeaderRoundTrip:
    """Round-trip property tests: what we write is what the header reports."""

    @settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        sample_rate=SAMPLE_RATES,
        channels=CHANNEL_COUNTS,
        frames=FRAME_COUNTS,
    )
    def test_header_matches_config(self, tmp_path, monkeypatch, sample_rate, channels, frames):
        """Saved WAV header reports the configured sample rate, channels, frames."""
        rng = np.random.default_rng(seed=frames + channels + sample_rate)
        if channels == 1:
            audio = rng.standard_normal(frames).astype("float32")
        else:
            audio = rng.standard_normal((frames, channels)).astype("float32")
        audio = np.clip(audio, -1.0, 1.0)

        path = _save(tmp_path, monkeypatch, audio, sample_rate, channels)
        assert path.endswith(".wav")
        assert Path(path).exists()

        info = sf.info(path)
        assert info.samplerate == sample_rate
        assert info.channels == channels
        assert info.frames == frames

    @settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(sample_rate=SAMPLE_RATES, frames=st.integers(min_value=1, max_value=2048))
    def test_data_round_trips(self, tmp_path, monkeypatch, sample_rate, frames):
        """Mono float audio read back matches what was written (within PCM tolerance)."""
        rng = np.random.default_rng(seed=frames + sample_rate)
        audio = np.clip(rng.standard_normal(frames).astype("float32"), -1.0, 1.0)

        path = _save(tmp_path, monkeypatch, audio, sample_rate, channels=1)
        read_back, sr = sf.read(path, dtype="float32")

        assert sr == sample_rate
        assert read_back.shape[0] == frames
        # Default soundfile WAV is 16-bit PCM; tolerance is ~1/32768.
        assert np.allclose(read_back, audio, atol=1e-3)

    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(sample_rate=SAMPLE_RATES, channels=CHANNEL_COUNTS)
    def test_riff_wave_container_valid(self, tmp_path, monkeypatch, sample_rate, channels):
        """The saved file is a valid RIFF/WAVE container parseable by stdlib wave.

        ``wave`` only handles PCM; soundfile's default WAV subtype is PCM_16, so
        the stdlib parser is a strong independent check of header correctness.
        """
        frames = 512
        rng = np.random.default_rng(seed=sample_rate + channels)
        audio = np.clip(
            rng.standard_normal((frames, channels)).astype("float32"), -1.0, 1.0
        )

        path = _save(tmp_path, monkeypatch, audio, sample_rate, channels)

        with wave.open(path, "rb") as w:
            assert w.getframerate() == sample_rate
            assert w.getnchannels() == channels
            assert w.getnframes() == frames
            assert w.getsampwidth() == 2  # 16-bit PCM


class TestWavHeaderEdgeCases:
    """Explicit edge cases that anchor the fuzzed properties."""

    def test_empty_audio_writes_valid_header(self, tmp_path, monkeypatch):
        """Zero-length audio still produces a valid, zero-frame WAV."""
        audio = np.array([], dtype="float32")
        path = _save(tmp_path, monkeypatch, audio, sample_rate=16000, channels=1)

        info = sf.info(path)
        assert info.frames == 0
        assert info.samplerate == 16000
        assert info.channels == 1

    def test_single_sample(self, tmp_path, monkeypatch):
        """A single-sample recording has exactly one frame."""
        audio = np.array([0.5], dtype="float32")
        path = _save(tmp_path, monkeypatch, audio, sample_rate=44100, channels=1)

        info = sf.info(path)
        assert info.frames == 1
        assert info.samplerate == 44100

    def test_extreme_amplitudes_round_trip(self, tmp_path, monkeypatch):
        """Full-scale +/-1.0 samples round-trip without header corruption."""
        audio = np.array([1.0, -1.0, 1.0, -1.0], dtype="float32")
        path = _save(tmp_path, monkeypatch, audio, sample_rate=16000, channels=1)

        read_back, sr = sf.read(path, dtype="float32")
        assert sr == 16000
        assert read_back.shape[0] == 4
        assert read_back.max() <= 1.0
        assert read_back.min() >= -1.0

    @pytest.mark.parametrize("sample_rate", [8000, 16000, 48000])
    def test_known_sample_rates(self, tmp_path, monkeypatch, sample_rate):
        """Common sample rates are preserved exactly in the header."""
        audio = np.zeros(256, dtype="float32")
        path = _save(tmp_path, monkeypatch, audio, sample_rate=sample_rate, channels=1)
        assert sf.info(path).samplerate == sample_rate
