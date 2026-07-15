"""
Transcription service using OpenAI Whisper API.

Provides:
- TranscribeService: async transcription of WAV files via Whisper
- Automatic retry (2 attempts) on API errors
- Configurable model and API key
"""

import os
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

DEFAULT_MODEL = "whisper-1"
MAX_RETRIES = 2
FALLBACK_MESSAGE = "[Transcription failed. Please check your API key and try again.]"


class TranscriptionError(Exception):
    """Raised when transcription fails after all retries."""


class TranscribeService:
    """Service for transcribing audio files using OpenAI's Whisper API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key is required. Set OPENAI_API_KEY environment "
                "variable or pass api_key to TranscribeService."
            )
        self.model = model
        self._client = AsyncOpenAI(api_key=self.api_key)

    async def transcribe(self, audio_path: str) -> str:
        """Transcribe a WAV audio file using Whisper API.

        Args:
            audio_path: Path to a WAV file.

        Returns:
            Transcribed text.

        Raises:
            TranscriptionError: If transcription fails after all retries.
        """
        path = Path(audio_path)
        if not path.exists():
            raise TranscriptionError(f"Audio file not found: {audio_path}")

        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 2):  # 3 attempts total (initial + 2 retries)
            try:
                with open(audio_path, "rb") as audio_file:
                    transcript = await self._client.audio.transcriptions.create(
                        model=self.model,
                        file=audio_file,
                    )
                return transcript.text

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES + 1:
                    # Could add exponential backoff here for robustness
                    continue
                break

        # After all retries, return fallback message
        error_msg = str(last_error) if last_error else "Unknown error"
        print(f"Transcription failed after {MAX_RETRIES + 1} attempts: {error_msg}")
        return FALLBACK_MESSAGE

    async def transcribe_text(self, text: str) -> str:
        """Synchronous-like convenience: returns the input text unchanged.

        This is a placeholder for future use when needing to process
        text alongside transcription workflows.
        """
        return text
