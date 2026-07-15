"""
PySide6 GUI application for scribe-dictation.

Main window with:
- Record/Stop toggle button
- Status bar (Idle / Recording... / Transcribing... / Done)
- Editable text display for transcribed output
- Copy to clipboard and Clear buttons
- Settings dialog for microphone device and API key
- Ctrl+R keyboard shortcut to toggle recording
"""

import asyncio
import os
import sys
import threading
from typing import Optional

import pyperclip
from PySide6.QtCore import QMetaObject, QSettings, Qt, Slot
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
    QStatusBar, QVBoxLayout, QWidget,
)

from scribe_dictation.audio.capture import AudioRecorder
from scribe_dictation.transcribe.service import TranscribeService

APP_NAME = "Scribe Dictation"
ORGANIZATION = "ScribeDictation"
SETTINGS_API_KEY = "api_key"
SETTINGS_DEVICE = "audio_device"
class SettingsDialog(QDialog):
    """Dialog for configuring application settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Settings")
        self.setMinimumWidth(400)
        self.settings = QSettings(ORGANIZATION, APP_NAME)
        layout = QFormLayout(self)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("sk-...")
        saved_key = self.settings.value(SETTINGS_API_KEY, "")
        if saved_key:
            self.api_key_input.setText(saved_key)
        layout.addRow("OpenAI API Key:", self.api_key_input)

        self.device_combo = QComboBox()
        self._populate_devices()
        layout.addRow("Microphone:", self.device_combo)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

    def _populate_devices(self):
        import sounddevice as sd
        saved_device = self.settings.value(SETTINGS_DEVICE, "")
        self.device_combo.addItem("Default", None)
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev["max_input_channels"] > 0:
                    label = f"{dev['name']} (API: {dev['hostapi']})"
                    self.device_combo.addItem(label, i)
                    if saved_device and (str(i) == saved_device or dev["name"] == saved_device):
                        self.device_combo.setCurrentIndex(self.device_combo.count() - 1)
        except Exception:
            pass

    def _save(self):
        self.settings.setValue(SETTINGS_API_KEY, self.api_key_input.text())
        device_id = self.device_combo.currentData()
        self.settings.setValue(SETTINGS_DEVICE, str(device_id) if device_id is not None else "")
        self.accept()


class ScribeDictationWindow(QMainWindow):
    """Main application window for Scribe Dictation."""

    STATUS_IDLE = "Idle"
    STATUS_RECORDING = "Recording..."
    STATUS_TRANSCRIBING = "Transcribing..."
    STATUS_DONE = "Done"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(480, 360)

        self.settings = QSettings(ORGANIZATION, APP_NAME)
        self._recorder: Optional[AudioRecorder] = None
        self._transcriber: Optional[TranscribeService] = None

        self._setup_ui()
        self._setup_shortcuts()
        self._setup_transcriber()
        self._update_status(self.STATUS_IDLE)

    # ── UI Setup ──────────────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Text display area
        self.text_display = QPlainTextEdit()
        self.text_display.setPlaceholderText("Transcribed text will appear here...")
        self.text_display.setMinimumHeight(180)
        layout.addWidget(self.text_display)

        # Button row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.record_btn = QPushButton("\U0001f3a4 Record")
        self.record_btn.setMinimumHeight(40)
        self.record_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.record_btn.clicked.connect(self._toggle_recording)
        btn_layout.addWidget(self.record_btn)

        self.copy_btn = QPushButton("\U0001f4cb Copy")
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_layout.addWidget(self.copy_btn)

        self.clear_btn = QPushButton("\U0001f5d1 Clear")
        self.clear_btn.clicked.connect(self._clear_text)
        btn_layout.addWidget(self.clear_btn)

        layout.addLayout(btn_layout)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Menu bar
        self._setup_menu()

    def _setup_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")

        settings_action = QAction("&Settings...", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_shortcuts(self):
        shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        shortcut.activated.connect(self._toggle_recording)

    def _setup_transcriber(self):
        """Initialize the transcription service from settings or env."""
        api_key = self.settings.value(SETTINGS_API_KEY, "") or os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            try:
                self._transcriber = TranscribeService(api_key=api_key)
            except Exception:
                self._transcriber = None
        else:
            self._transcriber = None

    # ── Status ────────────────────────────────────────────────────────

    def _update_status(self, text: str):
        self.status_bar.showMessage(text)

    # ── Recording ─────────────────────────────────────────────────────

    def _toggle_recording(self):
        if self._recorder and self._recorder.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        device_str = self.settings.value(SETTINGS_DEVICE, "")
        device = int(device_str) if device_str and device_str != "None" else None

        self._recorder = AudioRecorder(device=device)
        self._recorder.start()

        self.record_btn.setText("\u23f9 Stop")
        self._update_status(self.STATUS_RECORDING)

        # Start silence-detection thread
        self._silence_thread = threading.Thread(target=self._auto_stop_loop, daemon=True)
        self._silence_thread.start()

    def _auto_stop_loop(self):
        """Monitor recording for silence and auto-stop after 1.5s."""
        import time
        import numpy as np

        silence_duration = 1.5
        block_duration = 0.1
        blocks_for_silence = int(silence_duration / block_duration)
        silent_blocks = 0

        while self._recorder and self._recorder.is_recording:
            time.sleep(block_duration)
            with self._recorder._lock:
                if not self._recorder._recording:
                    continue
                latest = self._recorder._recording[-1]
                level = float(np.sqrt(np.mean(latest ** 2))) if latest.size > 0 else 0.0

            if level < 0.01:  # SILENCE_THRESHOLD
                silent_blocks += 1
                if silent_blocks >= blocks_for_silence:
                    QMetaObject.invokeMethod(
                        self, "_stop_recording", Qt.ConnectionType.QueuedConnection
                    )
                    break
            else:
                silent_blocks = 0

    def _stop_recording(self):
        if not self._recorder or not self._recorder.is_recording:
            return

        try:
            wav_path = self._recorder.stop()
        except RuntimeError:
            self._reset_recording_ui()
            return

        self._reset_recording_ui()
        self._transcribe_async(wav_path)

    def _reset_recording_ui(self):
        self.record_btn.setText("\U0001f3a4 Record")

    # ── Transcription ─────────────────────────────────────────────────

    def _transcribe_async(self, wav_path: str):
        self._update_status(self.STATUS_TRANSCRIBING)

        if self._transcriber is None:
            self._setup_transcriber()
            if self._transcriber is None:
                self.text_display.appendPlainText(
                    "[Transcription failed: No API key configured. "
                    "Set OPENAI_API_KEY environment variable or configure in Settings.]"
                )
                self._update_status(self.STATUS_IDLE)
                return

        def run_transcribe():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self._transcriber.transcribe(wav_path))
                loop.close()
            except Exception as e:
                result = f"[Transcription error: {e}]"

            QMetaObject.invokeMethod(
                self, "_on_transcription_complete",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, result),
            )

        thread = threading.Thread(target=run_transcribe, daemon=True)
        thread.start()

    @Slot(str)
    def _on_transcription_complete(self, text: str):
        self.text_display.appendPlainText(text)
        self._update_status(self.STATUS_DONE)

    # ── Actions ───────────────────────────────────────────────────────

    def _copy_to_clipboard(self):
        text = self.text_display.toPlainText()
        if text.strip():
            pyperclip.copy(text)

    def _clear_text(self):
        self.text_display.clear()
        self._update_status(self.STATUS_IDLE)

    def _open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self._setup_transcriber()

    def _show_about(self):
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b><br><br>"
            f"Version 0.1.0<br><br>"
            f"A desktop dictation app using OpenAI Whisper API.<br><br>"
            f"Press <b>Ctrl+R</b> to start/stop recording.<br>"
            f"Audio is automatically transcribed when recording stops.",
        )

    def closeEvent(self, event: QCloseEvent):
        if self._recorder and self._recorder.is_recording:
            try:
                self._recorder.stop()
            except RuntimeError:
                pass
        event.accept()


def main():
    """Launch the Scribe Dictation application."""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION)

    window = ScribeDictationWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
