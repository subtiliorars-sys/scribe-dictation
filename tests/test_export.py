"""Tests for the export module (scribe_dictation.export)."""

from datetime import datetime

import pytest

from scribe_dictation.export.formats import (
    _format_clock,
    _format_srt_timestamp,
    to_markdown,
    to_srt,
    to_txt,
)
from scribe_dictation.export.models import Segment, TranscriptionResult


@pytest.fixture
def sample_result() -> TranscriptionResult:
    """A synthetic transcription with a few segments and known timestamps."""
    return TranscriptionResult(
        segments=[
            Segment(start=0.0, end=2.5, text="Hello there."),
            Segment(start=2.5, end=6.0, text="This is a second segment."),
            Segment(start=6.0, end=9.25, text="And a third one."),
        ],
        title="Test Session",
        created_at=datetime(2026, 7, 20, 9, 30),
    )


class TestSegment:
    def test_valid_segment(self):
        seg = Segment(start=1.0, end=2.0, text="hi")
        assert seg.start == 1.0
        assert seg.end == 2.0

    def test_negative_start_raises(self):
        with pytest.raises(ValueError):
            Segment(start=-1.0, end=2.0, text="hi")

    def test_end_before_start_raises(self):
        with pytest.raises(ValueError):
            Segment(start=5.0, end=2.0, text="hi")

    def test_zero_length_segment_is_valid(self):
        seg = Segment(start=3.0, end=3.0, text="hi")
        assert seg.start == seg.end


class TestTranscriptionResult:
    def test_text_joins_segments(self, sample_result):
        assert sample_result.text == (
            "Hello there. This is a second segment. And a third one."
        )

    def test_text_skips_blank_segments(self):
        result = TranscriptionResult(
            segments=[
                Segment(start=0.0, end=1.0, text="Hello"),
                Segment(start=1.0, end=1.0, text="   "),
                Segment(start=1.0, end=2.0, text="World"),
            ]
        )
        assert result.text == "Hello World"

    def test_from_text_builds_single_segment(self):
        result = TranscriptionResult.from_text("Some text", duration=4.0)
        assert len(result.segments) == 1
        assert result.segments[0].start == 0.0
        assert result.segments[0].end == 4.0
        assert result.segments[0].text == "Some text"


class TestFormatClock:
    def test_zero(self):
        assert _format_clock(0) == "00:00:00"

    def test_sub_minute(self):
        assert _format_clock(45) == "00:00:45"

    def test_over_an_hour(self):
        assert _format_clock(3725) == "01:02:05"


class TestFormatSrtTimestamp:
    def test_zero(self):
        assert _format_srt_timestamp(0.0) == "00:00:00,000"

    def test_sub_second(self):
        assert _format_srt_timestamp(0.5) == "00:00:00,500"

    def test_sub_second_precise(self):
        assert _format_srt_timestamp(1.234) == "00:00:01,234"

    def test_exactly_one_minute(self):
        assert _format_srt_timestamp(60.0) == "00:01:00,000"

    def test_over_an_hour(self):
        # 1h 2m 3.456s
        assert _format_srt_timestamp(3723.456) == "01:02:03,456"

    def test_rounds_milliseconds(self):
        # 1.2345s * 1000 = 1234.5ms; Python's round() is round-half-to-even,
        # so this rounds down to the nearest even millisecond (1234).
        assert _format_srt_timestamp(1.2345) == "00:00:01,234"

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            _format_srt_timestamp(-1.0)

    def test_large_hours_not_truncated(self):
        # 10 hours, 0 minutes, 0 seconds
        assert _format_srt_timestamp(36000.0) == "10:00:00,000"


class TestToTxt:
    def test_basic_output(self, sample_result):
        expected = (
            "[00:00:00] Hello there.\n"
            "[00:00:02] This is a second segment.\n"
            "[00:00:06] And a third one.\n"
        )
        assert to_txt(sample_result) == expected

    def test_empty_result(self):
        result = TranscriptionResult(segments=[])
        assert to_txt(result) == ""


class TestToMarkdown:
    def test_basic_output(self, sample_result):
        output = to_markdown(sample_result)
        assert output.startswith("# Test Session\n")
        assert "*2026-07-20 09:30*" in output
        assert "- `[00:00:00]` Hello there." in output
        assert "- `[00:00:02]` This is a second segment." in output
        assert "- `[00:00:06]` And a third one." in output

    def test_default_title(self):
        result = TranscriptionResult(
            segments=[Segment(start=0.0, end=1.0, text="hi")],
            created_at=datetime(2026, 1, 1, 0, 0),
        )
        assert to_markdown(result).startswith("# Transcription\n")


class TestToSrt:
    def test_basic_output(self, sample_result):
        expected = (
            "1\n"
            "00:00:00,000 --> 00:00:02,500\n"
            "Hello there.\n"
            "\n"
            "2\n"
            "00:00:02,500 --> 00:00:06,000\n"
            "This is a second segment.\n"
            "\n"
            "3\n"
            "00:00:06,000 --> 00:00:09,250\n"
            "And a third one.\n"
        )
        assert to_srt(sample_result) == expected

    def test_sub_second_and_over_an_hour(self):
        result = TranscriptionResult(
            segments=[
                Segment(start=0.0, end=0.75, text="Quick one."),
                Segment(start=3661.5, end=3663.005, text="An hour in."),
            ]
        )
        expected = (
            "1\n"
            "00:00:00,000 --> 00:00:00,750\n"
            "Quick one.\n"
            "\n"
            "2\n"
            "01:01:01,500 --> 01:01:03,005\n"
            "An hour in.\n"
        )
        assert to_srt(result) == expected

    def test_empty_result(self):
        result = TranscriptionResult(segments=[])
        assert to_srt(result) == ""

    def test_sequential_indices(self, sample_result):
        output = to_srt(sample_result)
        indices = [
            line for line in output.split("\n") if line.strip().isdigit()
        ]
        assert indices == ["1", "2", "3"]
