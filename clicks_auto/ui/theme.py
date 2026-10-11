"""Colour themes and the generated Qt stylesheet.

Everything visual flows from a :class:`Palette`; switching a theme re-generates
the stylesheet and (optionally) cross-fades the window.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class Palette:
    key: str
    label: str
    bg: str
    bg_alt: str
    surface: str
    surface_alt: str
    surface_hi: str
    border: str
    border_hi: str
    text: str
    text_dim: str
    text_faint: str
    accent: str
    accent_hi: str
    accent_dim: str
    on_accent: str
    success: str
    warning: str
    danger: str
    info: str
    shadow: str
    log_bg: str
    dark: bool = True

    def get(self, name: str, default: str = "#ffffff") -> str:
        return getattr(self, name, default)

    def with_accent(self, accent: str, accent_hi: str, accent_dim: str | None = None) -> "Palette":
        return replace(self, accent=accent, accent_hi=accent_hi,
                       accent_dim=accent_dim or _mix(accent, self.bg, 0.65))


PALETTES: dict[str, Palette] = {
    "midnight": Palette(
        key="midnight", label="Midnight",
        bg="#0b1020", bg_alt="#0e1428", surface="#141b33", surface_alt="#18203c",
        surface_hi="#1f2949", border="#242f52", border_hi="#33406b",
        text="#eef2ff", text_dim="#a7b0d0", text_faint="#6f79a0",
        accent="#5b8cff", accent_hi="#7ba3ff", accent_dim="#20305c",
        on_accent="#08122b", success="#37d399", warning="#ffb454",
        danger="#ff6188", info="#59c2ff", shadow="#05070f",
        log_bg="#0a0f1f",
    ),
    "aurora": Palette(
        key="aurora", label="Aurora",
        bg="#08161a", bg_alt="#0b1d22", surface="#10262c", surface_alt="#143038",
        surface_hi="#1b3d47", border="#20444e", border_hi="#2d5f6b",
        text="#e9fbf7", text_dim="#9dc4bf", text_faint="#6c9a97",
        accent="#2ee6a8", accent_hi="#61ffc4", accent_dim="#0e4034",
        on_accent="#03241b", success="#2ee6a8", warning="#ffcf5c",
        danger="#ff6b81", info="#5ad1ff", shadow="#04100f",
        log_bg="#07171a",
    ),
    "sunset": Palette(
        key="sunset", label="Sunset",
        bg="#1b0f1c", bg_alt="#231326", surface="#2a1830", surface_alt="#331d3a",
        surface_hi="#402546", border="#4a2b51", border_hi="#63396d",
        text="#fff1f6", text_dim="#d3a9c2", text_faint="#a178a0",
        accent="#ff7a59", accent_hi="#ffa07f", accent_dim="#4d241c",
        on_accent="#2b0d06", success="#8fd96a", warning="#ffc861",
        danger="#ff5d7a", info="#c58bff", shadow="#120712",
        log_bg="#1a0d1a",
    ),
    "graphite": Palette(
        key="graphite", label="Graphite",
        bg="#111315", bg_alt="#15181b", surface="#1b1f23", surface_alt="#21262b",
        surface_hi="#2a3138", border="#2e353d", border_hi="#414b55",
        text="#eef1f4", text_dim="#a8b1ba", text_faint="#77818c",
        accent="#4f9cf9", accent_hi="#7ab7ff", accent_dim="#1d3348",
        on_accent="#04121f", success="#43c98b", warning="#e0ae4d",
        danger="#ef5f6b", info="#63b3ff", shadow="#080a0b",
        log_bg="#0e1113",
    ),
    "daylight": Palette(
        key="daylight", label="Daylight",
        bg="#eef1f7", bg_alt="#e6ebf3", surface="#ffffff", surface_alt="#f6f8fc",
        surface_hi="#eaeffb", border="#d8dfeb", border_hi="#bfc9dc",
        text="#1a2133", text_dim="#5a6478", text_faint="#8b94a8",
        accent="#3b6ef5", accent_hi="#5f8bff", accent_dim="#dbe5ff",
        on_accent="#ffffff", success="#12a06d", warning="#c9791a",
        danger="#dc3f5c", info="#2272c9", shadow="#c3cbdb",
        log_bg="#f2f5fa", dark=False,
    ),
}

DEFAULT_THEME = "midnight"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _mix(a: str, b: str, ratio: float) -> str:
    ra, ga, ba = _hex_to_rgb(a)
    rb, gb, bb = _hex_to_rgb(b)
    ratio = max(0.0, min(1.0, ratio))
    return "#%02x%02x%02x" % (
        int(ra + (rb - ra) * ratio),
        int(ga + (gb - ga) * ratio),
        int(ba + (bb - ba) * ratio),
    )


def rgba(color: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(color)
    return f"rgba({r}, {g}, {b}, {alpha:.3f})"


def lighten(color: str, amount: float = 0.15) -> str:
    return _mix(color, "#ffffff", amount)


def darken(color: str, amount: float = 0.15) -> str:
    return _mix(color, "#000000", amount)


def get_palette(key: str) -> Palette:
    return PALETTES.get(key, PALETTES[DEFAULT_THEME])


# --------------------------------------------------------------------------


def build_stylesheet(palette: Palette, *, compact: bool = False) -> str:
    p = palette
    radius = 12 if compact else 14
    unit = 8 if compact else 10
    font_size = 12.5 if compact else 13.5

    return f"""
