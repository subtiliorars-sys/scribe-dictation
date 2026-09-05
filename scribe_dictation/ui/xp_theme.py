"""Windows XP "Luna" retro theme for the Scribe Dictation UI.

Applied globally via QApplication.setStyleSheet(). Qt Style Sheets can't
replicate XP's curved title-bar bezier, so the look leans into what QSS
*can* do well instead: hard, jagged beveled borders (outset/inset), the
bright Luna blue/silver/green palette, and chunky rectangular buttons.
"""

# Luna palette
XP_BLUE_DARK = "#0a246a"
XP_BLUE = "#245edb"
XP_BLUE_LIGHT = "#3d95ff"
XP_BLUE_TITLE_GRAD = "#0997ff"
XP_DESKTOP_TEAL = "#5a7edc"
XP_SILVER = "#ece9d8"
XP_SILVER_DARK = "#aca899"
XP_SILVER_LIGHT = "#ffffff"
XP_BUTTON_FACE = "#ece9d8"
XP_GREEN = "#3ddc3d"
XP_GREEN_DARK = "#1a8c1a"
XP_RED = "#ff3b3b"
XP_TEXT = "#000000"
XP_YELLOW_HIGHLIGHT = "#ffff88"

XP_FONT_FAMILY = "Tahoma, 'MS Sans Serif', 'Segoe UI', sans-serif"

XP_STYLESHEET = f"""
* {{
    font-family: {XP_FONT_FAMILY};
    font-size: 11px;
    color: {XP_TEXT};
}}

QMainWindow, QDialog {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {XP_DESKTOP_TEAL}, stop:1 #3a5cb8
    );
}}

QWidget {{
    background-color: {XP_SILVER};
}}

/* Title-bar-style headers, group boxes: bright blue gradient, square jagged edges */
QGroupBox {{
    background-color: {XP_SILVER};
    border: 2px outset {XP_SILVER_DARK};
    border-radius: 0px;
    margin-top: 14px;
    font-weight: bold;
    padding-top: 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 4px;
    padding: 1px 6px;
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {XP_BLUE_DARK}, stop:0.5 {XP_BLUE_LIGHT}, stop:1 {XP_BLUE}
    );
    color: white;
    border: 1px outset {XP_BLUE_DARK};
}}

QLabel {{
    background: transparent;
}}

/* Chunky beveled buttons -- outset/inset borders read as "jagged" 3D edges */
QPushButton {{
    background-color: {XP_BUTTON_FACE};
    border: 2px outset {XP_SILVER_DARK};
    border-radius: 0px;
    padding: 4px 14px;
    min-height: 20px;
    font-weight: bold;
}}
QPushButton:hover {{
    background-color: #fff7c2;
    border: 2px outset {XP_BLUE};
}}
QPushButton:pressed {{
    background-color: #d7d2c0;
    border: 2px inset {XP_SILVER_DARK};
}}
QPushButton:disabled {{
    color: #7f7f7f;
    background-color: {XP_SILVER};
    border: 2px outset #d4d0c8;
}}
QPushButton:checked {{
    background-color: {XP_GREEN};
    border: 2px inset {XP_GREEN_DARK};
    color: white;
}}

QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget, QTableWidget {{
    background-color: #ffffff;
    border: 2px inset {XP_SILVER_DARK};
    border-radius: 0px;
    selection-background-color: {XP_BLUE};
    selection-color: white;
}}

QComboBox {{
    background-color: {XP_BUTTON_FACE};
    border: 2px outset {XP_SILVER_DARK};
    border-radius: 0px;
    padding: 2px 6px;
    min-height: 20px;
}}
QComboBox::drop-down {{
    border-left: 2px outset {XP_SILVER_DARK};
    width: 18px;
    background-color: {XP_BUTTON_FACE};
}}
QComboBox QAbstractItemView {{
    background-color: white;
    border: 2px outset {XP_SILVER_DARK};
    selection-background-color: {XP_BLUE};
    selection-color: white;
}}

QCheckBox, QRadioButton {{
    background: transparent;
    spacing: 6px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 13px;
    height: 13px;
    border: 2px inset {XP_SILVER_DARK};
    background-color: white;
}}
QCheckBox::indicator:checked {{
    background-color: {XP_GREEN};
}}
QRadioButton::indicator {{
    border-radius: 7px;
}}
QRadioButton::indicator:checked {{
    background-color: {XP_BLUE};
}}

/* Tabs styled like classic XP folder tabs */
QTabWidget::pane {{
    border: 2px outset {XP_SILVER_DARK};
    background-color: {XP_SILVER};
    top: -1px;
}}
QTabBar::tab {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #fdfbf5, stop:1 {XP_SILVER_DARK}
    );
    border: 2px outset {XP_SILVER_DARK};
    border-bottom: none;
    padding: 5px 14px;
    margin-right: 2px;
    font-weight: bold;
}}
QTabBar::tab:selected {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {XP_BLUE_LIGHT}, stop:1 {XP_BLUE}
    );
    color: white;
}}

/* Status/progress bars: bright green Luna gradient */
QProgressBar {{
    border: 2px inset {XP_SILVER_DARK};
    background-color: white;
    text-align: center;
    border-radius: 0px;
}}
QProgressBar::chunk {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #7dfa7d, stop:0.5 {XP_GREEN}, stop:1 {XP_GREEN_DARK}
    );
}}

QScrollBar:vertical {{
    background-color: {XP_SILVER};
    border: 1px outset {XP_SILVER_DARK};
    width: 17px;
}}
QScrollBar::handle:vertical {{
    background-color: {XP_BUTTON_FACE};
    border: 2px outset {XP_SILVER_DARK};
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    background-color: {XP_BUTTON_FACE};
    border: 2px outset {XP_SILVER_DARK};
    height: 16px;
}}

QMenuBar {{
    background-color: {XP_SILVER};
    border-bottom: 2px outset {XP_SILVER_DARK};
}}
QMenuBar::item:selected {{
    background-color: {XP_BLUE};
    color: white;
}}
QMenu {{
    background-color: {XP_SILVER};
    border: 2px outset {XP_SILVER_DARK};
}}
QMenu::item:selected {{
    background-color: {XP_BLUE};
    color: white;
}}

QStatusBar {{
    background-color: {XP_SILVER};
    border-top: 2px outset {XP_SILVER_DARK};
}}

QToolTip {{
    background-color: {XP_YELLOW_HIGHLIGHT};
    color: black;
    border: 1px solid black;
    padding: 2px;
}}
"""


THEME_DEFAULT = "default"
THEME_WINDOWS_XP = "windows_xp"

THEME_LABELS = {
    THEME_DEFAULT: "&Default",
    THEME_WINDOWS_XP: "Windows &XP (Retro)",
}


def apply_theme(app, theme: str) -> None:
    """Apply the given theme (by key) to the whole application."""
    if theme == THEME_WINDOWS_XP:
        app.setStyleSheet(XP_STYLESHEET)
    else:
        app.setStyleSheet("")


def apply_xp_theme(app) -> None:
    """Apply the Windows XP retro stylesheet to the whole application."""
    apply_theme(app, THEME_WINDOWS_XP)
