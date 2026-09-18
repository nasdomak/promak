"""Visual style of the application.

Two palettes - light (the default) and dark - and one Qt style sheet built
from them, so the whole application can be re-skinned from this single
file.  Every colour a screen needs has a name here; no widget anywhere
hard-codes a colour of its own.

The light palette is the one Promak starts with: a tool somebody is meant
to buy should look like a normal, tidy application, not like a console.
The dark one is a real alternative, not an afterthought.
"""

from __future__ import annotations

# The two brand colours the logo is built from.
BRAND_BLUE = "#3A6BF0"
BRAND_TEAL = "#16B5A4"

LIGHT = {
    "bg": "#F5F7FB",
    "surface": "#FFFFFF",
    "surface_alt": "#EDF0F7",
    "surface_sunken": "#F8FAFD",
    "border": "#DBE1EC",
    "border_strong": "#C3CBDA",
    "text": "#151A24",
    "text_dim": "#5B6478",
    "text_faint": "#8A93A6",
    "accent": "#2F5BEA",
    "accent_hover": "#2449C8",
    "accent_text": "#FFFFFF",
    "accent_soft": "#E8EEFF",
    "accent_line": "#B9CAFB",
    "success": "#0E9F6E",
    "success_soft": "#E3F8EF",
    "warning": "#9A5B00",
    "warning_soft": "#FFF4E0",
    "error": "#C62828",
    "error_soft": "#FDECEC",
    "selection": "#DDE5FF",
    "brand_from": BRAND_BLUE,
    "brand_to": BRAND_TEAL,
}

DARK = {
    "bg": "#0F1218",
    "surface": "#171B23",
    "surface_alt": "#1F242E",
    "surface_sunken": "#12161D",
    "border": "#2B313D",
    "border_strong": "#3A4250",
    "text": "#E8EBF2",
    "text_dim": "#98A1B3",
    "text_faint": "#7A8397",
    "accent": "#5B86FF",
    "accent_hover": "#7599FF",
    "accent_text": "#0B1020",
    "accent_soft": "#1B2440",
    "accent_line": "#33477C",
    "success": "#34D399",
    "success_soft": "#122A22",
    "warning": "#FBBF24",
    "warning_soft": "#2C2410",
    "error": "#F87171",
    "error_soft": "#2E1618",
    "selection": "#24324F",
    "brand_from": "#5B86FF",
    "brand_to": "#2BD6C4",
}

THEMES = {"light": LIGHT, "dark": DARK}
DEFAULT_THEME = "light"