* {{
    font-family: "Segoe UI Variable Display", "Segoe UI", "Inter", "Noto Sans", sans-serif;
    font-size: {font_size}px;
    color: {p.text};
    outline: none;
}}
QMainWindow, QDialog, #Root, #PageHost {{ background: {p.bg}; }}
#WindowFrame {{
    background: {p.bg};
    border: 1px solid {p.border};
    border-radius: 14px;
}}
QWidget#Page {{ background: transparent; }}
QToolTip {{
    background: {p.surface_hi};
    color: {p.text};
    border: 1px solid {p.border_hi};
    border-radius: 8px;
    padding: 6px 8px;
}}
QLabel[role="h1"] {{ font-size: {font_size + 13}px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: {font_size + 7}px; font-weight: 650; }}
QLabel[role="h3"] {{ font-size: {font_size + 3}px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {p.text_dim}; }}
QLabel[role="faint"] {{ color: {p.text_faint}; font-size: {font_size - 1}px; }}
QLabel[role="mono"] {{ font-family: "Cascadia Mono", "Cascadia Code", Consolas, monospace; }}

/* --------------------------------------------------------------- surfaces */
#Card, QFrame#Card {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {radius}px;
}}
#Card[tone="alt"] {{ background: {p.surface_alt}; }}
#Card[tone="hi"] {{ background: {p.surface_hi}; }}
#Card[interactive="true"]:hover {{ border: 1px solid {p.border_hi}; }}
#Sidebar {{
    background: {p.bg_alt};
    border-right: 1px solid {p.border};
}}
#TopBar {{
    background: {p.bg_alt};
    border-bottom: 1px solid {p.border};
}}
#HeroCard {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {p.surface_hi}, stop:0.55 {p.surface}, stop:1 {_mix(p.surface, p.accent, 0.18)});
    border: 1px solid {p.border_hi};
    border-radius: {radius + 6}px;
}}
#Divider {{ background: {p.border}; max-height: 1px; min-height: 1px; }}

/* ------------------------------------------------------------------ text */
#PageTitle {{ font-size: {font_size + 15}px; font-weight: 700; }}
#PageSubtitle {{ color: {p.text_dim}; font-size: {font_size}px; }}
#StatValue {{ font-size: {font_size + 16}px; font-weight: 700; color: {p.text}; }}
#StatLabel {{ color: {p.text_faint}; font-size: {font_size - 1}px; letter-spacing: 0.6px; }}

/* --------------------------------------------------------------- buttons */
QPushButton {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {radius - 3}px;
    padding: {unit - 1}px {unit + 6}px;
    color: {p.text};
}}
QPushButton:hover {{ background: {p.surface_hi}; border-color: {p.border_hi}; }}
QPushButton:pressed {{ background: {darken(p.surface_hi, 0.08)}; }}
QPushButton:disabled {{ color: {p.text_faint}; background: {_mix(p.surface_alt, p.bg, 0.4)}; border-color: {p.border}; }}
QPushButton[kind="primary"] {{
    background: {p.accent};
    color: {p.on_accent};
    border: 1px solid {lighten(p.accent, 0.1)};
    font-weight: 650;
}}
QPushButton[kind="primary"]:hover {{ background: {p.accent_hi}; }}
QPushButton[kind="primary"]:disabled {{ background: {_mix(p.accent, p.bg, 0.55)}; color: {p.text_faint}; }}
QPushButton[kind="danger"] {{
    background: {p.danger}; color: {p.on_accent}; border: 1px solid {lighten(p.danger, 0.1)}; font-weight: 650;
}}
QPushButton[kind="danger"]:hover {{ background: {lighten(p.danger, 0.12)}; }}
QPushButton[kind="success"] {{
    background: {p.success}; color: {p.on_accent}; border: 1px solid {lighten(p.success, 0.1)}; font-weight: 650;
}}
QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid {p.border}; color: {p.text_dim}; }}
QPushButton[kind="ghost"]:hover {{ color: {p.text}; border-color: {p.border_hi}; background: {rgba(p.accent, 0.10)}; }}
QPushButton[kind="flat"] {{ background: transparent; border: none; color: {p.text_dim}; padding: 6px; }}
QPushButton[kind="flat"]:hover {{ color: {p.text}; background: {rgba(p.accent, 0.12)}; border-radius: {radius - 2}px; }}
QPushButton[kind="chip"] {{
    background: {p.surface_alt}; border: 1px solid {p.border}; border-radius: 14px;
    padding: 4px 11px; color: {p.text_dim}; font-size: {font_size - 1}px;
}}
QPushButton[kind="chip"]:checked, QPushButton[kind="chip"][active="true"] {{
    background: {rgba(p.accent, 0.20)}; border-color: {p.accent}; color: {p.text};
}}
#NavButton {{
    background: transparent;
    border: none;
    border-radius: {radius - 2}px;
    padding: {unit + 2}px {unit + 4}px;
    text-align: left;
    color: {p.text_dim};
    font-weight: 500;
}}
#NavButton:hover {{ color: {p.text}; background: {rgba(p.accent, 0.10)}; }}
#NavButton[active="true"] {{ color: {p.text}; font-weight: 650; background: {rgba(p.accent, 0.16)}; }}
#NavIndicator {{
    background: {p.accent};
    border-radius: 3px;
}}
#BrandMark {{ font-size: {font_size + 6}px; font-weight: 800; letter-spacing: 0.4px; }}

