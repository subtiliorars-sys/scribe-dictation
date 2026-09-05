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
from datetime import date
from typing import Optional

import pyperclip
from PySide6.QtCore import Q_ARG, QMetaObject, QSettings, Qt, QUrl, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QGuiApplication,
    QKeySequence,
    QShortcut,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from scribe_dictation.audio.capture import AudioRecorder
from scribe_dictation.audio.sound_bank import (
    DEFAULT_SOUND_THEME,
    DEFAULT_SOUND_VOLUME,
    FREE_SOUND_THEMES,
    SETTINGS_SOUND_THEME,
    SETTINGS_SOUND_VOLUME,
    SOUND_THEMES,
    play_sound as _bank_play_sound,
    preview_sound as _bank_preview_sound,
)

from scribe_dictation.export import (
    Segment,
    TranscriptionResult,
    to_markdown,
    to_srt,
    to_txt,
)
from scribe_dictation.formatters import (
    BUILTIN_MODES,
    RAW_MODE,
    FormatEngine,
    get_mode_by_id,
    AppProfileManager,
    VerbalCommandParser,
    SETTINGS_VERBAL_COMMANDS_ENABLED,
    VoiceSnippetManager,
)
from scribe_dictation.licensing import deactivate_license, is_offline_cache_valid
from scribe_dictation.history.archive import TranscriptionArchive
from scribe_dictation.transcribe.languages import (
    LANGUAGES,
    TASK_TRANSCRIBE,
    TASK_TRANSLATE,
    get_language_by_code,
)
from scribe_dictation.transcribe.service import TranscribeService
from scribe_dictation.transcribe.vocabulary import CustomVocabularyManager
from scribe_dictation.tuning.diff_learner import DiffLearner
from scribe_dictation.ui.activation import ActivationDialog, BUY_URL
from scribe_dictation.ui.archive_dialog import ArchiveDialog
from scribe_dictation.ui.file_transcribe_dialog import FileTranscribeDialog
from scribe_dictation.ui.overlay import VoiceCapsule
from scribe_dictation.ui.profiles_dialog import ProfilesDialog
from scribe_dictation.ui.snippets_dialog import SnippetsDialog
from scribe_dictation.ui.transform_palette import (
    TransformPalette,
    grab_selected_text,
)
from scribe_dictation.ui.visualizer import AudioWaveformRibbon
from scribe_dictation.ui.xp_theme import (
    THEME_DEFAULT,
    THEME_LABELS,
    apply_theme,
)
from scribe_dictation.ui.vocabulary_dialog import VocabularyDialog
from scribe_dictation.transcribe.vocabulary import diff_corrections
from scribe_dictation.ui.voice_lab_dialog import VoiceLabDialog
from scribe_dictation.updater import (
    CURRENT_VERSION,
    fetch_latest_release_info,
    download_and_install_update,
)

APP_NAME = "Privacy Scribe"
ORGANIZATION = "PrivacyScribe"
SETTINGS_API_KEY = "api_key"
SETTINGS_DEVICE = "audio_device"
SETTINGS_AUTO_PASTE = "auto_paste"
SETTINGS_QUICK_REVIEW = "quick_review_toast"
SETTINGS_USE_LOCAL = "use_local"
SETTINGS_LOCAL_MODEL_SIZE = "local_model_size"
SETTINGS_PLAY_SOUNDS = "play_sounds"
SETTINGS_AUTO_UPDATE = "auto_update"
SETTINGS_HISTORY_LIMIT = "history_limit"
SETTINGS_SHOW_MENU_BAR = "show_menu_bar"
SETTINGS_FORMATTING_MODE = "formatting_mode"
SETTINGS_LANGUAGE = "transcription_language"
SETTINGS_TASK = "transcription_task"
SETTINGS_THEME = "app_theme"
DEFAULT_HISTORY_LIMIT = 1
SUPPORTED_HISTORY_LIMITS = [
    (1, "1 transcription (Default)"),
    (2, "Last 2 transcriptions"),
    (3, "Last 3 transcriptions"),
    (4, "Last 4 transcriptions"),
    (5, "Last 5 transcriptions"),
    (0, "Unlimited"),
]

# ── Free vs Pro Tier Limits ───────────────────────────────────────────
FREE_DAILY_DICTATION_LIMIT = 20
FREE_MAX_RECORDING_SECONDS = 10.0
FREE_ALLOWED_LOCAL_MODELS = ["base", "small"]
PRO_ALL_LOCAL_MODELS = ["tiny", "base", "small", "medium", "large-v3"]

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


def _play_sound(start: bool, is_pro: Optional[bool] = None):
    """Play the configured audio cue when starting or stopping recording."""
    _bank_play_sound(start, is_pro=is_pro)


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


def _is_transform_hotkey_match(current_keys, key=None):
    """Check if the current key combination matches the global text transform hotkey (Ctrl+Alt+T or Ctrl+Shift+T)."""
    from pynput import keyboard

    is_ctrl = keyboard.Key.ctrl in current_keys
    is_alt = keyboard.Key.alt in current_keys
    is_shift = keyboard.Key.shift in current_keys
    is_cmd = keyboard.Key.cmd in current_keys

    has_modifiers = (
        (is_ctrl and is_alt)
        or (is_ctrl and is_shift)
        or (is_cmd and is_alt)
        or (is_cmd and is_shift)
    )
    if not has_modifiers or key is None:
        return False

    if hasattr(key, "char") and key.char and key.char.lower() == "t":
        return True
    if hasattr(key, "vk") and key.vk in (0x54, 84):
        return True

    try:
        if key in (keyboard.KeyCode.from_char("t"), keyboard.KeyCode.from_char("T")):
            return True
    except Exception:
        pass
    return False


def _start_global_hotkey(press_callback, release_callback, transform_callback=None):
    """Start a background thread listening for global hotkey (press/release) and transform hotkey."""
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

        # Check transform shortcut (Ctrl+Alt+T or Ctrl+Shift+T)
        if transform_callback and _is_transform_hotkey_match(current_keys, key):
            if hasattr(transform_callback, "__self__"):
                from PySide6.QtCore import QMetaObject, Qt

                QMetaObject.invokeMethod(
                    transform_callback.__self__,
                    transform_callback.__name__,
                    Qt.ConnectionType.QueuedConnection,
                )
            else:
                transform_callback()
            return

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


def _restore_window_focus(target_hwnd: int) -> bool:
    """Forcefully restore focus to a target HWND on Windows, bypassing OS foreground lock restrictions."""
    if not target_hwnd or sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if not user32.IsWindow(target_hwnd):
            return False

        # If already foreground, we are good
        fg_hwnd = user32.GetForegroundWindow()
        if fg_hwnd == target_hwnd:
            return True

        current_thread_id = kernel32.GetCurrentThreadId()
        target_thread_id = user32.GetWindowThreadProcessId(target_hwnd, None)
        fg_thread_id = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0

        # Attach thread inputs to allow SetForegroundWindow without restriction
        attached_target = False
        attached_fg = False
        if target_thread_id and target_thread_id != current_thread_id:
            attached_target = bool(
                user32.AttachThreadInput(current_thread_id, target_thread_id, True)
            )
        if (
            fg_thread_id
            and fg_thread_id != current_thread_id
            and fg_thread_id != target_thread_id
        ):
            attached_fg = bool(
                user32.AttachThreadInput(current_thread_id, fg_thread_id, True)
            )

        # Windows bypass: send a simulated Alt keypress down/up to grant foreground rights
        VK_MENU = 0x12
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

        # Restore minimized window if needed
        SW_RESTORE = 9
        if user32.IsIconic(target_hwnd):
            user32.ShowWindow(target_hwnd, SW_RESTORE)

        user32.BringWindowToTop(target_hwnd)
        user32.SetForegroundWindow(target_hwnd)
        user32.SetFocus(target_hwnd)

        # Detach thread inputs
        if attached_target:
            user32.AttachThreadInput(current_thread_id, target_thread_id, False)
        if attached_fg:
            user32.AttachThreadInput(current_thread_id, fg_thread_id, False)

        return True
    except Exception as e:
        print(f"Failed to restore window focus: {e}")
        return False


