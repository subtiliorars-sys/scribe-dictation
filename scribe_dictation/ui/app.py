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
import time
from typing import Optional

import pyperclip
from PySide6.QtCore import Q_ARG, QMetaObject, QSettings, Qt, Slot
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from scribe_dictation.audio.capture import AudioRecorder
from scribe_dictation.export import (
    Segment,
    TranscriptionResult,
    to_markdown,
    to_srt,
    to_txt,
)
from scribe_dictation.transcribe.service import TranscribeService
from scribe_dictation.ui.overlay import VoiceCapsule

APP_NAME = "Scribe Dictation"
ORGANIZATION = "ScribeDictation"
SETTINGS_API_KEY = "api_key"
SETTINGS_DEVICE = "audio_device"
SETTINGS_AUTO_PASTE = "auto_paste"
SETTINGS_USE_LOCAL = "use_local"
SETTINGS_LOCAL_MODEL_SIZE = "local_model_size"
SETTINGS_VOICE_LEARNING = "voice_learning_enabled"
SETTINGS_PLAY_SOUNDS = "play_sounds"

# ── Global hotkey support ─────────────────────────────────────────────

_global_hotkey_listener = None

# Default hotkey configuration - Ctrl+Win is the default, reliable non-text hotkey
DEFAULT_GLOBAL_HOTKEY = "Ctrl + Win"
SUPPORTED_HOTKEYS = [
    "Ctrl + Win",  # Default: modifier-only, no character output
    "Ctrl + Alt",  # Clean modifier pair
    "Ctrl + Shift",  # Clean modifier pair
    "Alt + Shift",  # Clean modifier pair
    "Ctrl + Space",  # Common dictation / trigger key
    "Shift + Space",  # Alternate space combination
    "F1",  # Dedicated Function Key
    "F8",  # Dedicated Function Key
    "F9",  # Dedicated Function Key
    "F10",  # Dedicated Function Key
    "F11",  # Dedicated Function Key
    "F12",  # Dedicated Function Key
    "Caps Lock",  # Single toggle key
]


# Pre-cached in-memory WAV byte buffers for instantaneous zero-latency playback
_TAPE_PRESS_WAV = None
_TAPE_RELEASE_WAV = None


def _get_tape_sounds():
    """Synthesize authentic, punchy tape-recorder physical button click/clunk sounds."""
    global _TAPE_PRESS_WAV, _TAPE_RELEASE_WAV
    if _TAPE_PRESS_WAV is not None and _TAPE_RELEASE_WAV is not None:
        return _TAPE_PRESS_WAV, _TAPE_RELEASE_WAV

    import io
    import math
    import random
    import struct
    import wave

    sample_rate = 44100
    rng = random.Random(42)

    def generate_wav(samples):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(sample_rate)
            raw = bytearray()
            for s in samples:
                val = int(max(-1.0, min(1.0, s)) * 32767)
                raw.extend(struct.pack("<h", val))
            f.writeframes(raw)
        return buf.getvalue()

    # ── Tape Button Press / Punch In (~85ms) ──────────────────────────
    # 1. Plastic switch pre-travel click (high freq 2800-4500Hz noise & snap)
    # 2. Heavy solenoid/tape head carrier latch (120-180Hz hollow punch)
    # 3. Metallic leaf-spring contact ring (950Hz resonance)
    dur_press = 0.085
    n_press = int(dur_press * sample_rate)
    press_samples = [0.0] * n_press
    for i in range(n_press):
        t = i / sample_rate
        # Transient snap
        snap_env = math.exp(-t * 180.0)
        snap_noise = (rng.random() * 2 - 1) * snap_env * 0.45
        snap_tone = math.sin(2 * math.pi * 3400 * t) * snap_env * 0.35

        # Solenoid / Head carrier thud punch (dual pitch drop 180Hz -> 85Hz)
        pitch = 180.0 * math.exp(-t * 25.0)
        thud_env = math.exp(-t * 38.0)
        thud = math.sin(2 * math.pi * pitch * t) * thud_env * 0.75

        # Metal casing resonance
        case_env = math.exp(-t * 60.0)
        case_res = math.sin(2 * math.pi * 920 * t) * case_env * 0.25

        press_samples[i] = snap_noise + snap_tone + thud + case_res

    # ── Tape Button Release / Punch Out (~95ms) ───────────────────────
    # 1. Mechanical spring unlock snap (quick high-pitch metallic click)
    # 2. Cassette spring pushback clunk (hollow chassis clack at 240Hz & 650Hz)
    dur_rel = 0.095
    n_rel = int(dur_rel * sample_rate)
    rel_samples = [0.0] * n_rel
    for i in range(n_rel):
        t = i / sample_rate
        snap_env = math.exp(-t * 220.0)
        snap_noise = (rng.random() * 2 - 1) * snap_env * 0.5
        snap_click = math.sin(2 * math.pi * 2600 * t) * snap_env * 0.4

        clunk_env = math.exp(-t * 32.0)
        clunk_low = math.sin(2 * math.pi * 140 * t) * clunk_env * 0.65
        chassis_body = math.sin(2 * math.pi * 620 * t) * math.exp(-t * 50.0) * 0.35

        rel_samples[i] = snap_noise + snap_click + clunk_low + chassis_body

    _TAPE_PRESS_WAV = generate_wav(press_samples)
    _TAPE_RELEASE_WAV = generate_wav(rel_samples)
    return _TAPE_PRESS_WAV, _TAPE_RELEASE_WAV


