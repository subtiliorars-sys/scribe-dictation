"""Format writers for exporting a TranscriptionResult.

Three formats are supported:

- Plain text (.txt): one line per segment, prefixed with a
  `[HH:MM:SS]` timestamp marker, e.g.::

      [00:00:00] Hello there.
      [00:00:04] This is a second segment.

  Design choice: segment boundaries in this app correspond to distinct
  transcription events (e.g. separate recordings appended to the same
  session), so preserving a timestamp per line is more useful than
  collapsing everything into unbroken prose, at negligible readability
  cost.

- Markdown (.md): a `#` heading (title + date), followed by one entry per
  segment as a bullet list with the timestamp rendered as a subtle inline
  code marker, e.g. `` - `[00:00:00]` Hello there. ``

- SRT (.srt): standard SubRip subtitle format — 1-indexed entries, each
  with a `HH:MM:SS,mmm --> HH:MM:SS,mmm` timestamp line (comma-separated
  milliseconds, zero-padded), the text, and a blank line between entries.
"""

from __future__ import annotations

from scribe_dictation.export.models import TranscriptionResult


def _format_clock(seconds: float) -> str:
    """Format seconds as zero-padded HH:MM:SS (used by .txt/.md)."""
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_srt_timestamp(seconds: float) -> str:
    """Format seconds as SRT's HH:MM:SS,mmm (comma, zero-padded milliseconds)."""
    if seconds < 0:
        raise ValueError(f"Cannot format a negative timestamp: {seconds}")
    total_ms = round(seconds * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, ms = divmod(remainder_ms, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def to_txt(result: TranscriptionResult) -> str:
    """Render a TranscriptionResult as plain text, one timestamped line per segment."""
    lines = [
        f"[{_format_clock(segment.start)}] {segment.text.strip()}"
        for segment in result.segments
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def to_markdown(result: TranscriptionResult) -> str:
    """Render a TranscriptionResult as Markdown with a heading and bullet list."""
    title = result.title or "Transcription"
    date_str = result.created_at.strftime("%Y-%m-%d %H:%M")
    lines = [f"# {title}", "", f"*{date_str}*", ""]
    for segment in result.segments:
        timestamp = _format_clock(segment.start)
        lines.append(f"- `[{timestamp}]` {segment.text.strip()}")
    return "\n".join(lines) + "\n"


def to_srt(result: TranscriptionResult) -> str:
    """Render a TranscriptionResult as an SRT subtitle file."""
    blocks = []
    for index, segment in enumerate(result.segments, start=1):
        start = _format_srt_timestamp(segment.start)
        end = _format_srt_timestamp(segment.end)
        blocks.append(f"{index}\n{start} --> {end}\n{segment.text.strip()}\n")
    return "\n".join(blocks)
