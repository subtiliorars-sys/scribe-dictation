"""First-run setup wizard for Privacy Scribe.

Walks a new user through choosing a transcription mode, downloading the
local model (if applicable), picking a microphone, testing the global
hotkey, and trying a real dictation -- all skippable at any step.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Optional

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QSettings, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from scribe_dictation.transcribe.vocabulary import CustomVocabularyManager

ORGANIZATION = "PrivacyScribe"
APP_NAME = "Privacy Scribe"

SETTINGS_FIRST_RUN_COMPLETE = "first_run_complete"

PAGE_WELCOME, PAGE_MODE, PAGE_DOWNLOAD, PAGE_MIC, PAGE_HOTKEY, PAGE_TRY_IT = range(6)


class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Welcome to Privacy Scribe")
        layout = QVBoxLayout(self)
        label = QLabel(
            "<p>Privacy Scribe turns your voice into text anywhere on your "
            "computer.</p>"
            "<p>Press <b>Ctrl + Win</b> (configurable later) to start "
            "recording, speak, then release to transcribe and paste "
            "automatically into whatever app has focus.</p>"
            "<p>This short setup will get your microphone and transcription "
            "engine ready. You can skip it at any time and revisit it later "
            "from <b>Help &gt; Setup Tutorial</b>.</p>"
        )
        label.setWordWrap(True)
        layout.addWidget(label)


class ModePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Choose a Transcription Mode")
        layout = QFormLayout(self)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Local Engine - Offline & Private", "local")
        self.mode_combo.addItem("Cloud API - Faster, Needs API Key", "api")
        layout.addRow("Mode:", self.mode_combo)

        info = QLabel(
            "Local mode transcribes entirely on your machine -- nothing "
            "leaves your computer, but the first run downloads a model. "
            "Cloud API mode uses OpenAI's Whisper API for higher accuracy "
            "and needs an API key."
        )
        info.setWordWrap(True)
        layout.addRow(info)

        self.model_size_combo = QComboBox()
        for size, label in [
            ("tiny", "tiny (Ultra Fast)"),
            ("base", "base (Default)"),
            ("small", "small (Better Quality)"),
        ]:
            self.model_size_combo.addItem(label, size)
        layout.addRow("Local Model Size:", self.model_size_combo)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("sk-...")
        layout.addRow("API Key:", self.api_key_input)

        self.model_size_label = layout.labelForField(self.model_size_combo)
        self.api_key_label = layout.labelForField(self.api_key_input)

        self.mode_combo.currentIndexChanged.connect(self._toggle_fields)
        self._toggle_fields()

        self.registerField("use_local", self.mode_combo, "currentData")

    def _toggle_fields(self):
        is_local = self.mode_combo.currentData() == "local"
        self.model_size_combo.setVisible(is_local)
        if self.model_size_label:
            self.model_size_label.setVisible(is_local)
        self.api_key_input.setVisible(not is_local)
        if self.api_key_label:
            self.api_key_label.setVisible(not is_local)

    def is_local(self) -> bool:
        return self.mode_combo.currentData() == "local"

    def nextId(self) -> int:
        return PAGE_DOWNLOAD if self.is_local() else PAGE_MIC


class DownloadWorker(threading.Thread):
    def __init__(self, model_size: str, on_done):
        super().__init__(daemon=True)
        self.model_size = model_size
        self.on_done = on_done

    def run(self):
        error = None
        try:
            from faster_whisper import WhisperModel

            WhisperModel(self.model_size, device="cpu", compute_type="int8")
        except Exception as e:  # noqa: BLE001 -- surfaced to the wizard, not raised
            error = str(e)
        self.on_done(error)


class DownloadPage(QWizardPage):
    download_finished = Signal(object)

    def __init__(self, mode_page: ModePage):
        super().__init__()
        self.mode_page = mode_page
        self.setTitle("Downloading Local Model")
        self._done = False
        self._error: Optional[str] = None

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Preparing to download...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setMaximum(0)  # indeterminate
        layout.addWidget(self.progress)

        self.download_finished.connect(self._on_finished)

    def initializePage(self):
        self._done = False
        self._error = None
        model_size = self.mode_page.model_size_combo.currentData() or "base"
        self.status_label.setText(
            f"Downloading the '{model_size}' model. This only happens once "
            "and may take a few minutes depending on your connection..."
        )
        self.progress.setMaximum(0)
        worker = DownloadWorker(model_size, self._emit_finished)
        worker.start()

    def _emit_finished(self, error: Optional[str]):
        self.download_finished.emit(error)

    @Slot(object)
    def _on_finished(self, error):
        self._done = True
        self._error = error
        if error:
            self.status_label.setText(
                f"Download failed: {error}\nYou can continue -- the model "
                "will be retried automatically on your first dictation."
            )
        else:
            self.status_label.setText("Model ready.")
        self.progress.setMaximum(1)
        self.progress.setValue(1)
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._done

    def nextId(self) -> int:
        return PAGE_MIC


class MicPage(QWizardPage):
    level_changed = Signal(float)

    def __init__(self):
        super().__init__()
        self.setTitle("Choose Your Microphone")
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.device_combo = QComboBox()
        self._populate_devices()
        form.addRow("Microphone:", self.device_combo)
        layout.addLayout(form)

        self.level_bar = QProgressBar()
        self.level_bar.setMinimum(0)
        self.level_bar.setMaximum(100)
        self.level_bar.setTextVisible(False)
        layout.addWidget(QLabel("Speak to see your input level:"))
        layout.addWidget(self.level_bar)

        self.registerField("device_index", self.device_combo, "currentData")

        self._stream: Optional[sd.InputStream] = None
        self.level_changed.connect(self.level_bar.setValue)
        self.device_combo.currentIndexChanged.connect(self._restart_stream)

    def _populate_devices(self):
        self.device_combo.addItem("Default", None)
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev["max_input_channels"] > 0:
                    self.device_combo.addItem(
                        f"{dev['name']} (API: {dev['hostapi']})", i
                    )
        except Exception:
            pass

    def initializePage(self):
        self._restart_stream()

    def _restart_stream(self):
        self._stop_stream()
        device = self.device_combo.currentData()

        def callback(indata, frames, time_info, status):
            level = float(np.sqrt(np.mean(indata**2))) if indata.size else 0.0
            self.level_changed.emit(min(100.0, level * 400))

        try:
            self._stream = sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                device=device,
                callback=callback,
            )
            self._stream.start()
        except Exception:
            self._stream = None

    def _stop_stream(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def cleanupPage(self):
        self._stop_stream()

    def nextId(self) -> int:
        return PAGE_HOTKEY


class HotkeyPage(QWizardPage):
    hotkey_detected = Signal()

    def __init__(self):
        super().__init__()
        self.setTitle("Test Your Global Hotkey")
        layout = QVBoxLayout(self)

        self.instructions = QLabel(
            "Press and hold <b>Ctrl + Win</b> anywhere (even outside this "
            "window) to confirm your hotkey works."
        )
        self.instructions.setWordWrap(True)
        layout.addWidget(self.instructions)

        self.status_label = QLabel("Waiting for hotkey press...")
        layout.addWidget(self.status_label)

        self._detected = False
        self._listener_stop = None
        self.hotkey_detected.connect(self._on_detected)

    def initializePage(self):
        self._detected = False
        self.status_label.setText("Waiting for hotkey press...")
        self._start_listener()

    def _start_listener(self):
        try:
            from scribe_dictation.ui.app import (
                _start_global_hotkey,
                _stop_global_hotkey,
            )

            self._stop_global_hotkey = _stop_global_hotkey
            _start_global_hotkey(self._on_press, lambda: None)
        except Exception:
            self.status_label.setText(
                "Couldn't start the hotkey listener here -- you can still "
                "try it once setup is finished."
            )

    @Slot()
    def _on_press(self):
        self.hotkey_detected.emit()

    @Slot()
    def _on_detected(self):
        if self._detected:
            return
        self._detected = True
        self.status_label.setText("Hotkey detected! ✓")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._detected

    def cleanupPage(self):
        try:
            from scribe_dictation.ui.app import _stop_global_hotkey

            _stop_global_hotkey()
        except Exception:
            pass

    def nextId(self) -> int:
        return PAGE_TRY_IT


class TryItPage(QWizardPage):
    transcription_done = Signal(str)

    def __init__(self, mode_page: ModePage, mic_page: MicPage, vocabulary_manager):
        super().__init__()
        self.mode_page = mode_page
        self.mic_page = mic_page
        self.vocabulary_manager = vocabulary_manager
        self.setTitle("Try It Out")

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Click Record, say something, then click Stop to transcribe.")
        )

        self.record_btn = QPushButton("\U0001f3a4 Record")
        self.record_btn.clicked.connect(self._toggle_record)
        layout.addWidget(self.record_btn)

        self.result_box = QPlainTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setPlaceholderText("Your transcription will appear here...")
        layout.addWidget(self.result_box)

        self._recorder = None
        self._recording = False
        self.transcription_done.connect(self._on_transcription_done)

    def _toggle_record(self):
        from scribe_dictation.audio.capture import AudioRecorder

        if not self._recording:
            device = self.mic_page.device_combo.currentData()
            self._recorder = AudioRecorder(device=device)
            self._recorder.start()
            self._recording = True
            self.record_btn.setText("⏹ Stop")
        else:
            wav_path = self._recorder.stop()
            self._recording = False
            self.record_btn.setText("\U0001f3a4 Record")
            self.result_box.setPlainText("Transcribing...")
            self._transcribe_async(wav_path)

    def _transcribe_async(self, wav_path: str):
        from scribe_dictation.transcribe.service import TranscribeService

        use_local = self.mode_page.is_local()
        model_size = self.mode_page.model_size_combo.currentData() or "base"
        api_key = self.mode_page.api_key_input.text().strip()

        def run():
            try:
                if use_local:
                    service = TranscribeService(
                        use_local=True,
                        local_model_size=model_size,
                        vocabulary_manager=self.vocabulary_manager,
                    )
                else:
                    service = TranscribeService(
                        use_local=False,
                        api_key=api_key,
                        vocabulary_manager=self.vocabulary_manager,
                    )
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(service.transcribe(wav_path))
                loop.close()
            except Exception as e:  # noqa: BLE001 -- surfaced in the wizard UI
                result = f"[Transcription failed: {e}]"
            self.transcription_done.emit(result)

        threading.Thread(target=run, daemon=True).start()

    @Slot(str)
    def _on_transcription_done(self, text: str):
        self.result_box.setPlainText(text or "(no speech detected)")


class OnboardingWizard(QWizard):
    """First-run setup wizard. Skippable at any step."""

    def __init__(
        self, vocabulary_manager: Optional[CustomVocabularyManager] = None, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Privacy Scribe Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoCancelButton, False)
        self.setButtonText(QWizard.WizardButton.CancelButton, "Skip Setup")
        self.setMinimumSize(520, 420)

        self.settings = QSettings(ORGANIZATION, APP_NAME)

        mode_page = ModePage()
        mic_page = MicPage()

        self.setPage(PAGE_WELCOME, WelcomePage())
        self.setPage(PAGE_MODE, mode_page)
        self.setPage(PAGE_DOWNLOAD, DownloadPage(mode_page))
        self.setPage(PAGE_MIC, mic_page)
        self.setPage(PAGE_HOTKEY, HotkeyPage())
        self.setPage(PAGE_TRY_IT, TryItPage(mode_page, mic_page, vocabulary_manager))
        self.setStartId(PAGE_WELCOME)

        self._mode_page = mode_page
        self._mic_page = mic_page

        self.finished.connect(self._on_finished)

    def _on_finished(self, result: int):
        self.settings.setValue(SETTINGS_FIRST_RUN_COMPLETE, "true")

        from scribe_dictation.ui.app import (
            SETTINGS_API_KEY,
            SETTINGS_DEVICE,
            SETTINGS_LOCAL_MODEL_SIZE,
            SETTINGS_USE_LOCAL,
        )

        if result == QWizard.DialogCode.Accepted:
            self.settings.setValue(
                SETTINGS_USE_LOCAL, "true" if self._mode_page.is_local() else "false"
            )
            if self._mode_page.is_local():
                self.settings.setValue(
                    SETTINGS_LOCAL_MODEL_SIZE,
                    self._mode_page.model_size_combo.currentData() or "base",
                )
            else:
                api_key = self._mode_page.api_key_input.text().strip()
                if api_key:
                    self.settings.setValue(SETTINGS_API_KEY, api_key)

            device = self._mic_page.device_combo.currentData()
            self.settings.setValue(
                SETTINGS_DEVICE, str(device) if device is not None else ""
            )

        self.settings.sync()


def should_show_onboarding(settings: Optional[QSettings] = None) -> bool:
    """Return True if the first-run wizard has not yet been completed."""
    settings = settings or QSettings(ORGANIZATION, APP_NAME)
    return settings.value(SETTINGS_FIRST_RUN_COMPLETE, "false") != "true"