def _play_sound(start: bool):
    """Play tactile, authentic tape recorder punch on/off sound effect."""
    try:
        settings = QSettings(ORGANIZATION, APP_NAME)
        val = settings.value(SETTINGS_PLAY_SOUNDS, True)
        if isinstance(val, str) and val.lower() == "false":
            return
        elif isinstance(val, bool) and not val:
            return

        import sys

        if sys.platform == "win32":
            import winsound

            press_wav, rel_wav = _get_tape_sounds()
            data = press_wav if start else rel_wav
            winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_ASYNC)
    except Exception as e:
        print(f"Failed to play sound: {e}")


def _is_hotkey_match(hotkey_type, current_keys, key=None):
    """Check if the current key combination matches the configured hotkey."""
    from pynput import keyboard

    if hotkey_type == "Ctrl + Win":
        return keyboard.Key.ctrl in current_keys and keyboard.Key.cmd in current_keys
    elif hotkey_type == "Ctrl + Alt":
        return keyboard.Key.ctrl in current_keys and keyboard.Key.alt in current_keys
    elif hotkey_type == "Ctrl + Shift":
        return keyboard.Key.ctrl in current_keys and keyboard.Key.shift in current_keys
    elif hotkey_type == "Alt + Shift":
        return keyboard.Key.alt in current_keys and keyboard.Key.shift in current_keys
    elif hotkey_type == "Ctrl + Space":
        return keyboard.Key.ctrl in current_keys and keyboard.Key.space in current_keys
    elif hotkey_type == "Shift + Space":
        return keyboard.Key.shift in current_keys and keyboard.Key.space in current_keys
    elif hotkey_type == "Caps Lock":
        return key == keyboard.Key.caps_lock
    elif hotkey_type == "F1":
        return key == keyboard.Key.f1
    elif hotkey_type == "F8":
        return key == keyboard.Key.f8
    elif hotkey_type == "F9":
        return key == keyboard.Key.f9
    elif hotkey_type == "F10":
        return key == keyboard.Key.f10
    elif hotkey_type == "F11":
        return key == keyboard.Key.f11
    elif hotkey_type == "F12":
        return key == keyboard.Key.f12
    return False