/* ----------------------------------------------------------------- inputs */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {{
    background: {p.bg_alt};
    border: 1px solid {p.border};
    border-radius: {radius - 4}px;
    padding: {unit - 2}px {unit}px;
    selection-background-color: {rgba(p.accent, 0.45)};
    selection-color: {p.text};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {p.accent};
    background: {_mix(p.bg_alt, p.surface, 0.5)};
}}
QLineEdit:disabled, QPlainTextEdit:disabled {{ color: {p.text_faint}; }}
QLineEdit[mono="true"], QPlainTextEdit[mono="true"] {{
    font-family: "Cascadia Mono", "Cascadia Code", Consolas, monospace;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {p.text_dim}; margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border_hi};
    border-radius: 10px;
    padding: 4px;
    selection-background-color: {rgba(p.accent, 0.25)};
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0px; border: none; }}
QCheckBox, QRadioButton {{ spacing: 8px; color: {p.text_dim}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 17px; height: 17px; border-radius: 5px;
    border: 1px solid {p.border_hi}; background: {p.bg_alt};
}}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {p.accent}; border-color: {p.accent};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {p.accent}; }}

/* ------------------------------------------------------------------ lists */
QListWidget, QListView, QTreeWidget, QTableWidget {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {radius}px;
    padding: 6px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item {{
    border-radius: {radius - 4}px;
    padding: {unit}px;
    margin: 2px 4px;
    color: {p.text_dim};
}}
QListWidget::item:hover {{ background: {rgba(p.accent, 0.10)}; color: {p.text}; }}
QListWidget::item:selected {{
    background: {rgba(p.accent, 0.20)};
    color: {p.text};
    border: 1px solid {rgba(p.accent, 0.55)};
}}
QHeaderView::section {{
    background: {p.surface_alt}; color: {p.text_dim}; border: none;
    border-bottom: 1px solid {p.border}; padding: 7px;
}}
QTableWidget::item {{ padding: 5px; }}

/* --------------------------------------------------------------- progress */
QProgressBar {{
    background: {p.bg_alt};
    border: 1px solid {p.border};
    border-radius: 8px;
    height: 12px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 7px; }}
QProgressBar[tone="success"]::chunk {{ background: {p.success}; }}
QProgressBar[tone="danger"]::chunk {{ background: {p.danger}; }}

/* --------------------------------------------------------------- scrollbars */
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {rgba(p.text_faint, 0.45)}; border-radius: 5px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {rgba(p.accent, 0.75)}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {rgba(p.text_faint, 0.45)}; border-radius: 5px; min-width: 32px; }}
QScrollBar::handle:horizontal:hover {{ background: {rgba(p.accent, 0.75)}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ----------------------------------------------------------------- console */
#Console, QPlainTextEdit#Console {{
    background: {p.log_bg};
    border: 1px solid {p.border};
    border-radius: {radius}px;
    font-family: "Cascadia Mono", "Cascadia Code", Consolas, monospace;
    font-size: {font_size - 1.5}px;
    padding: 8px;
}}
#ConsoleToolbar {{ background: transparent; }}

