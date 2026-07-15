"""Tests for the transcription service."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scribe_dictation.transcribe.service import (
    FALLBACK_MESSAGE,
    MAX_RETRIES,
    TranscribeService,
    TranscriptionError,
)


@pytest.fixture
def mock_wav_file(tmp_path: Path) -> str:
    """Create a mock WAV file for testing."""
    wav_path = tmp_path / "test_audio.wav"
    wav_path.write_bytes(b"RIFF....WAVE....fake_wav_data")
    return str(wav_path)


class TestTranscribeServiceInit:
    """Tests for TranscribeService initialization."""

    def test_init_with_api_key(self):
        """Service initializes with explicit API key."""
        service = TranscribeService(api_key="test-key-123")
        assert service.api_key == "test-key-123"
        assert service.model == "whisper-1"

    def test_init_with_env_var(self):
        """Service initializes from environment variable."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key-456"}):
            service = TranscribeService()
            assert service.api_key == "env-key-456"

    def test_init_without_key_raises(self):
        """Missing API key raises ValueError."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="OpenAI API key is required"):
                TranscribeService()

    def test_init_with_custom_model(self):
        """Service accepts a custom model name."""
        service = TranscribeService(api_key="key", model="custom-model")
        assert service.model == "custom-model"


class TestTranscribeServiceTranscribe:
    """Tests for the transcribe method."""

    @pytest.mark.asyncio
    async def test_transcribe_success(self, mock_wav_file):
        """Successful transcription returns the transcribed text."""
        mock_response = MagicMock()
        mock_response.text = "Hello, this is a test transcription."

        service = TranscribeService(api_key="test-key")
        service._client = AsyncMock()
        service._client.audio.transcriptions.create = AsyncMock(
            return_value=mock_response
        )

        result = await service.transcribe(mock_wav_file)
        assert result == "Hello, this is a test transcription."
        # Verify the API was called with the correct model
        service._client.audio.transcriptions.create.assert_called_once()
        call_kwargs = service._client.audio.transcriptions.create.call_args.kwargs
        assert call_kwargs["model"] == "whisper-1"
        # The file arg should be an open file handle
        assert hasattr(call_kwargs["file"], "read")

    @pytest.mark.asyncio
    async def test_transcribe_missing_file(self):
        """Missing audio file raises TranscriptionError."""
        service = TranscribeService(api_key="test-key")
        with pytest.raises(TranscriptionError, match="Audio file not found"):
            await service.transcribe("/nonexistent/file.wav")

    @pytest.mark.asyncio
    async def test_transcribe_retry_then_succeed(self, mock_wav_file):
        """Service retries and succeeds on the second attempt."""
        mock_response = MagicMock()
        mock_response.text = "Success after retry."

        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Temporary API error")
            return mock_response

        service = TranscribeService(api_key="test-key")
        service._client = AsyncMock()
        service._client.audio.transcriptions.create = mock_create

        result = await service.transcribe(mock_wav_file)
        assert result == "Success after retry."
        assert call_count == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_transcribe_all_retries_fail(self, mock_wav_file):
        """When all retries fail, returns fallback message."""
        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception(f"API error #{call_count}")

        service = TranscribeService(api_key="test-key")
        service._client = AsyncMock()
        service._client.audio.transcriptions.create = mock_create

        result = await service.transcribe(mock_wav_file)
        assert result == FALLBACK_MESSAGE
        assert call_count == MAX_RETRIES + 1  # initial + 2 retries = 3

    @pytest.mark.asyncio
    async def test_transcribe_uses_correct_model(self, mock_wav_file):
        """Service sends the configured model to the API."""
        mock_response = MagicMock()
        mock_response.text = "Transcribed text."

        service = TranscribeService(api_key="test-key", model="whisper-2")
        service._client = AsyncMock()
        service._client.audio.transcriptions.create = AsyncMock(
            return_value=mock_response
        )

        await service.transcribe(mock_wav_file)
        # Verify the API was called with the correct model
        service._client.audio.transcriptions.create.assert_called_once()
        call_kwargs = service._client.audio.transcriptions.create.call_args.kwargs
        assert call_kwargs["model"] == "whisper-2"


class TestTranscribeServiceEdgeCases:
    """Tests for edge cases in the transcription service."""

    @pytest.mark.asyncio
    async def test_transcribe_large_file_triggers_retries(self, mock_wav_file):
        """Large file processing errors trigger retry logic."""
        mock_response = MagicMock()
        mock_response.text = "Final result."

        attempts = []

        async def mock_create(**kwargs):
            attempts.append(1)
            if len(attempts) < 3:
                raise Exception("Rate limit exceeded")
            return mock_response

        service = TranscribeService(api_key="test-key")
        service._client = AsyncMock()
        service._client.audio.transcriptions.create = mock_create

        result = await service.transcribe(mock_wav_file)
        assert result == "Final result."
        assert len(attempts) == 3  # initial + 2 retries