def _start_global_hotkey(press_callback, release_callback):
    """Start a background thread listening for global hotkey (press/release)."""
    global _global_hotkey_listener

    _stop_global_hotkey()

    try:
        from pynput import keyboard
    except ImportError:
        return

    settings = QSettings(ORGANIZATION, APP_NAME)
    hotkey_type = settings.value("global_hotkey", DEFAULT_GLOBAL_HOTKEY)

    current_keys = set()
    is_triggered = False

    def on_press(key):
        nonlocal is_triggered
        normalized_key = key
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            normalized_key = keyboard.Key.ctrl
        elif key in (keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            normalized_key = keyboard.Key.cmd
        elif key in (keyboard.Key.alt_l, keyboard.Key.alt_r):
            normalized_key = keyboard.Key.alt
        elif key in (keyboard.Key.shift_l, keyboard.Key.shift_r):
            normalized_key = keyboard.Key.shift

        current_keys.add(normalized_key)

        if _is_hotkey_match(hotkey_type, current_keys, key):
            if not is_triggered:
                is_triggered = True
                if hasattr(press_callback, "__self__"):
                    from PySide6.QtCore import QMetaObject, Qt

                    QMetaObject.invokeMethod(
                        press_callback.__self__,
                        press_callback.__name__,
                        Qt.ConnectionType.QueuedConnection,
                    )
                else:
                    press_callback()

    def on_release(key):
        nonlocal is_triggered
        normalized_key = key
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            normalized_key = keyboard.Key.ctrl
        elif key in (keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            normalized_key = keyboard.Key.cmd
        elif key in (keyboard.Key.alt_l, keyboard.Key.alt_r):
            normalized_key = keyboard.Key.alt
        elif key in (keyboard.Key.shift_l, keyboard.Key.shift_r):
            normalized_key = keyboard.Key.shift

        # If a modifier key is released, also check if the hotkey trigger ended
        was_match = _is_hotkey_match(hotkey_type, current_keys, key)
        try:
            current_keys.discard(normalized_key)
        except KeyError:
            pass

        if is_triggered:
            # Trigger release if hotkey combination is no longer active
            now_match = _is_hotkey_match(hotkey_type, current_keys, None)
            if not now_match or was_match:
                is_triggered = False
                if hasattr(release_callback, "__self__"):
                    from PySide6.QtCore import QMetaObject, Qt

                    QMetaObject.invokeMethod(
                        release_callback.__self__,
                        release_callback.__name__,
                        Qt.ConnectionType.QueuedConnection,
                    )
                else:
                    release_callback()

    _global_hotkey_listener = keyboard.Listener(
        on_press=on_press, on_release=on_release
    )
    _global_hotkey_listener.daemon = True
    _global_hotkey_listener.start()


def _stop_global_hotkey():
    """Stop the global hotkey listener."""
    global _global_hotkey_listener
    if _global_hotkey_listener is not None:
        _global_hotkey_listener.stop()
        _global_hotkey_listener = None


_last_paste_time = 0.0


def _simulate_paste(target_hwnd: Optional[int] = None):
    """Simulate atomic Ctrl+V (Windows/Linux) / Cmd+V (macOS) to paste into active window."""
    global _last_paste_time
    import time

    now = time.monotonic()
    # Debounce paste simulation within 200ms
    if now - _last_paste_time < 0.2:
        return
    _last_paste_time = now

    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            # Win32 SendInput Structures
            INPUT_KEYBOARD = 1
            KEYEVENTF_KEYUP = 0x0002

            VK_SHIFT = 0x10
            VK_CONTROL = 0x11
            VK_MENU = 0x12  # Alt
            VK_LWIN = 0x5B
            VK_RWIN = 0x5C
            VK_V = 0x56

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
                ]

            class _INPUT_UNION(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]

            class INPUT(ctypes.Structure):
                _fields_ = [
                    ("type", wintypes.DWORD),
                    ("u", _INPUT_UNION),
                ]

            def make_key_input(vk, flags):
                inp = INPUT()
                inp.type = INPUT_KEYBOARD
                inp.u.ki.wVk = vk
                inp.u.ki.wScan = 0
                inp.u.ki.dwFlags = flags
                inp.u.ki.time = 0
                inp.u.ki.dwExtraInfo = None
                return inp

            # If target_hwnd is specified and valid, ensure it is restored to foreground
            if target_hwnd and user32.IsWindow(target_hwnd):
                user32.SetForegroundWindow(target_hwnd)
                user32.BringWindowToTop(target_hwnd)
                time.sleep(0.04)

            # 1. Clear any stuck modifier keys (Shift, Ctrl, Alt, Win)
            release_mods = [
                make_key_input(VK_SHIFT, KEYEVENTF_KEYUP),
                make_key_input(VK_CONTROL, KEYEVENTF_KEYUP),
                make_key_input(VK_MENU, KEYEVENTF_KEYUP),
                make_key_input(VK_LWIN, KEYEVENTF_KEYUP),
                make_key_input(VK_RWIN, KEYEVENTF_KEYUP),
            ]
            mod_array = (INPUT * len(release_mods))(*release_mods)
            user32.SendInput(len(release_mods), mod_array, ctypes.sizeof(INPUT))
            time.sleep(0.02)

            # 2. Fire clean atomic Ctrl+V down and up sequence via SendInput
            paste_seq = [
                make_key_input(VK_CONTROL, 0),
                make_key_input(VK_V, 0),
                make_key_input(VK_V, KEYEVENTF_KEYUP),
                make_key_input(VK_CONTROL, KEYEVENTF_KEYUP),
            ]
            paste_array = (INPUT * len(paste_seq))(*paste_seq)
            user32.SendInput(len(paste_seq), paste_array, ctypes.sizeof(INPUT))
            return

        from pynput.keyboard import Controller, Key

        kb = Controller()
        mod = Key.cmd if sys.platform == "darwin" else Key.ctrl
        kb.press(mod)
        kb.press("v")
        time.sleep(0.02)
        kb.release("v")
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

        # Mode Selection
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Local Engine - Offline", "local")
        self.mode_combo.addItem("Cloud API - Online", "api")
        use_local_saved = self.settings.value(SETTINGS_USE_LOCAL, "true") == "true"
        self.mode_combo.setCurrentIndex(0 if use_local_saved else 1)
        self.mode_combo.currentIndexChanged.connect(self._toggle_mode_fields)
        layout.addRow("Transcription Mode:", self.mode_combo)

        # API Key (for API mode)
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Enter API key...")
        saved_key = self.settings.value(SETTINGS_API_KEY, "")
        if saved_key:
            self.api_key_input.setText(saved_key)
        layout.addRow("API Key:", self.api_key_input)

        # Local Model Size (for Local mode)
        self.model_size_combo = QComboBox()
        for size in ["tiny", "base", "small", "medium", "large-v3"]:
            self.model_size_combo.addItem(size, size)
        saved_size = self.settings.value(SETTINGS_LOCAL_MODEL_SIZE, "base")
        self.model_size_combo.setCurrentText(saved_size)
        layout.addRow("Local Model Size:", self.model_size_combo)

        self.device_combo = QComboBox()
        self._populate_devices()
        layout.addRow("Microphone:", self.device_combo)

        self.auto_paste_check = QCheckBox("Auto-paste after transcription")
        self.auto_paste_check.setChecked(
            self.settings.value(SETTINGS_AUTO_PASTE, "true") == "true"
        )
        layout.addRow(self.auto_paste_check)

        self.play_sounds_check = QCheckBox("Play sound on start/stop recording")
        self.play_sounds_check.setChecked(
            self.settings.value(SETTINGS_PLAY_SOUNDS, "true") == "true"
        )
        layout.addRow(self.play_sounds_check)

        # Voice profile (Pro/Lifetime only) — learns the user's vocabulary
        # locally and biases future transcriptions toward it.
        from scribe_dictation.licensing import LicenseTier, get_active_license_tier

        tier = get_active_license_tier()
        self.voice_learning_check = QCheckBox(
            "Learn my vocabulary to improve accuracy"
            if tier.at_least(LicenseTier.PRO)
            else "Learn my vocabulary to improve accuracy (Pro/Lifetime)"
        )
        self.voice_learning_check.setChecked(
            tier.at_least(LicenseTier.PRO)
            and self.settings.value(SETTINGS_VOICE_LEARNING, "false") == "true"
        )
        self.voice_learning_check.setEnabled(tier.at_least(LicenseTier.PRO))
        self.voice_learning_check.setToolTip(
            "100% local: tracks distinctive words across your own dictations "
            "(names, jargon) and hints the model with them. Nothing leaves "
            "this machine."
            if tier.at_least(LicenseTier.PRO)
            else "Upgrade to Pro or Lifetime to unlock this feature."
        )
        layout.addRow(self.voice_learning_check)

        # Global Hotkey Selection
        self.hotkey_combo = QComboBox()
        for hk in SUPPORTED_HOTKEYS:
            self.hotkey_combo.addItem(hk, hk)
        saved_hotkey = self.settings.value("global_hotkey", DEFAULT_GLOBAL_HOTKEY)
        self.hotkey_combo.setCurrentText(saved_hotkey)
        layout.addRow("Global Hotkey:", self.hotkey_combo)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._save)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

        # Labels for toggling visibility
        self.api_key_label = layout.labelForField(self.api_key_input)
        self.model_size_label = layout.labelForField(self.model_size_combo)

        self._toggle_mode_fields()

    def _toggle_mode_fields(self):
        is_local = self.mode_combo.currentData() == "local"
        self.api_key_input.setVisible(not is_local)
        if self.api_key_label:
            self.api_key_label.setVisible(not is_local)
        self.model_size_combo.setVisible(is_local)
        if self.model_size_label:
            self.model_size_label.setVisible(is_local)

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
                    if saved_device and (
                        str(i) == saved_device or dev["name"] == saved_device
                    ):
                        self.device_combo.setCurrentIndex(self.device_combo.count() - 1)
        except Exception:
            pass

    def _save(self):
        use_local = self.mode_combo.currentData() == "local"
        self.settings.setValue(SETTINGS_USE_LOCAL, "true" if use_local else "false")
        self.settings.setValue(SETTINGS_API_KEY, self.api_key_input.text())
        self.settings.setValue(
            SETTINGS_LOCAL_MODEL_SIZE, self.model_size_combo.currentData()
        )

        device_id = self.device_combo.currentData()
        self.settings.setValue(
            SETTINGS_DEVICE, str(device_id) if device_id is not None else ""
        )
        self.settings.setValue(
            SETTINGS_VOICE_LEARNING,
            "true" if self.voice_learning_check.isChecked() else "false",
        )
        self.settings.setValue(
            SETTINGS_AUTO_PASTE,
            "true" if self.auto_paste_check.isChecked() else "false",
        )
        self.settings.setValue(
            SETTINGS_PLAY_SOUNDS,
            "true" if self.play_sounds_check.isChecked() else "false",
        )
        self.settings.setValue("global_hotkey", self.hotkey_combo.currentText())
        self.accept()


