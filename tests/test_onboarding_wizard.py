"""Tests for the first-run onboarding wizard."""

import os
import sys

import pytest
from PySide6.QtCore import QSettings

from scribe_dictation.ui.onboarding_wizard import (
    APP_NAME,
    ORGANIZATION,
    PAGE_DOWNLOAD,
    PAGE_HOTKEY,
    PAGE_MIC,
    PAGE_TRY_IT,
    SETTINGS_FIRST_RUN_COMPLETE,
    ModePage,
    OnboardingWizard,
    should_show_onboarding,
)


@pytest.fixture
def qapp():
    """Provide a QApplication using the offscreen platform for headless tests."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    yield instance


@pytest.fixture
def clean_settings():
    """Clear the first-run flag before and after each test to avoid pollution."""
    settings = QSettings(ORGANIZATION, APP_NAME)
    settings.remove(SETTINGS_FIRST_RUN_COMPLETE)
    yield settings
    settings.remove(SETTINGS_FIRST_RUN_COMPLETE)


class TestModePageRouting:
    """Tests for ModePage.nextId() routing to download vs. mic."""

    def test_local_mode_routes_to_download(self, qapp):
        page = ModePage()
        idx = page.mode_combo.findData("local")
        page.mode_combo.setCurrentIndex(idx)
        assert page.is_local() is True
        assert page.nextId() == PAGE_DOWNLOAD

    def test_api_mode_routes_to_mic(self, qapp):
        page = ModePage()
        idx = page.mode_combo.findData("api")
        page.mode_combo.setCurrentIndex(idx)
        assert page.is_local() is False
        assert page.nextId() == PAGE_MIC

    def test_field_visibility_toggles_with_mode(self, qapp):
        page = ModePage()
        idx = page.mode_combo.findData("api")
        page.mode_combo.setCurrentIndex(idx)
        assert page.api_key_input.isVisible() or not page.isVisible()
        # model size combo should be hidden in API mode regardless of window visibility state
        assert page.model_size_combo.isVisibleTo(page) is False


class TestShouldShowOnboarding:
    """Tests for the first-run flag gate."""

    def test_shows_by_default(self, qapp, clean_settings):
        assert should_show_onboarding(clean_settings) is True

    def test_hidden_once_completed(self, qapp, clean_settings):
        clean_settings.setValue(SETTINGS_FIRST_RUN_COMPLETE, "true")
        assert should_show_onboarding(clean_settings) is False


class TestWizardConstruction:
    """Tests that the wizard builds all expected pages without crashing."""

    def test_all_pages_registered(self, qapp):
        wizard = OnboardingWizard()
        page_ids = wizard.pageIds()
        for expected in (PAGE_DOWNLOAD, PAGE_MIC, PAGE_HOTKEY, PAGE_TRY_IT):
            assert expected in page_ids

    def test_finish_sets_first_run_flag(self, qapp, clean_settings):
        from PySide6.QtWidgets import QWizard

        wizard = OnboardingWizard()
        wizard._on_finished(QWizard.DialogCode.Rejected)
        assert clean_settings.value(SETTINGS_FIRST_RUN_COMPLETE) == "true"


class TestHotkeyPageDispatch:
    """Regression test: _start_global_hotkey dispatches by Qt slot name via
    QMetaObject.invokeMethod, so the press callback MUST be a real @Slot or
    the dispatch silently no-ops and the hotkey page never completes.
    """

    def test_on_press_is_invokable_by_name(self, qapp):
        from PySide6.QtCore import QMetaObject, Qt

        from scribe_dictation.ui.onboarding_wizard import HotkeyPage

        page = HotkeyPage()
        assert page._detected is False

        invoked = QMetaObject.invokeMethod(
            page, "_on_press", Qt.ConnectionType.DirectConnection
        )
        assert invoked is True
        assert page._detected is True


class TestModePageLabelVisibility:
    """Regression test: hiding the API key / model size fields must also
    hide their QFormLayout row labels, or the label ("API Key:") is left
    dangling above an invisible field, confusing users.
    """

    def test_api_key_label_hidden_in_local_mode(self, qapp):
        page = ModePage()
        idx = page.mode_combo.findData("local")
        page.mode_combo.setCurrentIndex(idx)
        assert page.api_key_input.isVisible() is False
        assert page.api_key_label.isVisible() is False

    def test_model_size_label_hidden_in_api_mode(self, qapp):
        page = ModePage()
        idx = page.mode_combo.findData("api")
        page.mode_combo.setCurrentIndex(idx)
        assert page.model_size_combo.isVisible() is False
        assert page.model_size_label.isVisible() is False
