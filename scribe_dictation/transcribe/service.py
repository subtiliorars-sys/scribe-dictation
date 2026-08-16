"""
Transcription service supporting both OpenAI Whisper API and local faster-whisper.

Provides:
- TranscribeService: async transcription of WAV files
- Automatic retry (2 attempts) on API errors (for online mode)
- Configurable model, local model size, device, and API key
"""

import os
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from scribe_dictation.transcribe.voice_profile import VoiceProfile

DEFAULT_MODEL = "whisper-1"
DEFAULT_LOCAL_MODEL = "base"
MAX_RETRIES = 2
FALLBACK_MESSAGE = (
    "[Transcription failed. Please check your configuration and try again.]"
)


class TranscriptionError(Exception):
    """Raised when transcription fails."""


class TranscribeService:
    """Service for transcribing audio files using OpenAI's Whisper API or local faster-whisper."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        use_local: bool = False,
        local_model_size: str = DEFAULT_LOCAL_MODEL,
        local_device: str = "auto",
        local_compute_type: str = "default",
        voice_profile: Optional[VoiceProfile] = None,
    ):
        self.use_local = use_local
        self.model = model
        self.local_model_size = local_model_size
        self.local_device = local_device
        self.local_compute_type = local_compute_type
        self._local_model = None
        # Pro/Lifetime feature: biases decoding toward the user's learned
        # vocabulary and records new transcripts back into it. None (the
        # default) disables it entirely — see voice_profile.py.
        self.voice_profile = voice_profile

        if not self.use_local:
            self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
            if not self.api_key:
                raise ValueError(
                    "OpenAI API key is required. Set OPENAI_API_KEY environment "
                    "variable or pass api_key to TranscribeService."
                )
            self._client = AsyncOpenAI(api_key=self.api_key)

    def _init_local_model(self):
        """Lazy load the local faster-whisper model."""
        if self._local_model is not None:
            return

        from faster_whisper import WhisperModel

        device = self.local_device
        if device == "auto":
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        compute_type = self.local_compute_type
        if compute_type == "default" or compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        print(
            f"Loading local Whisper model '{self.local_model_size}' on device '{device}' with compute type '{compute_type}'..."
        )
        self._local_model = WhisperModel(
            self.local_model_size, device=device, compute_type=compute_type
        )

    async def transcribe(self, audio_path: str) -> str:
        """Transcribe a WAV audio file.

        Args:
            audio_path: Path to a WAV file.

        Returns:
            Transcribed text.

        Raises:
            TranscriptionError: If transcription fails.
        """
        path = Path(audio_path)
        if not path.exists():
            raise TranscriptionError(f"Audio file not found: {audio_path}")

        initial_prompt = (
            self.voice_profile.bias_prompt() if self.voice_profile else None
        )

        if self.use_local:
            try:
                # Local transcription uses faster-whisper
                self._init_local_model()
                # Run the transcription
                segments, info = self._local_model.transcribe(
                    audio_path, beam_size=5, initial_prompt=initial_prompt
                )
                text_list = [segment.text for segment in segments]
                result = "".join(text_list).strip()
                if self.voice_profile:
                    self.voice_profile.observe(result)
                return result
            except Exception as e:
                print(f"Local transcription failed: {e}")
                return f"[Local transcription failed: {e}]"

        # Online API mode
        last_error: Optional[Exception] = None

        for attempt in range(
            1, MAX_RETRIES + 2
        ):  # 3 attempts total (initial + 2 retries)
            try:
                with open(audio_path, "rb") as audio_file:
                    transcript = await self._client.audio.transcriptions.create(
                        model=self.model,
                        file=audio_file,
                        prompt=initial_prompt or "",
                    )
                if self.voice_profile:
                    self.voice_profile.observe(transcript.text)
                return transcript.text

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES + 1:
                    continue
                break

        error_msg = str(last_error) if last_error else "Unknown error"
        print(f"Transcription failed after {MAX_RETRIES + 1} attempts: {error_msg}")
        return FALLBACK_MESSAGE

    async def transcribe_text(self, text: str) -> str:
        """Synchronous-like convenience: returns the input text unchanged."""
        return text
