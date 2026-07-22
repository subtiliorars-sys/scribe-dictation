"""Integration test: audio capture to transcription to clipboard (mocked Whisper).

Verifies the full pipeline works end-to-end with a fake audio source.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the app under test
import main


def test_full_pipeline_writes_to_clipboard():
    """Capture -> transcribe -> clipboard round-trip with mocked Whisper."""
    # Create a minimal WAV file (44-byte header + silence)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        # Minimal WAV header + 0.1s of silence at 16kHz mono
        header = (
            b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
            b"\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00"
            b"\x02\x00\x10\x00data\x00\x00\x00\x00"
        )
        f.write(header)
        f.write(b"\x00" * 3200)  # 0.1s of silence
        tmp_path = f.name

    with patch("main.transcribe_openai", return_value="hello world") as mock_transcribe:
        with patch("main.pyperclip") as mock_clipboard:
            main.transcribe(tmp_path, {"model": "openai"})
            mock_transcribe.assert_called_once()
            mock_clipboard.copy.assert_called_once_with("hello world")

    Path(tmp_path).unlink()


def test_settings_persist_across_loads():
    """Settings written to disk should survive a reload."""
    main.save_settings({"model": "local", "device": "mic1", "hotkey": "ctrl+d", "language": "fr"})
    loaded = main.load_settings()
    assert loaded["model"] == "local"
    assert loaded["device"] == "mic1"
    assert loaded["language"] == "fr"


def test_history_search():
    """Search should find matching transcriptions."""
    main.save_transcription("order pizza for Friday", "openai")
    main.save_transcription("call dentist about appointment", "local")
    main.save_transcription("pizza again next week", "openai")

    results = main.search_history("pizza")
    assert len(results) == 2
    assert all("pizza" in r["text"].lower() for r in results)

    results = main.search_history("dentist")
    assert len(results) == 1
    assert "dentist" in results[0]["text"]
