"""Tests for the post-paste quick-review toast."""

import os
import sys

import pytest

from scribe_dictation.ui.review_toast import ReviewToast


@pytest.fixture
def qapp():
    """Provide a QApplication using the offscreen platform for headless tests."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    yield instance


class TestReviewToast:
    """Tests for ReviewToast construction and correction signal emission."""

    def test_prefills_original_text(self, qapp):
        toast = ReviewToast("hello wrold")
        assert toast.text_edit.toPlainText() == "hello wrold"

    def test_unedited_finish_emits_identical_pair(self, qapp):
        toast = ReviewToast("hello world")
        results = []
        toast.reviewed.connect(lambda orig, edited: results.append((orig, edited)))
        toast._finish()
        assert results == [("hello world", "hello world")]

    def test_edited_finish_emits_correction_pair(self, qapp):
        toast = ReviewToast("hello wrold")
        results = []
        toast.reviewed.connect(lambda orig, edited: results.append((orig, edited)))
        toast.text_edit.setPlainText("hello world")
        toast._finish()
        assert results == [("hello wrold", "hello world")]

    def test_finish_is_idempotent(self, qapp):
        toast = ReviewToast("hello world")
        results = []
        toast.reviewed.connect(lambda orig, edited: results.append((orig, edited)))
        toast._finish()
        toast._finish()
        assert len(results) == 1

    def test_does_not_steal_focus(self, qapp):
        from PySide6.QtCore import Qt

        toast = ReviewToast("hello world")
        assert toast.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        assert bool(toast.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