STYLE_TEMPLATE = """
/* ===================================================== base ========== */
QWidget {{
    background-color: {bg};
    color: {text};
    font-family: "Segoe UI Variable", "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{ background-color: {bg}; }}
QLabel {{ background: transparent; }}

/* ================================================== sidebar ========== */
#Sidebar {{
    background-color: {surface};
    border-right: 1px solid {border};
}}
#SidebarBrand {{
    background: transparent;
    padding: 20px 16px 0 16px;
}}
#SidebarTitle {{
    font-size: 19px;
    font-weight: 800;
    letter-spacing: 0.2px;
    color: {text};
    background: transparent;
}}
#SidebarSubtitle {{
    font-size: 11px;
    color: {text_faint};
    padding: 0 16px 16px 16px;
    background: transparent;
}}
#SidebarSection {{
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1.4px;
    color: {text_faint};
    padding: 6px 18px 6px 18px;
    background: transparent;
}}
QListWidget#ToolList {{
    background: transparent;
    border: none;
    outline: none;
    padding: 2px 10px;
}}
QListWidget#ToolList::item {{
    padding: 10px 12px;
    margin: 2px 0;
    border-radius: 9px;
    color: {text_dim};
}}
QListWidget#ToolList::item:hover {{
    background-color: {surface_alt};
    color: {text};
}}
QListWidget#ToolList::item:selected {{
    background-color: {accent};
    color: {accent_text};
    font-weight: 600;
}}
#SidebarFooter {{
    font-size: 11px;
    color: {text_faint};
    background: transparent;
}}
QPushButton#ThemeToggle {{
    background-color: {surface_alt};
    border: 1px solid {border};
    border-radius: 9px;
    padding: 7px 10px;
    color: {text_dim};
    font-weight: 600;
    text-align: center;
}}
QPushButton#ThemeToggle:hover {{
    border-color: {accent};
    color: {text};
    background-color: {accent_soft};
}}

/* ================================================= headings ========== */
#PageTitle {{
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.2px;
    color: {text};
}}
#PageSubtitle {{
    font-size: 12.5px;
    color: {text_dim};
}}
#SectionLabel {{
    font-size: 12px;
    font-weight: 700;
    color: {text};
}}
#HintLabel {{
    color: {text_dim};
    font-size: 11.5px;
}}

/* ================================================== notices ========== */
#NoticeBanner {{
    border: 1px solid {accent_line};
    border-left: 4px solid {accent};
    border-radius: 9px;
    background-color: {accent_soft};
    color: {text};
    padding: 10px 13px;
    font-size: 12px;
}}
#NoticeBanner[kind="warning"] {{
    border-color: {warning};
    border-left: 4px solid {warning};
    background-color: {warning_soft};
    color: {text};
}}
#NoticeBanner[kind="error"] {{
    border-color: {error};
    border-left: 4px solid {error};
    background-color: {error_soft};
    color: {text};
}}
#NoticeBanner[kind="success"] {{
    border-color: {success};
    border-left: 4px solid {success};
    background-color: {success_soft};
    color: {text};
}}

/* ================================================ drop area ========== */
#DropArea {{
    border: 2px dashed {border_strong};
    border-radius: 12px;
    background-color: {surface_sunken};
    color: {text_dim};
    font-size: 12.5px;
    padding: 14px;
}}
#DropArea:hover {{
    border-color: {accent};
    background-color: {accent_soft};
    color: {text};
}}

/* ================================================== preview ========== */
#PreviewBox {{
    background-color: {surface_sunken};
    border: 1px solid {border};
    border-radius: 12px;
}}
#PreviewTitle {{
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.8px;
    color: {text_faint};
}}
#PreviewImage {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 9px;
    color: {text_faint};
    font-size: 11.5px;
}}
#PreviewCaption {{
    font-size: 11.5px;
    color: {text_dim};
}}

/* =================================================== inputs ========== */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 7px 10px;
    color: {text};
    selection-background-color: {accent};
    selection-color: {accent_text};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {border_strong}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {accent};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    background-color: {surface_alt};
    color: {text_faint};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {accent};
    selection-color: {accent_text};
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; }}

/* ================================================== buttons ========== */
QPushButton {{
    background-color: {surface};
    border: 1px solid {border_strong};
    border-radius: 8px;
    padding: 8px 15px;
    color: {text};
    font-weight: 500;
}}
QPushButton:hover {{ border-color: {accent}; background-color: {accent_soft}; }}
QPushButton:pressed {{ background-color: {surface_alt}; }}
QPushButton:disabled {{
    color: {text_faint};
    border-color: {border};
    background-color: {surface_alt};
}}
QPushButton#PrimaryButton {{
    background-color: {accent};
    border: 1px solid {accent};
    color: {accent_text};
    font-weight: 700;
    padding: 9px 18px;
}}
QPushButton#PrimaryButton:hover {{
    background-color: {accent_hover};
    border-color: {accent_hover};
}}
QPushButton#PrimaryButton:disabled {{
    background-color: {surface_alt};
    border-color: {border};
    color: {text_faint};
}}
QPushButton#DangerButton {{ color: {error}; border-color: {border_strong}; }}
QPushButton#DangerButton:hover {{
    border-color: {error};
    background-color: {error_soft};
}}

/* =============================================== group boxes ========= */
QGroupBox {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 12px;
    margin-top: 16px;
    padding: 18px 14px 14px 14px;
    font-size: 13px;
    font-weight: 700;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 2px 8px;
    color: {text};
    background-color: {bg};
    border-radius: 6px;
}}

/* ===================================================== table ========= */
QTableWidget {{
    background-color: {surface};
    alternate-background-color: {surface_sunken};
    border: 1px solid {border};
    border-radius: 10px;
    gridline-color: {border};
    selection-background-color: {selection};
    selection-color: {text};
}}
QHeaderView::section {{
    background-color: {surface_alt};
    color: {text_dim};
    border: none;
    border-bottom: 1px solid {border};
    padding: 8px 9px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}
QTableWidget::item {{ padding: 6px 7px; border: none; }}
QTableCornerButton::section {{ background-color: {surface_alt}; border: none; }}

/* ================================================== progress ========= */
QProgressBar {{
    background-color: {surface_alt};
    border: 1px solid {border};
    border-radius: 8px;
    height: 18px;
    text-align: center;
    color: {text};
    font-size: 11px;
}}
QProgressBar::chunk {{
    background-color: {accent};
    border-radius: 7px;
    margin: 1px;
}}

/* ======================================================= log ========= */
QPlainTextEdit#LogView {{
    font-family: "Cascadia Mono", "Consolas", "Menlo", monospace;
    font-size: 11px;
    background-color: {surface_sunken};
    color: {text_dim};
    border: 1px solid {border};
    border-radius: 9px;
}}

/* ================================================== sliders ========== */
QSlider::groove:horizontal {{
    height: 5px;
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {surface};
    border: 2px solid {accent};
    width: 15px;
    height: 15px;
    margin: -7px 0;
    border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{ border-color: {accent_hover}; }}
QSlider::tickmark {{ color: {text_faint}; }}
QSlider:disabled::sub-page:horizontal {{ background: {border_strong}; }}
QSlider:disabled::handle:horizontal {{ border-color: {border_strong}; }}

/* =============================================== tick boxes ========== */
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; color: {text}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {text_faint}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QCheckBox::indicator {{
    border: 1px solid {border_strong};
    border-radius: 4px;
    background: {surface};
}}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    image: none;
}}
QRadioButton::indicator {{
    border: 1px solid {border_strong};
    border-radius: 8px;
    background: {surface};
}}
QRadioButton::indicator:checked {{ background: {accent}; border-color: {accent}; }}

/* ====================================================== misc ========= */
QSplitter::handle {{ background-color: transparent; height: 10px; }}
QSplitter::handle:hover {{ background-color: {accent_soft}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {border_strong};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {text_faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {border_strong};
    border-radius: 5px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {text_faint}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QStatusBar {{
    background-color: {surface};
    border-top: 1px solid {border};
    color: {text_dim};
}}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background-color: {surface};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: 7px;
    padding: 7px 9px;
    font-size: 12px;
}}
QMessageBox {{ background-color: {surface}; }}
QMessageBox QLabel {{ color: {text}; }}
"""


def normalise(name: str) -> str:
    """Answer with 'light' or 'dark', whatever was asked for."""
    value = str(name or "").strip().lower()
    return value if value in THEMES else DEFAULT_THEME


def palette(name: str = DEFAULT_THEME) -> dict:
    """The colours of one theme."""
    return dict(THEMES[normalise(name)])


def other_theme(name: str) -> str:
    """The theme the light/dark switch moves to."""
    return "dark" if normalise(name) == "light" else "light"


def stylesheet(name: str = DEFAULT_THEME) -> str:
    """The full Qt style sheet for the requested theme."""
    return STYLE_TEMPLATE.format(**palette(name))