_last_paste_time = 0.0


def _simulate_paste(target_hwnd: Optional[int] = None):
    """Simulate atomic Ctrl+V (Windows/Linux) / Cmd+V (macOS) to paste into active window."""
    global _last_paste_time
    import time

    now = time.monotonic()
    # Debounce paste simulation within 100ms
    if now - _last_paste_time < 0.1:
        return
    _last_paste_time = now

    try:
        if sys.platform == "win32":
            import ctypes

            user32 = ctypes.windll.user32

            # If target_hwnd is specified and valid, ensure it is restored to foreground
            if target_hwnd:
                _restore_window_focus(target_hwnd)
                time.sleep(0.08)

            VK_SHIFT = 0x10
            VK_CONTROL = 0x11
            VK_MENU = 0x12  # Alt
            VK_LWIN = 0x5B
            VK_RWIN = 0x5C
            VK_V = 0x56
            KEYEVENTF_KEYUP = 0x0002

            # 1. Release modifier keys
            for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN):
                user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.02)

            # 2. Fire clean Ctrl+V down and up sequence
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            time.sleep(0.01)
            user32.keybd_event(VK_V, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
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
        is_pro = is_offline_cache_valid()
        self.model_size_combo = QComboBox()
        if is_pro:
            for size, label in [
                ("tiny", "tiny (Ultra Fast)"),
                ("base", "base (Default)"),
                ("small", "small (Better Quality)"),
                ("medium", "medium (High Accuracy)"),
                ("large-v3", "large-v3 (Studio Grade)"),
            ]:
                self.model_size_combo.addItem(label, size)
        else:
            for size, label in [
                ("base", "base (Free Edition)"),
                ("small", "small (Free Edition)"),
                ("tiny", "tiny (🔒 Pro - Ultra Fast)"),
                ("medium", "medium (🔒 Pro - High Accuracy)"),
                ("large-v3", "large-v3 (🔒 Pro - Studio Grade)"),
            ]:
                self.model_size_combo.addItem(label, size)

        saved_size = self.settings.value(SETTINGS_LOCAL_MODEL_SIZE, "base")
        if not is_pro and saved_size not in FREE_ALLOWED_LOCAL_MODELS:
            saved_size = "base"
        idx = self.model_size_combo.findData(saved_size)
        if idx >= 0:
            self.model_size_combo.setCurrentIndex(idx)
        layout.addRow("Local Model Size:", self.model_size_combo)

        self.device_combo = QComboBox()
        self._populate_devices()
        layout.addRow("Microphone:", self.device_combo)

        self.auto_paste_check = QCheckBox("Auto-paste after transcription")
        self.auto_paste_check.setChecked(
            self.settings.value(SETTINGS_AUTO_PASTE, "true") == "true"
        )
        layout.addRow(self.auto_paste_check)

        self.quick_review_check = QCheckBox(
            "Show a quick review popup after auto-paste (helps the app learn corrections)"
        )
        self.quick_review_check.setChecked(
            self.settings.value(SETTINGS_QUICK_REVIEW, "true") == "true"
        )
        layout.addRow(self.quick_review_check)

        self.play_sounds_check = QCheckBox("Play sound on start/stop recording")
        self.play_sounds_check.setChecked(
            self.settings.value(SETTINGS_PLAY_SOUNDS, "true") == "true"
        )
        layout.addRow(self.play_sounds_check)

        # Sound Theme Selection with Live Audition Buttons
        sound_layout = QHBoxLayout()
        self.sound_theme_combo = QComboBox()
        self.sound_theme_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        combo_model = QStandardItemModel(self.sound_theme_combo)
        for theme_id, theme in SOUND_THEMES.items():
            locked = not is_pro and theme.tier != "free"
            if is_pro:
                label = f"{theme.name} ({theme.category})"
            else:
                if theme.tier == "free":
                    label = f"{theme.name} ({theme.category})"
                elif theme.tier == "basic":
                    label = f"{theme.name} (🔒 Basic - {theme.category})"
                else:
                    label = f"{theme.name} (🔒 Pro - {theme.category})"
            item = QStandardItem(label)
            item.setData(theme_id, Qt.ItemDataRole.UserRole)
            if locked:
                # Locked themes are shown for visibility but can't be selected,
                # since actual playback silently reverts them to the default
                # sound for non-Pro/Basic users — selecting one here used to
                # look like it worked (preview played it) but never played
                # during real recording.
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            combo_model.appendRow(item)
        self.sound_theme_combo.setModel(combo_model)

        saved_theme = self.settings.value(SETTINGS_SOUND_THEME, DEFAULT_SOUND_THEME)
        if not is_pro and saved_theme not in FREE_SOUND_THEMES:
            saved_theme = DEFAULT_SOUND_THEME
        idx = self.sound_theme_combo.findData(saved_theme)
        if idx >= 0:
            self.sound_theme_combo.setCurrentIndex(idx)

        self.btn_preview_start = QPushButton("▶ Test Start")
        self.btn_preview_start.setToolTip(
            "Play the sound that fires when recording starts"
        )
        self.btn_preview_start.setFixedHeight(24)
        self.btn_preview_start.clicked.connect(self._preview_start_sound)

        self.btn_preview_stop = QPushButton("■ Test Stop")
        self.btn_preview_stop.setToolTip(
            "Play the sound that fires when recording stops"
        )
        self.btn_preview_stop.setFixedHeight(24)
        self.btn_preview_stop.clicked.connect(self._preview_stop_sound)

        sound_layout.addWidget(self.sound_theme_combo)
        sound_layout.addWidget(self.btn_preview_start)
        sound_layout.addWidget(self.btn_preview_stop)
        layout.addRow("Sound Theme:", sound_layout)

        # Volume Slider
        volume_layout = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        try:
            saved_vol = int(
                self.settings.value(SETTINGS_SOUND_VOLUME, DEFAULT_SOUND_VOLUME)
            )
        except (ValueError, TypeError):
            saved_vol = DEFAULT_SOUND_VOLUME
        self.volume_slider.setValue(saved_vol)

        self.volume_label = QLabel(f"{saved_vol}%")
        self.volume_slider.valueChanged.connect(
            lambda v: self.volume_label.setText(f"{v}%")
        )

        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_label)
        layout.addRow("Sound Volume:", volume_layout)

        update_layout = QHBoxLayout()
        self.auto_update_check = QCheckBox(
            "Automatically download and install updates on startup"
        )
        self.auto_update_check.setChecked(
            self.settings.value(SETTINGS_AUTO_UPDATE, "true") == "true"
        )

        self.btn_check_updates = QPushButton("Check for Updates Now")
        self.btn_check_updates.clicked.connect(
            lambda: parent._check_for_updates_manual()
            if hasattr(parent, "_check_for_updates_manual")
            else None
        )

        update_layout.addWidget(self.auto_update_check)
        update_layout.addWidget(self.btn_check_updates)
        layout.addRow("Updates:", update_layout)
        # Global Hotkey Selection
        self.hotkey_combo = QComboBox()
        for hk in SUPPORTED_HOTKEYS:
            self.hotkey_combo.addItem(hk, hk)

        saved_hotkey = self.settings.value("global_hotkey", DEFAULT_GLOBAL_HOTKEY)
        self.hotkey_combo.setCurrentText(saved_hotkey)
        layout.addRow("Global Hotkey:", self.hotkey_combo)

        # History Limit Selection
        self.history_combo = QComboBox()
        for limit, label in SUPPORTED_HISTORY_LIMITS:
            self.history_combo.addItem(label, limit)
        saved_history = self.settings.value(
            SETTINGS_HISTORY_LIMIT, DEFAULT_HISTORY_LIMIT
        )
        try:
            saved_history = int(saved_history)
        except (ValueError, TypeError):
            saved_history = DEFAULT_HISTORY_LIMIT
        idx = self.history_combo.findData(saved_history)
        if idx >= 0:
            self.history_combo.setCurrentIndex(idx)
        layout.addRow("Transcription History:", self.history_combo)

        # Formatting Mode Selection
        self.mode_format_combo = QComboBox()
        for mode_key, mode_obj in BUILTIN_MODES.items():
            badge = "" if not mode_obj.is_pro else (" (Pro)" if not is_pro else "")
            self.mode_format_combo.addItem(f"{mode_obj.name}{badge}", mode_key)
        saved_format_mode = self.settings.value(SETTINGS_FORMATTING_MODE, "raw")
        idx = self.mode_format_combo.findData(saved_format_mode)
        if idx >= 0:
            self.mode_format_combo.setCurrentIndex(idx)
        layout.addRow("Formatting Mode:", self.mode_format_combo)

        # Language Selection
        self.language_combo = QComboBox()
        for lang in LANGUAGES:
            badge = ""
            if lang.code == "auto" and not is_pro:
                badge = " (Pro Lifetime Only)"
            self.language_combo.addItem(f"{lang.display_name}{badge}", lang.code)
        saved_lang = self.settings.value(SETTINGS_LANGUAGE, "auto" if is_pro else "en")
        lang_idx = self.language_combo.findData(saved_lang)
        if lang_idx >= 0:
            self.language_combo.setCurrentIndex(lang_idx)
        layout.addRow("Spoken Language:", self.language_combo)

        # Task Mode Selection (Transcribe vs Translate to English)
        self.task_combo = QComboBox()
        self.task_combo.addItem("Transcribe (Same Language)", TASK_TRANSCRIBE)
        trans_badge = "" if is_pro else " (Pro Lifetime Only)"
        self.task_combo.addItem(
            f"Translate (Speech ➔ English){trans_badge}", TASK_TRANSLATE
        )
        saved_task = self.settings.value(SETTINGS_TASK, TASK_TRANSCRIBE)
        task_idx = self.task_combo.findData(saved_task)
        if task_idx >= 0:
            self.task_combo.setCurrentIndex(task_idx)
        layout.addRow("Speech Task:", self.task_combo)

        self.verbal_commands_check = QCheckBox(
            "Enable verbal punctuation commands (e.g. 'new line', 'period', 'comma')"
        )
        self.verbal_commands_check.setChecked(
            self.settings.value(SETTINGS_VERBAL_COMMANDS_ENABLED, "true") == "true"
        )
        layout.addRow(self.verbal_commands_check)

        # Pro Vocabulary Button
        if (
            is_pro
            and hasattr(parent, "vocabulary_manager")
            and parent.vocabulary_manager
        ):
            vocab_btn = QPushButton("🔤 Manage Custom Vocabulary & Dictionary...")
            vocab_btn.clicked.connect(
                lambda: VocabularyDialog(parent.vocabulary_manager, self).exec()
            )
            layout.addRow(vocab_btn)

        # Pro App Profiles Button
        if is_pro and hasattr(parent, "profile_manager") and parent.profile_manager:
            profiles_btn = QPushButton("🎯 App Profiles & Smart Formatting...")
            profiles_btn.clicked.connect(
                lambda: ProfilesDialog(parent.profile_manager, self).exec()
            )
            layout.addRow(profiles_btn)

        # Pro Voice Snippets Button
        if is_pro and hasattr(parent, "snippet_manager") and parent.snippet_manager:
            snippets_btn = QPushButton("🗣️ Voice Snippets & Macros...")
            snippets_btn.clicked.connect(
                lambda: SnippetsDialog(parent.snippet_manager, self).exec()
            )
            layout.addRow(snippets_btn)

        self.show_menu_check = QCheckBox("Show top menu bar (Ctrl+M to toggle)")
        self.show_menu_check.setChecked(
            self.settings.value(SETTINGS_SHOW_MENU_BAR, "true") == "true"
        )
        layout.addRow(self.show_menu_check)

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

    def _preview_start_sound(self):
        theme_id = self.sound_theme_combo.currentData() or DEFAULT_SOUND_THEME
        volume = self.volume_slider.value() if hasattr(self, "volume_slider") else None
        _bank_preview_sound(theme_id, start=True, volume=volume)

    def _preview_stop_sound(self):
        theme_id = self.sound_theme_combo.currentData() or DEFAULT_SOUND_THEME
        volume = self.volume_slider.value() if hasattr(self, "volume_slider") else None
        _bank_preview_sound(theme_id, start=False, volume=volume)

    def _save(self):
        is_pro = is_offline_cache_valid()
        use_local = self.mode_combo.currentData() == "local"
        self.settings.setValue(SETTINGS_USE_LOCAL, "true" if use_local else "false")
        self.settings.setValue(SETTINGS_API_KEY, self.api_key_input.text())

        selected_model = self.model_size_combo.currentData()
        if not is_pro and selected_model not in FREE_ALLOWED_LOCAL_MODELS:
            QMessageBox.information(
                self,
                "Pro Feature",
                f"The '{selected_model}' model is exclusive to Privacy Scribe Pro.\n\n"
                "Free Edition includes 'base' and 'small'. Upgrade to Pro to unlock ultra-fast 'tiny', 'medium', and 'large-v3'.",
            )
            selected_model = "base"
        self.settings.setValue(SETTINGS_LOCAL_MODEL_SIZE, selected_model)

        device_id = self.device_combo.currentData()
        self.settings.setValue(
            SETTINGS_DEVICE, str(device_id) if device_id is not None else ""
        )
        self.settings.setValue(
            SETTINGS_AUTO_PASTE,
            "true" if self.auto_paste_check.isChecked() else "false",
        )
        self.settings.setValue(
            SETTINGS_QUICK_REVIEW,
            "true" if self.quick_review_check.isChecked() else "false",
        )
        self.settings.setValue(
            SETTINGS_PLAY_SOUNDS,
            "true" if self.play_sounds_check.isChecked() else "false",
        )
        selected_theme = self.sound_theme_combo.currentData()
        if not is_pro and selected_theme not in FREE_SOUND_THEMES:
            theme_obj = SOUND_THEMES.get(selected_theme)
            theme_name = theme_obj.name if theme_obj else selected_theme
            tier_name = "Pro" if (theme_obj and theme_obj.tier == "pro") else "Basic"
            QMessageBox.information(
                self,
                f"{tier_name} Sound Theme",
                f"The '{theme_name}' sound theme is exclusive to Privacy Scribe {tier_name}.\n\n"
                "Free Edition includes 3 core sounds (Classic Beep, Subtle Tick, Soft Chime).\n"
                "Upgrade to unlock the full acoustic library.\n\n"
                "Defaulting to Classic Beep & Boop.",
            )
            selected_theme = DEFAULT_SOUND_THEME
        self.settings.setValue(SETTINGS_SOUND_THEME, selected_theme)

        if hasattr(self, "volume_slider"):
            self.settings.setValue(SETTINGS_SOUND_VOLUME, self.volume_slider.value())

        self.settings.setValue(
            SETTINGS_AUTO_UPDATE,
            "true" if self.auto_update_check.isChecked() else "false",
        )

        self.settings.setValue("global_hotkey", self.hotkey_combo.currentText())
        self.settings.setValue(SETTINGS_HISTORY_LIMIT, self.history_combo.currentData())
        self.settings.setValue(
            SETTINGS_SHOW_MENU_BAR,
            "true" if self.show_menu_check.isChecked() else "false",
        )
        selected_format = self.mode_format_combo.currentData()
        if not is_pro and selected_format != "raw":
            selected_format = "raw"
        self.settings.setValue(SETTINGS_FORMATTING_MODE, selected_format)

        selected_lang = self.language_combo.currentData()
        if not is_pro and selected_lang == "auto":
            QMessageBox.information(
                self,
                "Pro Lifetime Feature",
                "Automatic Language Detection is exclusive to Privacy Scribe Pro Lifetime Edition.\n\n"
                "Free Edition supports explicit language selection (English, Spanish, French, German, Japanese, etc.). "
                "Defaulting to English.",
            )
            selected_lang = "en"
        self.settings.setValue(SETTINGS_LANGUAGE, selected_lang)

        selected_task = self.task_combo.currentData()
        if not is_pro and selected_task != TASK_TRANSCRIBE:
            QMessageBox.information(
                self,
                "Pro Lifetime Feature",
                "Speech Translation (translating foreign speech into English) is exclusive to Privacy Scribe Pro Lifetime Edition.\n\n"
                "Free Edition performs high-accuracy direct transcription in your chosen language.",
            )
            selected_task = TASK_TRANSCRIBE
        self.settings.setValue(SETTINGS_TASK, selected_task)
        self.settings.setValue(
            SETTINGS_VERBAL_COMMANDS_ENABLED,
            "true" if self.verbal_commands_check.isChecked() else "false",
        )
        self.accept()


