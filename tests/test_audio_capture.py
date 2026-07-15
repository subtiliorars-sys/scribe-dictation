"""Tests for the audio capture module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from scribe_dictation.audio.capture import (
    DATA_DIR,
    AudioRecorder,
    record_until_silence,
)


class TestAudioRecorder:
    """Tests for the AudioRecorder class."""

    @patch("scribe_dictation.audio.capture.sd.InputStream")
    def test_start_recording(self, mock_stream):
        """Recording starts and creates an InputStream."""
        recorder = AudioRecorder(sample_rate=16000, channels=1)
        assert not recorder.is_recording

        recorder.start()
        assert recorder.is_recording
        assert not recorder.is_paused
        mock_stream.assert_called_once()
        mock_stream.return_value.start.assert_called_once()

    @patch("scribe_dictation.audio.capture.sd.InputStream")
    def test_start_twice(self, mock_stream):
        """Calling start() twice should not create a second stream."""
        recorder = AudioRecorder()
        recorder.start()
        recorder.start()
        mock_stream.assert_called_once()

    @patch("scribe_dictation.audio.capture.sd.InputStream")
    def test_pause_resume(self, mock_stream):
        """Pause and resume toggle the paused flag."""
        recorder = AudioRecorder()
        recorder.start()
        assert not recorder.is_paused

        recorder.pause()
        assert recorder.is_paused

        recorder.resume()
        assert not recorder.is_paused

    @patch("scribe_dictation.audio.capture.sd.InputStream")
    @patch("scribe_dictation.audio.capture.sf.write")
    def test_stop_saves_wav(self, mock_sf_write, mock_stream):
        """Stop recording saves the audio to a WAV file."""
        recorder = AudioRecorder()
        recorder.start()

        # Simulate some recording data
        fake_data = np.zeros((1600, 1), dtype="float32")
        recorder._recording = [fake_data]

        filepath = recorder.stop()

        assert not recorder.is_recording
        assert filepath.endswith(".wav")
        mock_sf_write.assert_called_once()
        args, _ = mock_sf_write.call_args
        assert args[0] == filepath  # First arg is the file path
        assert args[2] == 16000  # Third arg is sample rate

    @patch("scribe_dictation.audio.capture.sd.InputStream")
    def test_stop_not_recording_raises(self, mock_stream):
        """Stopping when not recording raises RuntimeError."""
        recorder = AudioRecorder()
        with pytest.raises(RuntimeError, match="Not recording"):
            recorder.stop()

    def test_get_audio_data_empty(self):
        """Getting audio data when nothing recorded returns empty array."""
        recorder = AudioRecorder()
        recorder._recording = []
        data = recorder._get_audio_data()
        assert data.size == 0

    def test_get_audio_data_concatenates(self):
        """Getting audio data concatenates all chunks."""
        recorder = AudioRecorder()
        chunk1 = np.ones((100, 1), dtype="float32")
        chunk2 = np.ones((200, 1), dtype="float32") * 2
        recorder._recording = [chunk1, chunk2]

        data = recorder._get_audio_data()
        assert data.shape == (300, 1)
        assert np.allclose(data[:100], 1.0)
        assert np.allclose(data[100:], 2.0)

    def test_data_dir_created(self):
        """The data directory should exist."""
        assert DATA_DIR.exists()
        assert DATA_DIR.is_dir()


class TestRecordUntilSilence:
    """Tests for the record_until_silence function."""

    def test_detects_silence(self):
        """record_until_silence stops after silence is detected."""
        recorder_mock = MagicMock(spec=AudioRecorder)
        recorder_mock.stop.return_value = "/tmp/test.wav"
        recorder_mock._recording = [np.zeros((1600, 1))]
        recorder_mock._lock = MagicMock()
        recorder_mock.is_recording = True

        with patch(
            "scribe_dictation.audio.capture.AudioRecorder",
            return_value=recorder_mock,
        ), patch("scribe_dictation.audio.capture._rms", return_value=0.001):
            result = record_until_silence(
                sample_rate=16000,
                silence_threshold=0.01,
                silence_duration=0.3,
            )
            assert result == "/tmp/test.wav"
            recorder_mock.stop.assert_called_once()

    def test_resets_on_sound(self):
        """record_until_silence resets the silent block counter when sound is detected."""
        recorder_mock = MagicMock(spec=AudioRecorder)
        recorder_mock.stop.return_value = "/tmp/test.wav"
        recorder_mock._recording = [np.zeros((1600, 1))]
        recorder_mock._lock = MagicMock()
        recorder_mock.is_recording = True

        with patch(
            "scribe_dictation.audio.capture.AudioRecorder",
            return_value=recorder_mock,
        ), patch(
            "scribe_dictation.audio.capture._rms",
            side_effect=[0.001, 0.1, 0.001, 0.001, 0.001],
        ):
            result = record_until_silence(
                sample_rate=16000,
                silence_threshold=0.01,
                silence_duration=0.3,
            )
            assert result == "/tmp/test.wav"
            recorder_mock.stop.assert_called_once()