class ScribeDictationWindow(QMainWindow):
    """Main application window for Scribe Dictation."""

    STATUS_IDLE = "Idle"
    STATUS_RECORDING = "Recording...  (Ctrl+Win to stop)"
    STATUS_TRANSCRIBING = "Transcribing..."
    STATUS_DONE = "Done"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(480, 360)

        # Set Window Icon
        from PySide6.QtGui import QIcon

        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "resources", "icon.ico"
        )
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.settings = QSettings(ORGANIZATION, APP_NAME)
        self._recorder: Optional[AudioRecorder] = None
        self._transcriber: Optional[TranscribeService] = None

        # Segments accumulated across recordings in this session, used for
        # Export. Each recording becomes one timestamped segment, with start
        # measured from the first recording in the session.
        self._session_started_at: Optional[float] = None
        self._segments: list = []
        self._recording_started_at: Optional[float] = None

        self.capsule = VoiceCapsule()
        self._setup_ui()
        self._setup_shortcuts()
        self._setup_global_hotkey()
        self._setup_tray()
        self._setup_transcriber()
        self._update_hotkey_label()
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
        self.text_display.setReadOnly(True)
        self.text_display.setPlaceholderText("Transcribed text will appear here...")
        self.text_display.setMinimumHeight(180)
        layout.addWidget(self.text_display)

        # Button row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.record_btn = QPushButton("\U0001f3a4 Record")
        self.record_btn.setMinimumHeight(40)
        self.record_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.record_btn.clicked.connect(self._toggle_recording)
        btn_layout.addWidget(self.record_btn)

        self.copy_btn = QPushButton("\U0001f4cb Copy")
        self.copy_btn.clicked.connect(self._copy_to_clipboard_action)
        btn_layout.addWidget(self.copy_btn)

        self.clear_btn = QPushButton("\U0001f5d1 Clear")
        self.clear_btn.clicked.connect(self._clear_text)
        btn_layout.addWidget(self.clear_btn)

        layout.addLayout(btn_layout)

        # Hotkey Help Label
        from PySide6.QtWidgets import QLabel

        self.hotkey_label = QLabel()
        self.hotkey_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hotkey_label.setStyleSheet("color: #718096; font-size: 11px;")
        layout.addWidget(self.hotkey_label)

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

        export_action = QAction("&Export...", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self._export_transcription)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        help_menu.addSeparator()
        deactivate_action = QAction("Deactivate &Pro License...", self)
        deactivate_action.triggered.connect(self._deactivate_license)
        help_menu.addAction(deactivate_action)

    def _deactivate_license(self):
        reply = QMessageBox.question(
            self,
            "Deactivate License",
            "Are you sure you want to deactivate your Pro license on this computer? The app will close.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from scribe_dictation.licensing import deactivate_license

            deactivate_license()
            self.close()

    def _setup_shortcuts(self):
        shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        shortcut.activated.connect(self._toggle_recording)

    def _setup_global_hotkey(self):
        """Register system-wide hotkey."""
        self._recording_mode = None
        self._last_hotkey_press_time = 0.0
        _start_global_hotkey(
            self._on_global_hotkey_pressed, self._on_global_hotkey_released
        )

    def _update_hotkey_label(self):
        hotkey = self.settings.value("global_hotkey", DEFAULT_GLOBAL_HOTKEY)
        self.hotkey_label.setText(
            f"Global Hotkey: Hold <b>{hotkey}</b> to record, release to paste"
        )

    @Slot()
    def _on_global_hotkey_pressed(self):
        import time

        self._last_hotkey_press_time = time.time()

        # If already recording, ignore repeated on_press events from holding down keys
        if self._recorder and self._recorder.is_recording:
            return

        self._recording_mode = "HOLD"
        self._start_recording()

    @Slot()
    def _on_global_hotkey_released(self):
        # When hotkey is released, stop recording immediately
        if self._recorder and self._recorder.is_recording:
            self._stop_recording()
            self._recording_mode = None

    def _setup_tray(self):
        """Create a system tray icon with quick actions."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        from PySide6.QtGui import QIcon

        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "resources", "icon.ico"
        )
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            self.tray_icon.setIcon(
                self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon)
            )
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
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show()
            self.raise_()
            self.activateWindow()

    def _setup_transcriber(self):
        """Initialize the transcription service from settings or env."""
        use_local = self.settings.value(SETTINGS_USE_LOCAL, "true") == "true"
        local_model_size = self.settings.value(SETTINGS_LOCAL_MODEL_SIZE, "base")
        api_key = self.settings.value(SETTINGS_API_KEY, "") or os.environ.get(
            "OPENAI_API_KEY", ""
        )

        voice_profile = None
        if self.settings.value(SETTINGS_VOICE_LEARNING, "false") == "true":
            from scribe_dictation.licensing import LicenseTier, get_active_license_tier
            from scribe_dictation.transcribe.voice_profile import (
                VoiceProfile,
                default_profile_path,
            )

            tier = get_active_license_tier()
            if tier.at_least(LicenseTier.PRO):
                voice_profile = VoiceProfile(default_profile_path(), tier=tier)

        try:
            self._transcriber = TranscribeService(
                api_key=api_key,
                use_local=use_local,
                local_model_size=local_model_size,
                voice_profile=voice_profile,
            )
        except Exception as e:
            print(f"Failed to setup transcriber: {e}")
            self._transcriber = None

    # ── Status ────────────────────────────────────────────────────────

    def _get_recording_status_text(self) -> str:
        hotkey = self.settings.value("global_hotkey", DEFAULT_GLOBAL_HOTKEY)
        return f"Recording...  ({hotkey} to stop)"

    def _update_status(self, text: str):
        self.status_bar.showMessage(text)

    # ── Recording ─────────────────────────────────────────────────────

    def _toggle_recording(self):
        if self._recorder and self._recorder.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        if self._recorder and self._recorder.is_recording:
            return

        # Capture current foreground window before recording/overlay changes state
        self._target_hwnd = None
        if sys.platform == "win32":
            try:
                import ctypes

                fg = ctypes.windll.user32.GetForegroundWindow()
                scribe_hwnd = int(self.winId()) if self.isVisible() else 0
                capsule_hwnd = (
                    int(self.capsule.winId()) if self.capsule.isVisible() else 0
                )
                if fg and fg not in (scribe_hwnd, capsule_hwnd):
                    self._target_hwnd = fg
            except Exception:
                self._target_hwnd = None

        _play_sound(True)
        self.capsule.show_recording()
        device_str = self.settings.value(SETTINGS_DEVICE, "")
        device = int(device_str) if device_str and device_str != "None" else None

        if self._session_started_at is None:
            self._session_started_at = time.monotonic()
        self._recording_started_at = time.monotonic()

        self._recorder = AudioRecorder(device=device)
        self._recorder.start()

        self.record_btn.setText("\u23f9 Stop")
        self._update_status(self._get_recording_status_text())

        # Start background monitoring thread to feed live RMS levels to the visualizer
        self._meter_thread = threading.Thread(
            target=self._live_audio_meter_loop, daemon=True
        )
        self._meter_thread.start()

    def _live_audio_meter_loop(self):
        """Monitor recording for silence (in toggle mode) and feed live audio levels to the VoiceCapsule."""
        import time
        import numpy as np

        silence_duration = 1.5
        block_duration = 0.04
        blocks_for_silence = int(silence_duration / block_duration)
        silent_blocks = 0
        is_hold = getattr(self, "_recording_mode", None) == "HOLD"

        while self._recorder and self._recorder.is_recording:
            time.sleep(block_duration)
            if not self._recorder or not self._recorder.is_recording:
                break
            with self._recorder._lock:
                if not self._recorder._recording:
                    continue
                latest = self._recorder._recording[-1]
                level = float(np.sqrt(np.mean(latest**2))) if latest.size > 0 else 0.0

            # Feed live level to floating capsule
            self.capsule.update_audio_level(level)

            if not is_hold:
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

        self._recording_mode = None
        try:
            wav_path = self._recorder.stop()
        except RuntimeError:
            self.capsule.hide_capsule()
            self._reset_recording_ui()
            return

        _play_sound(False)
        self.capsule.show_transcribing()
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
                self.capsule.hide_capsule()
                self.text_display.appendPlainText(
                    "[Transcription failed: No API key configured. "
                    "Configure your API Key in Settings or select Local Mode.]"
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
                self,
                "_on_transcription_complete",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, result),
            )

        thread = threading.Thread(target=run_transcribe, daemon=True)
        thread.start()

    @Slot(str)
    def _on_transcription_complete(self, text: str):
        text = text.strip()
        if not text:
            self.capsule.hide_capsule()
            self._update_status(self.STATUS_IDLE)
            return

        self.capsule.show_done()
        self.text_display.appendPlainText(text)
        self._update_status(self.STATUS_DONE)

        # Record this recording as a timestamped segment (relative to the
        # start of the session) so it can be included in Export output.
        now = time.monotonic()
        session_start = self._session_started_at or now
        seg_start = (self._recording_started_at or now) - session_start
        seg_end = now - session_start
        self._segments.append(
            Segment(
                start=max(seg_start, 0.0),
                end=max(seg_end, seg_start, 0.0),
                text=text,
            )
        )

        # Copy to clipboard
        _copy_to_clipboard(text)

        # Auto-paste (simulate Ctrl+V into the target / active window)
        auto_paste = self.settings.value(SETTINGS_AUTO_PASTE, "true") == "true"
        if auto_paste:
            target_hwnd = getattr(self, "_target_hwnd", None)
            from PySide6.QtCore import QTimer

            QTimer.singleShot(150, lambda: _simulate_paste(target_hwnd))

    # ── Actions ───────────────────────────────────────────────────────

    def _copy_to_clipboard_action(self):
        text = self.text_display.toPlainText()
        if text.strip():
            _copy_to_clipboard(text)
            self._update_status("Copied!")

    def _clear_text(self):
        self.text_display.clear()
        self._segments = []
        self._session_started_at = None
        self._update_status(self.STATUS_IDLE)

    def _export_transcription(self):
        """Export the current transcription to .txt, .md, or .srt."""
        segments = list(self._segments)
        if not segments:
            # Fall back to whatever plain text is on screen (e.g. manually
            # edited), as a single zero-length segment, so Export still
            # works even if no recording has completed in this session.
            text = self.text_display.toPlainText()
            if not text.strip():
                QMessageBox.information(self, "Export", "Nothing to export yet.")
                return
            segments = [Segment(start=0.0, end=0.0, text=text)]

        result = TranscriptionResult(segments=segments)

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Transcription",
            "transcription.txt",
            "Plain Text (*.txt);;Markdown (*.md);;SubRip Subtitle (*.srt)",
        )
        if not path:
            return

        if path.endswith(".md") or "Markdown" in selected_filter:
            content = to_markdown(result)
        elif path.endswith(".srt") or "SubRip" in selected_filter:
            content = to_srt(result)
        else:
            content = to_txt(result)

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self._update_status(f"Exported to {path}")
        except OSError as e:
            QMessageBox.warning(self, "Export failed", f"Could not write file:\n{e}")

    def _open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self._setup_transcriber()
            _stop_global_hotkey()
            self._setup_global_hotkey()
            self._update_hotkey_label()

    def _show_about(self):
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b><br><br>"
            f"Version 0.2.0<br><br>"
            f"A desktop dictation app supporting local offline processing and OpenAI cloud API.<br><br>"
            f"Press <b>Ctrl+R</b> or the global shortcut to start/stop recording.<br>"
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

    # ── Licensing check ──
    from scribe_dictation.licensing import is_offline_cache_valid
    from scribe_dictation.ui.activation import ActivationDialog

    if not is_offline_cache_valid():
        activation = ActivationDialog()
        if activation.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)

    window = ScribeDictationWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