class ScribeDictationWindow(QMainWindow):
    """Main application window for Scribe Dictation."""

    request_stop_recording = Signal()

    STATUS_IDLE = "Idle"
    STATUS_RECORDING = "Recording...  (Ctrl+Win to stop)"
    STATUS_TRANSCRIBING = "Transcribing..."
    STATUS_DONE = "Done"

    def __init__(self):
        super().__init__()
        self.request_stop_recording.connect(self._stop_recording)
        self.settings = QSettings(ORGANIZATION, APP_NAME)
        self.vocabulary_manager = CustomVocabularyManager(settings=self.settings)
        self.profile_manager = AppProfileManager(settings=self.settings)
        self.snippet_manager = VoiceSnippetManager(settings=self.settings)
        self.verbal_command_parser = VerbalCommandParser(settings=self.settings)
        self.archive = TranscriptionArchive()
        self.diff_learner = DiffLearner()
        self._last_raw_transcription: str = ""
        self._last_wav_path: Optional[str] = None
        self._recorder: Optional[AudioRecorder] = None
        self._transcriber: Optional[TranscribeService] = None

        # Transcription history buffer and limit
        self._history_limit: int = self._get_history_limit()
        self._transcription_history: list[str] = []

        # Segments accumulated across recordings in this session, used for
        # Export. Each recording becomes one timestamped segment, with start
        # measured from the first recording in the session.
        self._session_started_at: Optional[float] = None
        self._segments: list = []
        self._recording_started_at: Optional[float] = None
        self.transform_palette: Optional[TransformPalette] = None

        self.setMinimumSize(220, 75)
        self.resize(400, 220)
        self._update_window_title()
        self._update_app_icon()

        self.capsule = VoiceCapsule(is_pro=self._is_pro())
        self._setup_ui()
        self._setup_shortcuts()
        self._setup_global_hotkey()
        self._setup_tray()
        self._setup_transcriber()
        self._set_menu_bar_visible(self._is_menu_bar_visible())
        self._update_hotkey_label()
        self._update_status(self.STATUS_IDLE)

        if self.settings.value(SETTINGS_AUTO_UPDATE, "true") == "true":
            self._check_for_updates_background()

        import threading

        def check_local_model():
            try:
                from scribe_dictation.transcribe import LocalModelManager

                checked, msg = LocalModelManager.run_periodic_check(self.settings)
                if checked:
                    print(f"[Periodic Model Check] {msg}")
            except Exception as e:
                print(f"[Periodic Model Check Error] {e}")

        threading.Thread(target=check_local_model, daemon=True).start()

    def _is_menu_bar_visible(self) -> bool:
        return self.settings.value(SETTINGS_SHOW_MENU_BAR, "true") == "true"

    def _set_menu_bar_visible(self, visible: bool):
        self.settings.setValue(SETTINGS_SHOW_MENU_BAR, "true" if visible else "false")
        self.menuBar().setVisible(visible)
        if hasattr(self, "_toggle_menu_action"):
            self._toggle_menu_action.setChecked(visible)

    def _toggle_menu_bar(self):
        self._set_menu_bar_visible(not self._is_menu_bar_visible())

    def _set_theme(self, theme: str):
        self.settings.setValue(SETTINGS_THEME, theme)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)

    def _update_app_icon(self):
        from PySide6.QtGui import QIcon

        res_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
        icon_name = "icon_pro.ico" if self._is_pro() else "icon_free.ico"
        icon_path = os.path.join(res_dir, icon_name)
        if not os.path.exists(icon_path):
            icon_path = os.path.join(res_dir, "icon.ico")
        if os.path.exists(icon_path):
            q_icon = QIcon(icon_path)
            self.setWindowIcon(q_icon)
            if hasattr(self, "tray_icon") and self.tray_icon:
                self.tray_icon.setIcon(q_icon)

    def _is_pro(self) -> bool:
        return is_offline_cache_valid()

    def _get_daily_dictation_count(self) -> int:
        today = date.today().isoformat()
        saved_date = self.settings.value("daily_usage_date", "")
        if saved_date != today:
            return 0
        try:
            return int(self.settings.value("daily_usage_count", 0))
        except (ValueError, TypeError):
            return 0

    def _increment_daily_dictation_count(self) -> int:
        today = date.today().isoformat()
        saved_date = self.settings.value("daily_usage_date", "")
        count = 0 if saved_date != today else self._get_daily_dictation_count()
        count += 1
        self.settings.setValue("daily_usage_date", today)
        self.settings.setValue("daily_usage_count", count)
        return count

    def _get_remaining_daily_dictations(self) -> Optional[int]:
        if self._is_pro():
            return None
        return max(0, FREE_DAILY_DICTATION_LIMIT - self._get_daily_dictation_count())

    def _update_window_title(self):
        if self._is_pro():
            self.setWindowTitle(f"{APP_NAME} Pro")
        else:
            rem = self._get_remaining_daily_dictations()
            self.setWindowTitle(
                f"{APP_NAME} (Free: {rem}/{FREE_DAILY_DICTATION_LIMIT} today)"
            )

    def _show_daily_limit_modal(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Daily Limit Reached")
        msg.setText(
            f"<b>You've used all {FREE_DAILY_DICTATION_LIMIT} free dictations for today!</b><br><br>"
            "Upgrade to <b>Privacy Scribe Pro</b> to unlock:<br>"
            "• Unlimited daily voice dictations<br>"
            "• Ultra-fast 'tiny' and high-accuracy 'large-v3' models<br>"
            "• Unlimited recording clip lengths (no 10s cap)<br>"
            "• One-time payment ($9.99 / $29), no subscriptions forever."
        )
        upgrade_btn = msg.addButton(
            "⭐ Upgrade to Pro ($9.99)", QMessageBox.ButtonRole.AcceptRole
        )
        activate_btn = msg.addButton(
            "🔑 Enter License Key", QMessageBox.ButtonRole.ActionRole
        )
        msg.addButton(QMessageBox.StandardButton.Close)

        msg.exec()
        if msg.clickedButton() == upgrade_btn:
            self._open_buy_url()
        elif msg.clickedButton() == activate_btn:
            self._open_activation()

    def _get_history_limit(self) -> int:
        val = self.settings.value(SETTINGS_HISTORY_LIMIT, DEFAULT_HISTORY_LIMIT)
        try:
            limit = int(val)
            if limit in [lim for lim, _ in SUPPORTED_HISTORY_LIMITS]:
                return limit
            return DEFAULT_HISTORY_LIMIT
        except (ValueError, TypeError):
            return DEFAULT_HISTORY_LIMIT

    def _set_history_limit(self, limit: int):
        self._history_limit = limit
        self.settings.setValue(SETTINGS_HISTORY_LIMIT, limit)
        self._update_history_menu_actions()
        if (
            self._history_limit > 0
            and len(self._transcription_history) > self._history_limit
        ):
            self._transcription_history = self._transcription_history[
                -self._history_limit :
            ]
            self._segments = self._segments[-self._history_limit :]
            self.text_display.setPlainText("\n\n".join(self._transcription_history))

    def _update_history_menu_actions(self):
        if (
            hasattr(self, "_history_actions")
            and self._history_limit in self._history_actions
        ):
            self._history_actions[self._history_limit].setChecked(True)

    # ── UI Setup ──────────────────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(4)

        # Text display area
        self.text_display = QPlainTextEdit()
        self.text_display.setPlaceholderText("Transcribed text will appear here...")
        self.text_display.setMinimumHeight(24)
        self.text_display.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.text_display.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.text_display)

        # Button row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        self.record_btn = QPushButton("\U0001f3a4 Record")
        self.record_btn.setMinimumHeight(26)
        self.record_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.record_btn.clicked.connect(self._toggle_recording)
        btn_layout.addWidget(self.record_btn)

        # Embedded live audio waveform ribbon
        self.visualizer_ribbon = AudioWaveformRibbon(
            self, num_points=28, is_pro=self._is_pro()
        )
        self.visualizer_ribbon.setMinimumWidth(80)
        self.visualizer_ribbon.setFixedHeight(24)
        self.visualizer_ribbon.set_active(False)
        self.visualizer_ribbon.setVisible(False)
        btn_layout.addWidget(self.visualizer_ribbon)

        self.copy_btn = QPushButton("\U0001f4cb Copy")
        self.copy_btn.setMinimumHeight(26)
        self.copy_btn.clicked.connect(self._copy_to_clipboard_action)
        btn_layout.addWidget(self.copy_btn)

        self.clear_btn = QPushButton("\U0001f5d1 Clear")
        self.clear_btn.setMinimumHeight(26)
        self.clear_btn.clicked.connect(self._clear_text)
        btn_layout.addWidget(self.clear_btn)

        layout.addLayout(btn_layout)

        # Hotkey Help Label
        from PySide6.QtWidgets import QLabel

        self.hotkey_label = QLabel()
        self.hotkey_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hotkey_label.setStyleSheet("color: #718096; font-size: 10px;")
        layout.addWidget(self.hotkey_label)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Menu bar
        self._setup_menu()

    def _show_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)

        show_menu_act = menu.addAction("Show Menu Bar (Ctrl+M)")
        show_menu_act.setCheckable(True)
        show_menu_act.setChecked(self._is_menu_bar_visible())
        show_menu_act.triggered.connect(self._toggle_menu_bar)

        menu.addSeparator()

        copy_act = menu.addAction("Copy (Ctrl+C)")
        copy_act.triggered.connect(self._copy_to_clipboard_action)

        clear_act = menu.addAction("Clear History")
        clear_act.triggered.connect(self._clear_text)

        menu.addSeparator()

        settings_act = menu.addAction("Settings... (Ctrl+,)")
        settings_act.triggered.connect(self._open_settings)

        export_act = menu.addAction("Export... (Ctrl+E)")
        export_act.triggered.connect(self._export_transcription)

        menu.exec(self.text_display.mapToGlobal(pos))

    def _setup_menu(self):
        menu_bar = self.menuBar()
        menu_bar.clear()
        is_pro = self._is_pro()

        # File Menu
        file_menu = menu_bar.addMenu("&File")

        if is_pro:
            transcribe_file_action = QAction("Transcribe &Audio File...", self)
            transcribe_file_action.setShortcut(QKeySequence("Ctrl+O"))
            transcribe_file_action.triggered.connect(self._open_file_transcribe_dialog)
            file_menu.addAction(transcribe_file_action)
            file_menu.addSeparator()

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

        # Mode Menu (Pro Only)
        if is_pro:
            mode_menu = menu_bar.addMenu("&Mode")
            self._mode_action_group = QActionGroup(self)
            self._mode_action_group.setExclusive(True)
            current_mode = self.settings.value(SETTINGS_FORMATTING_MODE, "raw")

            for mode_key, mode_obj in BUILTIN_MODES.items():
                action = QAction(f"{mode_obj.name}", self)
                action.setCheckable(True)
                if mode_key == current_mode:
                    action.setChecked(True)
                action.triggered.connect(
                    lambda checked=False, k=mode_key: self._set_formatting_mode(k)
                )
                self._mode_action_group.addAction(action)
                mode_menu.addAction(action)

        # Tools Menu (Pro Only)
        if is_pro:
            tools_menu = menu_bar.addMenu("&Tools")

            transform_action = QAction("✨ &Transform Selected Text...", self)
            transform_action.setShortcut(QKeySequence("Ctrl+Alt+T"))
            transform_action.triggered.connect(lambda: self._open_transform_palette())
            tools_menu.addAction(transform_action)
            tools_menu.addSeparator()

            profiles_action = QAction("🎯 &App Profiles & Smart Detection...", self)
            profiles_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
            profiles_action.triggered.connect(self._open_profiles_dialog)
            tools_menu.addAction(profiles_action)

            snippets_action = QAction("🗣️ Voice &Snippets & Macros...", self)
            snippets_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
            snippets_action.triggered.connect(self._open_snippets_dialog)
            tools_menu.addAction(snippets_action)

            vocab_action = QAction("Custom &Vocabulary & Dictionary...", self)
            vocab_action.setShortcut(QKeySequence("Ctrl+Shift+V"))
            vocab_action.triggered.connect(self._open_vocabulary_dialog)
            tools_menu.addAction(vocab_action)

            voice_lab_action = QAction("🎓 Voice &Calibration & Accuracy Lab...", self)
            voice_lab_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
            voice_lab_action.triggered.connect(self._open_voice_lab_dialog)
            tools_menu.addAction(voice_lab_action)

            tools_menu.addSeparator()
            archive_action = QAction("🗄️ Search Audio &Archive & History...", self)
            archive_action.setShortcut(QKeySequence("Ctrl+H"))
            archive_action.triggered.connect(self._open_archive_dialog)
            tools_menu.addAction(archive_action)

        # View Menu
        view_menu = menu_bar.addMenu("&View")
        self._toggle_menu_action = QAction("Show &Menu Bar", self)
        self._toggle_menu_action.setCheckable(True)
        self._toggle_menu_action.setShortcut(QKeySequence("Ctrl+M"))
        self._toggle_menu_action.setChecked(self._is_menu_bar_visible())
        self._toggle_menu_action.triggered.connect(self._toggle_menu_bar)
        view_menu.addAction(self._toggle_menu_action)

        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("&Theme")
        self._theme_action_group = QActionGroup(self)
        self._theme_action_group.setExclusive(True)
        current_theme = self.settings.value(SETTINGS_THEME, THEME_DEFAULT)

        for theme_key, theme_label in THEME_LABELS.items():
            action = QAction(theme_label, self)
            action.setCheckable(True)
            if theme_key == current_theme:
                action.setChecked(True)
            action.triggered.connect(
                lambda checked=False, t=theme_key: self._set_theme(t)
            )
            self._theme_action_group.addAction(action)
            theme_menu.addAction(action)

        # History Menu
        history_menu = menu_bar.addMenu("&History")
        self._history_action_group = QActionGroup(self)
        self._history_action_group.setExclusive(True)
        self._history_actions = {}

        for limit, label in SUPPORTED_HISTORY_LIMITS:
            action = QAction(label, self)
            action.setCheckable(True)
            if limit == self._history_limit:
                action.setChecked(True)
            action.triggered.connect(
                lambda checked=False, lim=limit: self._set_history_limit(lim)
            )
            self._history_action_group.addAction(action)
            history_menu.addAction(action)
            self._history_actions[limit] = action

        history_menu.addSeparator()
        if is_pro:
            open_archive_act = QAction(
                "🗄️ Open Searchable Audio &Archive (Ctrl+H)...", self
            )
            open_archive_act.triggered.connect(self._open_archive_dialog)
            history_menu.addAction(open_archive_act)
            history_menu.addSeparator()

        clear_history_action = QAction("&Clear Transcription History", self)
        clear_history_action.triggered.connect(self._clear_text)
        history_menu.addAction(clear_history_action)

        # Help Menu
        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        check_updates_action = QAction("🔄 Check for &Updates...", self)
        check_updates_action.triggered.connect(self._check_for_updates_manual)
        help_menu.addAction(check_updates_action)

        setup_tutorial_action = QAction("🧭 Setup &Tutorial...", self)
        setup_tutorial_action.triggered.connect(self._open_onboarding_wizard)
        help_menu.addAction(setup_tutorial_action)

        help_menu.addSeparator()
        if self._is_pro():
            deactivate_action = QAction("Deactivate &Pro License...", self)
            deactivate_action.triggered.connect(self._deactivate_license)
            help_menu.addAction(deactivate_action)
        else:
            upgrade_action = QAction("⭐ Upgrade to &Pro ($9.99)...", self)
            upgrade_action.triggered.connect(self._open_buy_url)
            help_menu.addAction(upgrade_action)

            activate_action = QAction("🔑 &Activate Pro License...", self)
            activate_action.triggered.connect(self._open_activation)
            help_menu.addAction(activate_action)

    def _check_for_updates_background(self):
        """Silently check for GitHub releases in a background daemon thread."""

        def worker():
            info = fetch_latest_release_info(timeout=4.0)
            if info:
                QMetaObject.invokeMethod(
                    self,
                    "_prompt_update_available",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, info.get("tag_name", "")),
                    Q_ARG(str, info.get("html_url", "")),
                    Q_ARG(str, info.get("download_url", "")),
                    Q_ARG(bool, True),
                )

        threading.Thread(target=worker, daemon=True).start()

    @Slot(str, str, str, bool)
    def _prompt_update_available(
        self, tag_name: str, url: str, download_url: str, is_auto: bool = False
    ):
        """Prompt user when a new release is detected or auto-install if configured."""
        if download_url and getattr(sys, "frozen", False):
            auto_install = (
                is_auto and self.settings.value(SETTINGS_AUTO_UPDATE, "true") == "true"
            )

            if auto_install:
                reply = QMessageBox.StandardButton.Yes
            else:
                reply = QMessageBox.information(
                    self,
                    "Update Available",
                    f"🎉 A new version of Privacy Scribe ({tag_name}) is available!\n\n"
                    "Would you like to download and install it now? The app will restart automatically.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )

            if reply == QMessageBox.StandardButton.Yes:
                self._update_status("Downloading update...")

                def download_worker():
                    success = download_and_install_update(download_url)
                    if success:
                        QMetaObject.invokeMethod(
                            QApplication.instance(),
                            "quit",
                            Qt.ConnectionType.QueuedConnection,
                        )
                    else:
                        QMetaObject.invokeMethod(
                            self,
                            "_update_status",
                            Qt.ConnectionType.QueuedConnection,
                            Q_ARG(str, "Update failed."),
                        )

                threading.Thread(target=download_worker, daemon=True).start()
        else:
            # Fallback for source code mode or no direct asset
            if not is_auto:
                reply = QMessageBox.information(
                    self,
                    "Update Available",
                    f"🎉 A new version of Privacy Scribe ({tag_name}) is available!\n\n"
                    "Would you like to open the download page to update now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    QDesktopServices.openUrl(QUrl(url))

    def _check_for_updates_manual(self):
        """Manual update check triggered by user."""
        self._update_status("Checking for updates...")

        def worker():
            info = fetch_latest_release_info(timeout=5.0)
            if info:
                QMetaObject.invokeMethod(
                    self,
                    "_prompt_update_available",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, info.get("tag_name", "")),
                    Q_ARG(str, info.get("html_url", "")),
                    Q_ARG(str, info.get("download_url", "")),
                    Q_ARG(bool, False),
                )
            else:
                QMetaObject.invokeMethod(
                    self,
                    "_show_up_to_date_message",
                    Qt.ConnectionType.QueuedConnection,
                )

        threading.Thread(target=worker, daemon=True).start()

    @Slot()
    def _show_up_to_date_message(self):
        QMessageBox.information(
            self,
            "You're Up to Date",
            f"Privacy Scribe v{CURRENT_VERSION} is currently the latest version.",
        )
        self._update_status("Privacy Scribe is up to date.")

    def _open_profiles_dialog(self):
        dialog = ProfilesDialog(self.profile_manager, self)
        dialog.exec()

    def _open_snippets_dialog(self):
        dialog = SnippetsDialog(self.snippet_manager, self)
        dialog.exec()

    def _open_vocabulary_dialog(self):
        dialog = VocabularyDialog(self.vocabulary_manager, self)
        dialog.exec()
        self._setup_transcriber()

    def _open_voice_lab_dialog(self):
        dialog = VoiceLabDialog(self)
        dialog.exec()

    def _open_archive_dialog(self):
        dialog = ArchiveDialog(self.archive, self)
        dialog.exec()

    def _open_file_transcribe_dialog(self):
        if self._transcriber is None:
            self._setup_transcriber()
        dialog = FileTranscribeDialog(self._transcriber, self)
        dialog.exec()

    def _get_format_engine(self) -> FormatEngine:
        """Create or return a configured FormatEngine instance."""
        api_key = self.settings.value(SETTINGS_API_KEY, "") or os.environ.get(
            "OPENAI_API_KEY", ""
        )
        return FormatEngine(
            api_key=api_key,
            verbal_command_parser=getattr(self, "verbal_command_parser", None),
        )

    @Slot()
    def _open_transform_palette(self, text: Optional[str] = None):
        """Open the Global Transform Selected Text Quick Action Palette."""
        target_hwnd = None
        if sys.platform == "win32":
            try:
                import ctypes

                target_hwnd = ctypes.windll.user32.GetForegroundWindow()
            except Exception:
                target_hwnd = None

        grabbed_text = ""
        if text is None:
            grabbed_text = grab_selected_text(target_hwnd=target_hwnd)
        else:
            grabbed_text = text

        if self.transform_palette is None:
            self.transform_palette = TransformPalette(
                format_engine=self._get_format_engine(),
                target_hwnd=target_hwnd,
                initial_text=grabbed_text,
                is_pro=self._is_pro(),
            )
        else:
            self.transform_palette.format_engine = self._get_format_engine()
            self.transform_palette.set_target_hwnd(target_hwnd)
            self.transform_palette.is_pro = self._is_pro()
            self.transform_palette.set_text(grabbed_text)

        self.transform_palette.position_near_cursor()
        self.transform_palette.show()
        self.transform_palette.raise_()
        self.transform_palette.activateWindow()

    def _set_formatting_mode(self, mode_id: str):
        self.settings.setValue(SETTINGS_FORMATTING_MODE, mode_id)
        mode = get_mode_by_id(mode_id)
        mode_name = mode.name if mode else mode_id
        self._update_status(f"Mode set to: {mode_name}")

    def _set_language_code(self, lang_code: str):
        self.settings.setValue(SETTINGS_LANGUAGE, lang_code)
        self._setup_transcriber()
        lang = get_language_by_code(lang_code)
        self._update_status(f"Language set to: {lang.display_name}")

    def _set_speech_task(self, task: str):
        self.settings.setValue(SETTINGS_TASK, task)
        self._setup_transcriber()
        task_label = (
            "Translation (➔ English)" if task == TASK_TRANSLATE else "Transcription"
        )
        self._update_status(f"Speech task set to: {task_label}")

    def _open_buy_url(self):
        QDesktopServices.openUrl(QUrl(BUY_URL))

    def _open_activation(self):
        dialog = ActivationDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._setup_transcriber()
            self._update_window_title()
            self._update_app_icon()
            self._setup_menu()
            self._set_menu_bar_visible(self._is_menu_bar_visible())
            if hasattr(self, "capsule"):
                self.capsule.set_pro_mode(True)
            if hasattr(self, "visualizer_ribbon"):
                self.visualizer_ribbon.set_pro_mode(True)
            self._update_status("Pro License Activated! All features unlocked.")
            QMessageBox.information(
                self,
                "Pro License Activated",
                "🎉 Thank you for upgrading to Privacy Scribe Pro!\n\n"
                "All restrictions have been removed. You now have unlimited daily dictations, all model sizes unlocked, and unlimited recording lengths.",
            )

    def _deactivate_license(self):
        reply = QMessageBox.question(
            self,
            "Deactivate License",
            "Are you sure you want to deactivate your Pro license on this computer? The app will switch back to Free Edition.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            deactivate_license()
            self._setup_transcriber()
            self._update_window_title()
            self._update_app_icon()
            self._setup_menu()
            self._set_menu_bar_visible(self._is_menu_bar_visible())
            if hasattr(self, "capsule"):
                self.capsule.set_pro_mode(False)
            if hasattr(self, "visualizer_ribbon"):
                self.visualizer_ribbon.set_pro_mode(False)
            self._update_status("Switched to Free Edition.")

    def _setup_shortcuts(self):
        shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        shortcut.activated.connect(self._toggle_recording)

        menu_toggle_shortcut = QShortcut(QKeySequence("Ctrl+M"), self)
        menu_toggle_shortcut.activated.connect(self._toggle_menu_bar)

        alt_m_shortcut = QShortcut(QKeySequence("Alt+M"), self)
        alt_m_shortcut.activated.connect(self._toggle_menu_bar)

        transform_shortcut = QShortcut(QKeySequence("Ctrl+Alt+T"), self)
        transform_shortcut.activated.connect(self._open_transform_palette)

        transform_shortcut_shift = QShortcut(QKeySequence("Ctrl+Shift+T"), self)
        transform_shortcut_shift.activated.connect(self._open_transform_palette)

        if self._is_pro():
            file_shortcut = QShortcut(QKeySequence("Ctrl+O"), self)
            file_shortcut.activated.connect(self._open_file_transcribe_dialog)

            vocab_shortcut = QShortcut(QKeySequence("Ctrl+Shift+V"), self)
            vocab_shortcut.activated.connect(self._open_vocabulary_dialog)

            profiles_shortcut = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
            profiles_shortcut.activated.connect(self._open_profiles_dialog)

            snippets_shortcut = QShortcut(QKeySequence("Ctrl+Shift+M"), self)
            snippets_shortcut.activated.connect(self._open_snippets_dialog)

            voice_lab_shortcut = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
            voice_lab_shortcut.activated.connect(self._open_voice_lab_dialog)

            archive_shortcut = QShortcut(QKeySequence("Ctrl+H"), self)
            archive_shortcut.activated.connect(self._open_archive_dialog)

    def _setup_global_hotkey(self):
        """Register system-wide hotkey."""
        self._recording_mode = None
        self._last_hotkey_press_time = 0.0
        _start_global_hotkey(
            self._on_global_hotkey_pressed,
            self._on_global_hotkey_released,
            self._open_transform_palette,
        )

    def _update_hotkey_label(self):
        hotkey = self.settings.value("global_hotkey", DEFAULT_GLOBAL_HOTKEY)
        self.hotkey_label.setText(
            f"Global Hotkey: Hold <b>{hotkey}</b> to record, release to paste | Transform: <b>Ctrl+Alt+T</b>"
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

        transform_action = menu.addAction("✨ Transform Selected Text (Ctrl+Alt+T)")
        transform_action.triggered.connect(lambda: self._open_transform_palette())

        menu.addSeparator()

        show_action = menu.addAction("Show Window")
        show_action.triggered.connect(self.show)

        settings_action = menu.addAction("Settings...")
        settings_action.triggered.connect(self._open_settings)

        update_action = menu.addAction("🔄 Check for Updates...")
        update_action.triggered.connect(self._check_for_updates_manual)

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
        is_pro = self._is_pro()
        use_local = self.settings.value(SETTINGS_USE_LOCAL, "true") == "true"
        local_model_size = self.settings.value(SETTINGS_LOCAL_MODEL_SIZE, "base")
        if not is_pro and local_model_size not in FREE_ALLOWED_LOCAL_MODELS:
            local_model_size = "base"

        api_key = self.settings.value(SETTINGS_API_KEY, "") or os.environ.get(
            "OPENAI_API_KEY", ""
        )
        language = self.settings.value(SETTINGS_LANGUAGE, "auto")
        task = self.settings.value(SETTINGS_TASK, TASK_TRANSCRIBE)

        try:
            self._transcriber = TranscribeService(
                api_key=api_key,
                use_local=use_local,
                local_model_size=local_model_size,
                vocabulary_manager=self.vocabulary_manager,
                language=language,
                task=task,
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

        if not self._is_pro():
            rem = self._get_remaining_daily_dictations()
            if rem is not None and rem <= 0:
                self._show_daily_limit_modal()
                return

        # Capture current foreground window before recording/overlay changes state
        self._target_hwnd = None
        self._target_process = None
        self._target_title = None
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

        if hasattr(self, "profile_manager") and self.profile_manager:
            try:
                self._target_process, self._target_title = (
                    self.profile_manager.detect_foreground_app(self._target_hwnd)
                )
            except Exception:
                self._target_process, self._target_title = None, None

        _play_sound(True)
        self.capsule.show_recording()
        if hasattr(self, "visualizer_ribbon"):
            self.visualizer_ribbon.set_transcribing(False)
            self.visualizer_ribbon.set_active(True)
            self.visualizer_ribbon.setVisible(True)
        device_str = self.settings.value(SETTINGS_DEVICE, "")
        device = int(device_str) if device_str and device_str != "None" else None

        if self._session_started_at is None:
            self._session_started_at = time.monotonic()
        self._recording_started_at = time.monotonic()

        # Let the start cue play out cleanly before opening the microphone stream,
        # preventing acoustic feedback and device contention on cold DAC wake-up.
        time.sleep(0.06)

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
        """Monitor recording for silence (in toggle mode) and enforce 30s cap on Free Edition."""
        import time
        import numpy as np

        silence_duration = 1.5
        block_duration = 0.04
        blocks_for_silence = int(silence_duration / block_duration)
        silent_blocks = 0
        is_hold = getattr(self, "_recording_mode", None) == "HOLD"
        is_pro = self._is_pro()

        while self._recorder and self._recorder.is_recording:
            time.sleep(block_duration)
            if not self._recorder or not self._recorder.is_recording:
                break
            with self._recorder._lock:
                if not self._recorder._recording:
                    continue
                latest = self._recorder._recording[-1]
                level = float(np.sqrt(np.mean(latest**2))) if latest.size > 0 else 0.0

            # Feed live level to floating capsule and embedded ribbon
            self.capsule.update_audio_level(level)
            if (
                hasattr(self, "visualizer_ribbon")
                and self.visualizer_ribbon.isVisible()
            ):
                self.visualizer_ribbon.update_audio_level(level)

            # Free Edition: enforce 10-second max recording duration
            if not is_pro and self._recording_started_at:
                elapsed = time.monotonic() - self._recording_started_at
                if elapsed >= FREE_MAX_RECORDING_SECONDS:
                    self.request_stop_recording.emit()
                    break

            if not is_hold:
                if level < 0.01:  # SILENCE_THRESHOLD
                    silent_blocks += 1
                    if silent_blocks >= blocks_for_silence:
                        self.request_stop_recording.emit()
                        break
                else:
                    silent_blocks = 0

    @Slot()
    def _stop_recording(self):
        if not self._recorder or not self._recorder.is_recording:
            return

        self._recording_mode = None
        try:
            wav_path = self._recorder.stop()
        except RuntimeError:
            self.capsule.hide_capsule()
            if hasattr(self, "visualizer_ribbon"):
                self.visualizer_ribbon.set_active(False)
                self.visualizer_ribbon.setVisible(False)
            self._reset_recording_ui()
            return

        # Free Edition: ensure audio length is strictly clamped to max 10.0s
        if not self._is_pro() and os.path.exists(wav_path):
            try:
                import soundfile as sf

                data, sr = sf.read(wav_path)
                max_samples = int(FREE_MAX_RECORDING_SECONDS * sr)
                if len(data) > max_samples:
                    data = data[:max_samples]
                    sf.write(wav_path, data, sr)
            except Exception:
                pass

        _play_sound(False)
        self.capsule.show_transcribing()
        if hasattr(self, "visualizer_ribbon"):
            self.visualizer_ribbon.set_transcribing(True)
            self.visualizer_ribbon.setVisible(True)
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

    def _learn_from_last_edit(self):
        """Diff any user edit made to the most recent transcription entry.

        Compares the last entry in ``_transcription_history`` against what is
        currently shown in ``text_display`` (the user may have hand-corrected
        it before the next transcription arrives) and feeds any small,
        repeated substitutions into the vocabulary manager's learned
        corrections so they auto-apply in future transcriptions.
        """
        if not self._transcription_history or not hasattr(self, "vocabulary_manager"):
            return

        expected_previous = "\n\n".join(self._transcription_history)
        current = self.text_display.toPlainText()
        if current == expected_previous:
            return

        prior_entries = self._transcription_history[:-1]
        prefix = "\n\n".join(prior_entries)
        if prior_entries and not current.startswith(prefix):
            return

        edited_last = current[len(prefix) :].lstrip("\n") if prior_entries else current
        original_last = self._transcription_history[-1]

        for orig_phrase, corrected_phrase in diff_corrections(
            original_last, edited_last
        ):
            self.vocabulary_manager.record_correction(orig_phrase, corrected_phrase)

        self.vocabulary_manager.save()

    @Slot(str)
    def _on_transcription_complete(self, text: str):
        text = text.strip()
        if not text:
            self.capsule.hide_capsule()
            if hasattr(self, "visualizer_ribbon"):
                self.visualizer_ribbon.set_active(False)
                self.visualizer_ribbon.setVisible(False)
            self._update_status(self.STATUS_IDLE)
            return

        # Parse verbal punctuation and formatting commands if enabled
        if hasattr(self, "verbal_command_parser") and self.verbal_command_parser:
            text = self.verbal_command_parser.parse(text)

        # Pro: Expand Voice Snippets & Macros
        if self._is_pro() and hasattr(self, "snippet_manager") and self.snippet_manager:
            text = self.snippet_manager.expand_text(text)

        # Pro: Apply active formatting mode (Clean, Bullets, Email, etc.)
        if self._is_pro():
            mode_id = None
            if hasattr(self, "profile_manager") and self.profile_manager:
                resolved = self.profile_manager.resolve_mode(
                    process_name=getattr(self, "_target_process", None),
                    window_title=getattr(self, "_target_title", None),
                    hwnd=getattr(self, "_target_hwnd", None),
                )
                if resolved and resolved != RAW_MODE.id:
                    mode_id = resolved

            if not mode_id:
                mode_id = self.settings.value(SETTINGS_FORMATTING_MODE, "raw")

            if mode_id and mode_id != "raw":
                mode = get_mode_by_id(mode_id)
                if mode:
                    engine = FormatEngine(
                        mode=mode,
                        verbal_command_parser=getattr(
                            self, "verbal_command_parser", None
                        ),
                    )
                    text = engine.format_text(text)

        self.capsule.show_done()
        if hasattr(self, "visualizer_ribbon"):
            self.visualizer_ribbon.set_active(False)
            self.visualizer_ribbon.setVisible(False)
        self._learn_from_last_edit()
        self._transcription_history.append(text)
        if self._history_limit > 0:
            self._transcription_history = self._transcription_history[
                -self._history_limit :
            ]
        self.text_display.setPlainText("\n\n".join(self._transcription_history))

        if not self._is_pro():
            self._increment_daily_dictation_count()
            rem = self._get_remaining_daily_dictations()
            self._update_status(
                f"Done · Free: {rem}/{FREE_DAILY_DICTATION_LIMIT} remaining today"
            )
            self._update_window_title()
        else:
            self._update_status(self.STATUS_DONE)

        self._last_raw_transcription = text
        if hasattr(self, "archive") and self.archive:
            try:
                lang = self.settings.value(SETTINGS_LANGUAGE, "auto")
                active_mode = self.settings.value(SETTINGS_FORMATTING_MODE, "raw")
                self.archive.save_entry(
                    text=text,
                    audio_path=getattr(self, "_last_wav_path", None),
                    language=lang,
                    mode=active_mode,
                )
            except Exception:
                pass

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
        if self._history_limit > 0:
            self._segments = self._segments[-self._history_limit :]

        # Copy to clipboard
        _copy_to_clipboard(text)

        # Auto-paste (simulate Ctrl+V into the target / active window)
        auto_paste = self.settings.value(SETTINGS_AUTO_PASTE, "true") == "true"
        if auto_paste:
            target_hwnd = getattr(self, "_target_hwnd", None)
            from PySide6.QtCore import QTimer

            QTimer.singleShot(150, lambda: _simulate_paste(target_hwnd))

            # With auto-paste on, the user's edits (if any) happen in the
            # target app, invisible to us -- show a quick, non-activating
            # review toast so we still have a chance to learn corrections.
            show_review = self.settings.value(SETTINGS_QUICK_REVIEW, "true") == "true"
            if show_review:
                self._show_review_toast(text)

    def _show_review_toast(self, original_text: str):
        from scribe_dictation.ui.review_toast import ReviewToast

        toast = ReviewToast(original_text, parent=None)
        toast.reviewed.connect(self._on_review_toast_finished)
        self._review_toast = toast
        toast.show()

    @Slot(str, str)
    def _on_review_toast_finished(self, original_text: str, edited_text: str):
        if hasattr(self, "vocabulary_manager") and self.vocabulary_manager:
            for orig_phrase, corrected_phrase in diff_corrections(
                original_text, edited_text
            ):
                self.vocabulary_manager.record_correction(orig_phrase, corrected_phrase)
            self.vocabulary_manager.save()
        self._review_toast = None

    # ── Actions ───────────────────────────────────────────────────────

    def _copy_to_clipboard_action(self):
        text = self.text_display.toPlainText()
        if text.strip():
            _copy_to_clipboard(text)
            self._update_status("Copied!")

    def _clear_text(self):
        self.text_display.clear()
        self._transcription_history = []
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
            self._set_menu_bar_visible(self._is_menu_bar_visible())
            new_limit = self._get_history_limit()
            self._set_history_limit(new_limit)
            self._setup_transcriber()
            _stop_global_hotkey()
            self._setup_global_hotkey()
            self._update_hotkey_label()

    def _open_onboarding_wizard(self):
        from scribe_dictation.ui.onboarding_wizard import OnboardingWizard

        wizard = OnboardingWizard(
            vocabulary_manager=getattr(self, "vocabulary_manager", None), parent=self
        )
        wizard.exec()
        self._setup_transcriber()

    def _show_about(self):
        is_pro = self._is_pro()
        tier_label = (
            "<b>Pro Edition</b> (Lifetime License Active)"
            if is_pro
            else f"<b>Free Edition</b> ({FREE_DAILY_DICTATION_LIMIT} dictations/day, {int(FREE_MAX_RECORDING_SECONDS)}s length limit, base/small models)"
        )
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b><br><br>"
            f"Version 1.0.0 — {tier_label}<br><br>"
            f"A desktop dictation app supporting local offline processing and OpenAI cloud API.<br><br>"
            f"Press <b>Ctrl+Win</b> or the global shortcut to start/stop recording.<br>"
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
    """Launch the Privacy Scribe application."""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORGANIZATION)

    saved_theme = QSettings(ORGANIZATION, APP_NAME).value(SETTINGS_THEME, THEME_DEFAULT)
    apply_theme(app, saved_theme)

    from scribe_dictation.ui.onboarding_wizard import (
        OnboardingWizard,
        should_show_onboarding,
    )

    if should_show_onboarding():
        wizard = OnboardingWizard()
        wizard.exec()

    # Launch main window (Runs out-of-the-box in Free Edition; Pro unlocks all features)
    window = ScribeDictationWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
