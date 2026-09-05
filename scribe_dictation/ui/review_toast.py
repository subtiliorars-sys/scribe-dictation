"""Post-paste quick-review toast for Privacy Scribe.

After auto-paste, the user's focus and cursor move to whatever app they
pasted into -- corrections happen there, invisible to Privacy Scribe. This
toast is a small, non-activating floating popup that briefly surfaces the
just-transcribed text for a quick glance/fix, giving the app a real chance
to observe corrections even when auto-paste is on.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

AUTO_DISMISS_MS = 8000
EDIT_GRACE_MS = 4000


class ReviewToast(QWidget):
    """Non-activating floating popup showing the last transcription for a
    quick edit before it auto-dismisses. Emits ``reviewed`` with the
    (original, edited) text pair once dismissed.
    """

    reviewed = Signal(str, str)

    def __init__(self, original_text: str, parent=None):
        super().__init__(parent)
        self._original_text = original_text
        self._finished = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(340, 150)
        self.setStyleSheet(
            "background-color: #161b22; border: 1px solid #30363d; border-radius: 8px;"
        )

        if sys.platform == "win32":
            try:
                import ctypes

                hwnd = int(self.winId())
                GWL_EXSTYLE = -20
                WS_EX_NOACTIVATE = 0x08000000
                WS_EX_TOOLWINDOW = 0x00000080
                WS_EX_TOPMOST = 0x00000008
                user32 = ctypes.windll.user32
                style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                user32.SetWindowLongW(
                    hwnd,
                    GWL_EXSTYLE,
                    style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
                )
            except Exception:
                pass

        self._setup_layout()
        self._reposition()

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._finish)
        self._dismiss_timer.start(AUTO_DISMISS_MS)

        self.text_edit.textChanged.connect(self._on_text_changed)

    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("✓ Transcribed — fix anything?")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #58a6ff; background: transparent;")
        header.addWidget(title)
        header.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(
            "QPushButton { color: #8b949e; background: transparent; border: none; }"
            "QPushButton:hover { color: #f0f6fc; }"
        )
        close_btn.clicked.connect(self._finish)
        header.addWidget(close_btn)
        layout.addLayout(header)

        self.text_edit = QPlainTextEdit(self._original_text)
        self.text_edit.setStyleSheet(
            "color: #f0f6fc; background: #0d1117; border: 1px solid #21262d; "
            "border-radius: 4px; padding: 4px;"
        )
        self.text_edit.setFont(QFont("Segoe UI", 9))
        layout.addWidget(self.text_edit)

        hint = QLabel("Edits here teach the app your corrections.")
        hint.setFont(QFont("Segoe UI", 8))
        hint.setStyleSheet("color: #6e7681; background: transparent;")
        layout.addWidget(hint)

    def _reposition(self):
        screen = QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            x = geom.x() + geom.width() - self.width() - 24
            y = geom.y() + geom.height() - self.height() - 24
            self.move(x, y)

    def _on_text_changed(self):
        # Give the user a grace window to keep typing without the toast
        # vanishing mid-edit.
        self._dismiss_timer.start(EDIT_GRACE_MS)

    def _finish(self):
        if self._finished:
            return
        self._finished = True
        self._dismiss_timer.stop()
        edited_text = self.text_edit.toPlainText()
        self.reviewed.emit(self._original_text, edited_text)
        self.hide()
        self.deleteLater()

    def closeEvent(self, event):
        self._finish()
        super().closeEvent(event)
