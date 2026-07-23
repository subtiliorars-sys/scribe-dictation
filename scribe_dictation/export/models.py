"""Data model for transcription results used by the export layer.

The live app currently only captures a single block of text per recording
(see scribe_dictation/transcribe/service.py), without per-word or per-phrase
timestamps from the Whisper API. To keep exports meaningful and forward
compatible with true segment-level timestamps (e.g. once the service is
switched to request `verbose_json` from the Whisper API), the export layer
is built around a small, self-contained model:

- `Segment`: a span of transcribed text with a start/end time in seconds.
- `TranscriptionResult`: an ordered list of segments, plus optional metadata
  (a title, used as a heading in the Markdown export).

Callers with only a single block of text (today's UI) can build a
`TranscriptionResult` with one `Segment` covering the whole duration.
Callers with real per-segment timestamps (e.g. from Whisper's
`verbose_json` response) can pass those segments directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Segment:
    """A single transcribed span of audio.

    Attributes:
        start: Start time in seconds, relative to the start of the recording.
        end: End time in seconds, relative to the start of the recording.
        text: The transcribed text for this span.
    """

    start: float
    end: float
    text: str

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"Segment.start must be >= 0, got {self.start}")
        if self.end < self.start:
            raise ValueError(
                f"Segment.end ({self.end}) must be >= Segment.start ({self.start})"
            )


@dataclass(frozen=True)
class TranscriptionResult:
    """A full transcription, made up of one or more timestamped segments.

    Attributes:
        segments: Ordered list of segments covering the recording.
        title: Optional human-readable title (used as a Markdown heading).
            Defaults to a timestamp-based title if not provided.
        created_at: When the transcription was produced. Defaults to now.
    """

    segments: list[Segment]
    title: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def text(self) -> str:
        """The full transcript as a single string, segments joined by spaces."""
        return " ".join(segment.text.strip() for segment in self.segments if segment.text.strip())

    @classmethod
    def from_text(
        cls,
        text: str,
        duration: float = 0.0,
        title: str | None = None,
    ) -> "TranscriptionResult":
        """Build a single-segment result from a plain text string.

        Used when only whole-transcript text is available (no per-segment
        timestamps), e.g. the current UI flow. The single segment spans
        from 0 to `duration` seconds.
        """
        return cls(segments=[Segment(start=0.0, end=max(duration, 0.0), text=text)], title=title)
