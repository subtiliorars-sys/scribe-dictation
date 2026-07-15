"""
Audio capture module using sounddevice.

Provides:
- AudioRecorder: start/stop/pause/resume recording to temp WAV files
- record_until_silence(): auto-stop after silence detection
"""

import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

# Default configuration
DEFAULT_SAMPLE_RATE = 16000  # 16 kHz — optimal for Whisper
DEFAULT_CHANNELS = 1
DEFAULT_DTYPE = "float32"
SILENCE_THRESHOLD = 0.01  # RMS threshold for silence
SILENCE_DURATION = 1.5  # seconds of silence before auto-stop

# Ensure data directory exists
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class AudioRecorder:
    """Record from the default microphone with start/stop/pause/resume."""

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        dtype: str = DEFAULT_DTYPE,
        device: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.device = device

        self._recording: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._is_recording = False
        self._is_paused = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def start(self) -> None:
        """Start recording audio from the default microphone."""
        if self._is_recording:
            return

        self._recording = []
        self._is_recording = True
        self._is_paused = False
        self._stop_event.clear()

        def callback(indata: np.ndarray, frames: int, time_info, status) -> None:
            """Stream callback — appends data when not paused."""
            if status:
                print(f"Audio stream status: {status}")
            if not self._is_paused:
                with self._lock:
                    self._recording.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            device=self.device,
            callback=callback,
        )
        self._stream.start()

    def stop(self) -> str:
        """Stop recording and save audio to a temp WAV file.

        Returns:
            Path to the saved WAV file.
        """
        if not self._is_recording:
            raise RuntimeError("Not recording")

        self._is_recording = False
        self._stop_event.set()

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        audio_data = self._get_audio_data()
        return self._save_wav(audio_data)

    def pause(self) -> None:
        """Pause recording (data is not appended while paused)."""
        if self._is_recording and not self._is_paused:
            self._is_paused = True

    def resume(self) -> None:
        """Resume recording after a pause."""
        if self._is_recording and self._is_paused:
            self._is_paused = False

    def _get_audio_data(self) -> np.ndarray:
        """Concatenate all recorded chunks into a single array."""
        with self._lock:
            if not self._recording:
                return np.array([], dtype=self.dtype)
            return np.concatenate(self._recording, axis=0)

    def _save_wav(self, audio_data: np.ndarray) -> str:
        """Save audio data to a WAV file in the data directory.

        Returns:
            Absolute path to the saved WAV file.
        """
        fd, tmp_path = tempfile.mkstemp(suffix=".wav", dir=str(DATA_DIR))
        os.close(fd)
        sf.write(tmp_path, audio_data, self.sample_rate)
        return tmp_path


def _rms(data: np.ndarray) -> float:
    """Compute the root mean square of audio data."""
    if data.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(data**2)))


def record_until_silence(
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    dtype: str = DEFAULT_DTYPE,
    silence_threshold: float = SILENCE_THRESHOLD,
    silence_duration: float = SILENCE_DURATION,
    device: Optional[int] = None,
) -> str:
    """Record audio until silence is detected for the given duration.

    Args:
        sample_rate: Sampling rate in Hz.
        channels: Number of audio channels.
        dtype: Audio data type.
        silence_threshold: RMS threshold below which audio is considered silence.
        silence_duration: Seconds of sustained silence before stopping.
        device: Optional device ID.

    Returns:
        Path to the saved WAV file.
    """
    recorder = AudioRecorder(
        sample_rate=sample_rate,
        channels=channels,
        dtype=dtype,
        device=device,
    )
    recorder.start()

    block_duration = 0.1  # seconds per check
    blocks_for_silence = int(silence_duration / block_duration)
    silent_blocks = 0

    try:
        while True:
            time.sleep(block_duration)
            with recorder._lock:
                if not recorder._recording:
                    continue
                # Check the most recent block for silence
                latest = recorder._recording[-1]
                level = _rms(latest)

            if level < silence_threshold:
                silent_blocks += 1
                if silent_blocks >= blocks_for_silence:
                    break
            else:
                silent_blocks = 0
    finally:
        pass  # Let the caller decide when to stop

    return recorder.stop()