/* -------------------------------------------------------------------- tabs */
QTabWidget::pane {{ border: 1px solid {p.border}; border-radius: {radius}px; background: {p.surface}; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {p.text_dim};
    padding: 8px 14px; margin-right: 4px;
    border: 1px solid transparent; border-radius: 9px;
}}
QTabBar::tab:hover {{ color: {p.text}; background: {rgba(p.accent, 0.10)}; }}
QTabBar::tab:selected {{
    color: {p.text}; background: {rgba(p.accent, 0.18)}; border-color: {rgba(p.accent, 0.5)};
}}

/* -------------------------------------------------------------- menu / misc */
QMenu {{ background: {p.surface}; border: 1px solid {p.border_hi}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 7px; color: {p.text_dim}; }}
QMenu::item:selected {{ background: {rgba(p.accent, 0.22)}; color: {p.text}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 5px 8px; }}
QStatusBar {{ background: {p.bg_alt}; border-top: 1px solid {p.border}; color: {p.text_dim}; }}
QStatusBar::item {{ border: none; }}
QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 5px; color: {p.text_dim}; }}
QToolButton:hover {{ color: {p.text}; background: {rgba(p.accent, 0.12)}; }}
QToolBar {{ background: {p.bg_alt}; border: none; spacing: 4px; padding: 4px; }}
QSplitter::handle {{ background: transparent; width: 10px; }}
QSplitter::handle:hover {{ background: {rgba(p.accent, 0.25)}; }}
QGroupBox {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {radius}px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {p.text_dim}; }}
QSlider::groove:horizontal {{ height: 6px; background: {p.bg_alt}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {p.text}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: {p.accent_hi}; }}
QCalendarWidget QWidget {{ alternate-background-color: {p.surface_alt}; }}
#Toast {{
    background: {p.surface};
    border: 1px solid {p.border_hi};
    border-radius: {radius}px;
}}
#Toast[level="success"] {{ border-left: 4px solid {p.success}; }}
#Toast[level="error"] {{ border-left: 4px solid {p.danger}; }}
#Toast[level="warning"] {{ border-left: 4px solid {p.warning}; }}
#Toast[level="info"] {{ border-left: 4px solid {p.info}; }}
#Pill {{
    background: {rgba(p.accent, 0.16)};
    border: 1px solid {rgba(p.accent, 0.45)};
    border-radius: 11px;
    padding: 2px 10px;
    color: {p.text};
    font-size: {font_size - 1.5}px;
}}
#Pill[level="success"] {{ background: {rgba(p.success, 0.16)}; border-color: {rgba(p.success, 0.45)}; }}
#Pill[level="danger"] {{ background: {rgba(p.danger, 0.16)}; border-color: {rgba(p.danger, 0.45)}; }}
#Pill[level="warning"] {{ background: {rgba(p.warning, 0.16)}; border-color: {rgba(p.warning, 0.45)}; }}
#Pill[level="muted"] {{ background: {rgba(p.text_faint, 0.14)}; border-color: {rgba(p.text_faint, 0.35)}; color: {p.text_dim}; }}
#StepRow {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; }}
#StepRow:hover {{ border-color: {p.border_hi}; background: {p.surface_alt}; }}
#StepRow[state="running"] {{ border-color: {p.accent}; background: {rgba(p.accent, 0.12)}; }}
#StepRow[state="ok"] {{ border-color: {rgba(p.success, 0.6)}; }}
#StepRow[state="error"] {{ border-color: {rgba(p.danger, 0.7)}; background: {rgba(p.danger, 0.10)}; }}
#StepRow[state="retry"] {{ border-color: {rgba(p.warning, 0.7)}; }}
#Splash {{ background: {p.bg}; }}
#HeroGlyph {{ color: {p.accent}; font-size: 46px; font-weight: 800; }}
QFrame#DropZone {{ background: {p.bg_alt}; border: 2px dashed {p.border_hi}; border-radius: {radius}px; }}
QFrame#DropZone[drag="true"] {{ border-color: {p.accent}; background: {rgba(p.accent, 0.12)}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""


def apply_stylesheet(app, palette: Palette, *, compact: bool = False) -> None:
    app.setStyleSheet(build_stylesheet(palette, compact=compact))


def available_themes() -> list[tuple[str, str]]:
    return [(key, palette.label) for key, palette in PALETTES.items()]


def theme_accent_preview(key: str) -> list[str]:
    palette = get_palette(key)
    return [palette.accent, palette.success, palette.warning, palette.danger, palette.bg, palette.surface]


def widget_font(point_size: int = 13, *, bold: bool = False, mono: bool = False) -> Any:
    from PyQt6.QtGui import QFont

    family = "Cascadia Mono" if mono else "Segoe UI Variable Display"
    font = QFont(family, point_size)
    font.setBold(bold)
    return font
