"""Local Whisper transcription service using faster-whisper.

Provides:
- LocalWhisperService: Loads local faster-whisper models and transcribes WAV/audio files
  with custom vocabulary dictionary biasing (initial_prompt) and post-transcription replacements.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from scribe_dictation.export.models import Segment
from scribe_dictation.transcribe.vocabulary import CustomVocabularyManager

DEFAULT_LOCAL_MODEL = "base"


class LocalWhisperService:
    """Service for transcribing audio locally using faster-whisper with vocabulary biasing and translation support."""

    def __init__(
        self,
        model_size: str = DEFAULT_LOCAL_MODEL,
        device: str = "auto",
        compute_type: str = "default",
        vocabulary_manager: Optional[CustomVocabularyManager] = None,
        initial_prompt: Optional[str] = None,
        language: Optional[str] = None,
        task: str = "transcribe",
    ):
        """Initialize LocalWhisperService.

        Args:
            model_size: Model size name (e.g. 'tiny', 'base', 'small', 'medium', 'large-v3').
            device: Compute device ('auto', 'cuda', 'cpu').
            compute_type: Quantization / compute type ('default', 'int8', 'float16', etc.).
            vocabulary_manager: Optional CustomVocabularyManager for prompt biasing and replacements.
            initial_prompt: Optional static initial prompt text.
            language: Language code ('auto', 'es', 'fr', etc.) or None for auto-detection.
            task: 'transcribe' or 'translate' (speech-to-English translation).
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.vocabulary_manager = vocabulary_manager
        self.initial_prompt = initial_prompt
        self.language = language
        self.task = task
        self._model = None

    def _init_model(self) -> None:
        """Lazy load the faster-whisper model."""
        if self._model is not None:
            return

        from faster_whisper import WhisperModel

        device = self.device
        if device == "auto":
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        compute_type = self.compute_type
        if compute_type == "default" or compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        print(
            f"Loading local Whisper model '{self.model_size}' on device '{device}' "
            f"with compute type '{compute_type}'..."
        )
        self._model = WhisperModel(
            self.model_size, device=device, compute_type=compute_type
        )

    def get_initial_prompt(self, extra_prompt: Optional[str] = None) -> Optional[str]:
        """Compute the combined initial_prompt string from vocabulary manager and prompt parameters."""
        base = extra_prompt if extra_prompt is not None else self.initial_prompt

        if self.vocabulary_manager is not None:
            prompt = self.vocabulary_manager.build_initial_prompt(base_prompt=base)
            return prompt if prompt else None

        return base if base else None

    def transcribe(
        self,
        audio_path: str | Path,
        initial_prompt: Optional[str] = None,
        beam_size: int = 5,
        language: Optional[str] = None,
        task: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Transcribe an audio file synchronously.

        Args:
            audio_path: Path to audio file.
            initial_prompt: Optional override or additional prompt for dictionary biasing.
            beam_size: Beam size for decoding.
            language: Optional language code override (e.g. 'es', 'fr', 'auto').
            task: Optional task override ('transcribe' or 'translate').
            **kwargs: Extra parameters passed to model.transcribe.

        Returns:
            Transcribed or translated text with post-transcription replacements applied.
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        try:
            import soundfile as sf
            from scribe_dictation.audio.vad import is_speech_present

            audio_arr, sr = sf.read(str(path), dtype="float32")
            if audio_arr.size == 0 or not is_speech_present(audio_arr, sample_rate=sr):
                return ""
        except Exception:
            pass

        self._init_model()

        prompt = self.get_initial_prompt(initial_prompt)
        transcribe_kwargs = {"beam_size": beam_size, "vad_filter": True, **kwargs}
        if prompt:
            transcribe_kwargs["initial_prompt"] = prompt

        target_lang = language if language is not None else self.language
        if target_lang and target_lang.lower().strip() not in ("auto", "none", ""):
            transcribe_kwargs["language"] = target_lang.lower().strip()

        target_task = task if task is not None else self.task
        if target_task:
            normalized_task = (
                "translate"
                if target_task.lower().strip() in ("translate", "translation")
                else "transcribe"
            )
            transcribe_kwargs["task"] = normalized_task

        segments, _ = self._model.transcribe(str(path), **transcribe_kwargs)
        text_list = [segment.text for segment in segments]
        raw_text = "".join(text_list).strip()

        # Apply post-transcription vocabulary replacements if available
        if self.vocabulary_manager is not None:
            return self.vocabulary_manager.apply_replacements(raw_text)

        return raw_text

    def transcribe_segments(
        self,
        audio_path: str | Path,
        initial_prompt: Optional[str] = None,
        beam_size: int = 5,
        language: Optional[str] = None,
        task: Optional[str] = None,
        **kwargs: Any,
    ) -> list[Segment]:
        """Transcribe an audio file and return timestamped segments.

        Args:
            audio_path: Path to audio file.
            initial_prompt: Optional override or additional prompt for dictionary biasing.
            beam_size: Beam size for decoding.
            language: Optional language code override.
            task: Optional task override ('transcribe' or 'translate').
            **kwargs: Extra parameters passed to model.transcribe.

        Returns:
            List of Segment objects with post-transcription replacements applied.
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        try:
            import soundfile as sf
            from scribe_dictation.audio.vad import is_speech_present

            audio_arr, sr = sf.read(str(path), dtype="float32")
            if audio_arr.size == 0 or not is_speech_present(audio_arr, sample_rate=sr):
                return []
        except Exception:
            pass

        self._init_model()

        prompt = self.get_initial_prompt(initial_prompt)
        transcribe_kwargs = {"beam_size": beam_size, "vad_filter": True, **kwargs}
        if prompt:
            transcribe_kwargs["initial_prompt"] = prompt

        target_lang = language if language is not None else self.language
        if target_lang and target_lang.lower().strip() not in ("auto", "none", ""):
            transcribe_kwargs["language"] = target_lang.lower().strip()

        target_task = task if task is not None else self.task
        if target_task:
            normalized_task = (
                "translate"
                if target_task.lower().strip() in ("translate", "translation")
                else "transcribe"
            )
            transcribe_kwargs["task"] = normalized_task

        segments_gen, _ = self._model.transcribe(str(path), **transcribe_kwargs)
        result_segments: list[Segment] = []

        for seg in segments_gen:
            seg_text = seg.text.strip()
            if self.vocabulary_manager is not None:
                seg_text = self.vocabulary_manager.apply_replacements(seg_text)

            if seg_text:
                result_segments.append(
                    Segment(
                        start=float(seg.start),
                        end=float(seg.end),
                        text=seg_text,
                    )
                )

        return result_segments

    async def transcribe_async(
        self,
        audio_path: str | Path,
        initial_prompt: Optional[str] = None,
        beam_size: int = 5,
        language: Optional[str] = None,
        task: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Asynchronously transcribe an audio file by running local execution in a thread pool."""
        return await asyncio.to_thread(
            self.transcribe,
            audio_path,
            initial_prompt=initial_prompt,
            beam_size=beam_size,
            language=language,
            task=task,
            **kwargs,
        )


class LocalModelManager:
    """Manages downloading, updating, and caching state of local Whisper models."""

    @staticmethod
    def is_model_cached(model_size: str) -> bool:
        """Check if a model size is fully downloaded and cached locally."""
        from faster_whisper import download_model

        try:
            download_model(model_size, local_files_only=True)
            return True
        except Exception:
            return False

    @staticmethod
    def download_or_update(model_size: str) -> str:
        """Download or update the specified Whisper model from Hugging Face."""
        from faster_whisper import download_model

        return download_model(model_size, local_files_only=False)

    @staticmethod
    def run_periodic_check(settings) -> tuple[bool, str]:
        """Perform a check for local model updates if periodic time has elapsed (e.g. 30 days).

        Returns (checked, msg).
        """
        import time

        last_check_str = settings.value("last_local_model_update_check", "")
        now = time.time()

        if last_check_str:
            try:
                last_check = float(last_check_str)
                if now - last_check < 30 * 86400:
                    return False, "Periodic check not due yet."
            except ValueError:
                pass

        settings.setValue("last_local_model_update_check", str(now))
        model_size = settings.value("local_model_size", "base")

        try:
            LocalModelManager.download_or_update(model_size)
            return True, f"Successfully verified/updated local model '{model_size}'."
        except Exception as e:
            return True, f"Failed to verify/update model: {e}"
