"""
PySide6 GUI application for scribe-dictation.

Main window with:
- Record/Stop toggle button
- Status bar (Idle / Recording... / Transcribing... / Done)
- Editable text display for transcribed output
- Copy to clipboard and Clear buttons
- Auto-paste after transcription (configurable)
- Global hotkey (Ctrl+Shift+D) to toggle recording from any app
- Settings dialog for microphone device, API key, and auto-paste toggle
- System tray icon with quick actions
- Ctrl+R keyboard shortcut to toggle recording
"""

import asyncio
import os
import sys
import threading
from typing import Optional

import pyperclip
from PySide6.QtCore import Q_ARG, QMetaObject, QSettings, Qt, Slot
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
    QStatusBar, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from scribe_dictation.audio.capture import AudioRecorder
from scribe_dictation.audio.devices import list_input_devices, resolve_device_index
from scribe_dictation.transcribe.service import TranscribeService

APP_NAME = "Scribe Dictation"
ORGANIZATION = "ScribeDictation"
SETTINGS_API_KEY = "api_key"
SETTINGS_DEVICE = "audio_device"
SETTINGS_AUTO_PASTE = "auto_paste"

# ── Global hotkey support ─────────────────────────────────────────────

_global_hotkey_listener = None


def _start_global_hotkey(callback):
    """Start a background thread listening for Ctrl+Shift+D global hotkey."""
    global _global_hotkey_listener

    if _global_hotkey_listener is not None:
        return

    try:
        from pynput import keyboard
    except ImportError:
        return

    COMBINATION = {keyboard.Key.ctrl, keyboard.Key.shift, keyboard.KeyCode.from_char("d")}
    current_keys = set()

    def on_press(key):
        current_keys.add(key)
        if COMBINATION.issubset(current_keys):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, callback)

    def on_release(key):
        try:
            current_keys.discard(key)
        except KeyError:
            pass

    _global_hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    _global_hotkey_listener.daemon = True
    _global_hotkey_listener.start()


def _stop_global_hotkey():
    """Stop the global hotkey listener."""
    global _global_hotkey_listener
    if _global_hotkey_listener is not None:
        _global_hotkey_listener.stop()
        _global_hotkey_listener = None


def _simulate_paste():
    """Simulate Ctrl+V (Windows) / Cmd+V (macOS) to paste into active window."""
    try:
        from pynput.keyboard import Controller, Key
        kb = Controller()
        mod = Key.cmd if sys.platform == "darwin" else Key.ctrl
        kb.press(mod)
        kb.press(KeyCode.from_vk(86))
        kb.release(KeyCode.from_vk(86))
        kb.release(mod)
    except Exception as e:
        print(f"Auto-paste failed: {e}")


def _copy_to_clipboard(text: str) -> bool:
    """Place ``text`` on the system clipboard.

    Uses PySide6's ``QGuiApplication.clipboard()`` (no extra dependency beyond
    the existing PySide6 requirement) and falls back to ``pyperclip`` if the Qt
    clipboard is unavailable. Returns ``True`` when the text was written.
    """
    try:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
            return True
    except Exception as e:  # pragma: no cover - defensive, depends on platform
        print(f"Qt clipboard write failed: {e}")

    try:
        pyperclip.copy(text)
        return True
    except Exception as e:  # pragma: no cover - defensive, depends on platform
        print(f"pyperclip clipboard write failed: {e}")
        return False


try:
    from pynput.keyboard import KeyCode as _KC
    KeyCode = _KC
except ImportError:
    class KeyCode:
        @staticmethod
        def from_vk(vk):
            return None


# ── Settings Dialog ────────────────────────────────────────────────────

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

        self.auto_paste_check = QCheckBox("Auto-paste after transcription")
        self.auto_paste_check.setChecked(
            self.settings.value(SETTINGS_AUTO_PASTE, "true") == "true"
        )
        layout.addRow(self.auto_paste_check)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

    def _populate_devices(self):
        # Persisted selection is a stable id ("name::hostapi"), not an index —
        # indices shift across runs and when devices are plugged/unplugged.
        saved_device = self.settings.value(SETTINGS_DEVICE, "")
        self.device_combo.addItem("Default", "")
        try:
            devices = list_input_devices()
            for dev in devices:
                self.device_combo.addItem(dev.display_name, dev.stable_id)
                if saved_device and dev.stable_id == saved_device:
                    self.device_combo.setCurrentIndex(self.device_combo.count() - 1)
        except Exception:
            pass

    def _save(self):
        self.settings.setValue(SETTINGS_API_KEY, self.api_key_input.text())
        stable_id = self.device_combo.currentData()
        self.settings.setValue(SETTINGS_DEVICE, stable_id or "")
        self.settings.setValue(SETTINGS_AUTO_PASTE, "true" if self.auto_paste_check.isChecked() else "false")
        self.accept()


class ScribeDictationWindow(QMainWindow):
    """Main application window for Scribe Dictation."""

    STATUS_IDLE = "Idle"
    STATUS_RECORDING = "Recording...  (Ctrl+Shift+D to stop)"
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
        self._setup_global_hotkey()
        self._setup_tray()
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
        self.copy_btn.clicked.connect(self._copy_to_clipboard_action)
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

    def _setup_global_hotkey(self):
        """Register Ctrl+Shift+D as a system-wide hotkey."""
        _start_global_hotkey(self._toggle_recording)

    def _setup_tray(self):
        """Create a system tray icon with quick actions."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_ComputerIcon
        ))
        self.tray_icon.setToolTip(APP_NAME)

        from PySide6.QtWidgets import QMenu
        menu = QMenu()

        toggle_action = menu.addAction("Toggle Recording")
        toggle_action.triggered.connect(self._toggle_recording)

        menu.addSeparator()

        show_action = menu.addAction("Show Window")
        show_action.triggered.connect(self.show)

        settings_action = menu.addAction("Settings...")
        settings_action.triggered.connect(self._open_settings)

        menu.addSeparator()

        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.close)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show()
            self.raise_()

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
        stable_id = self.settings.value(SETTINGS_DEVICE, "")
        # Resolve the persisted stable id to a *current* device index. If the
        # previously-selected device is no longer present (unplugged, driver
        # change, etc.), this returns None and we transparently fall back to
        # the system default input device instead of crashing.
        device = resolve_device_index(stable_id)

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

        # Always place the result on the clipboard so the user can paste with
        # Ctrl+V even when automatic pasting is disabled.
        if text.strip():
            _copy_to_clipboard(text)

            # Auto-paste (simulate Ctrl+V into the previously-active window) is
            # an optional, toggleable behaviour gated by the "auto_paste" setting.
            auto_paste = self.settings.value(SETTINGS_AUTO_PASTE, "true") == "true"
            if auto_paste:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(200, _simulate_paste)

    # ── Actions ───────────────────────────────────────────────────────

    def _copy_to_clipboard_action(self):
        text = self.text_display.toPlainText()
        if text.strip():
            _copy_to_clipboard(text)
            self._update_status("Copied!")

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
            f"Version 0.2.0<br><br>"
            f"A desktop dictation app using OpenAI Whisper API.<br><br>"
            f"Press <b>Ctrl+R</b> or <b>Ctrl+Shift+D</b> (global) to start/stop recording.<br>"
            f"Auto-paste is configurable in Settings.",
        )

    def closeEvent(self, event: QCloseEvent):
        if self._recorder and self._recorder.is_recording:
            try:
                self._recorder.stop()
            except RuntimeError:
                pass
        _stop_global_hotkey()
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
