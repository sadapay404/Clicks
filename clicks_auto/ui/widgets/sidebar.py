"""Animated navigation sidebar with a sliding active indicator."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..anim import MOTION, HoverGlow, animate_value, fade_in, stagger
from ..theme import Palette

NAV_ITEMS: list[tuple[str, str, str]] = [
    ("dashboard", "Dashboard", "\u25c9"),
    ("run", "Run", "\u25b6"),
    ("recorder", "Record Session", "\u25cf"),
    ("scripts", "Scripts", "\u2637"),
    ("schedules", "Schedules", "\u23f0"),
    ("history", "History", "\u21ba"),
    ("settings", "Settings", "\u2699"),
]


class NavButton(QPushButton):
    def __init__(self, key: str, label: str, glyph: str, parent: Optional[QWidget] = None,
                 *, accent: str = "#5b8cff") -> None:
        super().__init__(f"   {glyph}    {label}", parent)
        self.key = key
        self.setObjectName("NavButton")
        self.setProperty("active", "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(44)
        self._glow = HoverGlow(self, accent, alpha=32, radius=12)
        self._glow.lower()
        self.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        from PyQt6.QtCore import QEvent

        if obj is self:
            if event.type() == QEvent.Type.Enter:
                self._glow.animate_to(True)
            elif event.type() == QEvent.Type.Leave:
                self._glow.animate_to(False)
            elif event.type() == QEvent.Type.Resize:
                self._glow.setGeometry(0, 0, self.width(), self.height())
                self._glow.lower()
        return super().eventFilter(obj, event)

    def set_accent(self, accent: str) -> None:
        self._glow.set_color(accent)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        style = self.style()
        if style:
            style.unpolish(self)
            style.polish(self)


class Indicator(QFrame):
    """Coloured bar that glides to the active navigation item."""

    def __init__(self, parent: QWidget, accent: str) -> None:
        super().__init__(parent)
        self.setObjectName("NavIndicator")
        self.setFixedWidth(4)
        self._color = accent
        self._animation: Optional[QVariantAnimation] = None

    def set_accent(self, accent: str) -> None:
        self._color = accent

    def slide_to(self, y: int, height: int, *, animate: bool = True, duration: int = 260) -> None:
        if not animate or not MOTION.enabled:
            self.setGeometry(self.x(), y, self.width(), height)
            self.show()
            return
        start_y, start_h = self.y(), self.height()

        def apply(value) -> None:
            progress = float(value)
            self.setGeometry(
                self.x(),
                int(start_y + (y - start_y) * progress),
                self.width(),
                int(start_h + (height - start_h) * progress),
            )

        self._animation = animate_value(0.0, 1.0, duration, apply, easing_name="out", parent=self)


class Sidebar(QWidget):
    navigate = pyqtSignal(str)
    action_clicked = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None, *, palette: Palette, width: int = 232) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(width)
        self._palette = palette
        self._buttons: dict[str, NavButton] = {}
        self._active = "dashboard"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(6)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 0, 0, 0)
        brand_row.setSpacing(10)
        self.logo = QLabel("\u25ce")
        self.logo.setStyleSheet(f"color: {palette.accent}; font-size: 24px; font-weight: 800;")
        brand_row.addWidget(self.logo)
        brand_column = QVBoxLayout()
        brand_column.setSpacing(0)
        brand_column.setContentsMargins(0, 0, 0, 0)
        self.brand = QLabel("Clicks-Auto")
        self.brand.setObjectName("BrandMark")
        brand_column.addWidget(self.brand)
        self.tagline = QLabel("playback + recorder")
        self.tagline.setProperty("role", "faint")
        brand_column.addWidget(self.tagline)
        brand_row.addLayout(brand_column)
        brand_row.addStretch(1)
        layout.addLayout(brand_row)
        layout.addSpacing(14)

        self.indicator = Indicator(self, palette.accent)
        self.indicator.hide()

        self.group_label = QLabel("WORKSPACE")
        self.group_label.setProperty("role", "faint")
        self.group_label.setContentsMargins(8, 0, 0, 0)
        layout.addWidget(self.group_label)

        for key, label, glyph in NAV_ITEMS:
            button = NavButton(key, label, glyph, self, accent=palette.accent)
            button.clicked.connect(lambda _checked=False, k=key: self.activate(k))
            layout.addWidget(button)
            self._buttons[key] = button

        layout.addStretch(1)

        self.status_card = QFrame()
        self.status_card.setObjectName("Card")
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(12, 10, 12, 12)
        status_layout.setSpacing(6)
        self.status_title = QLabel("Ready")
        font = self.status_title.font()
        font.setBold(True)
        self.status_title.setFont(font)
        status_layout.addWidget(self.status_title)
        self.status_detail = QLabel("No browser running")
        self.status_detail.setProperty("role", "faint")
        self.status_detail.setWordWrap(True)
        status_layout.addWidget(self.status_detail)
        layout.addWidget(self.status_card)

        self.version_label = QLabel("")
        self.version_label.setProperty("role", "faint")
        self.version_label.setContentsMargins(8, 6, 0, 0)
        layout.addWidget(self.version_label)

        self._entrance_done = False

    # ------------------------------------------------------------------ api
    def set_version(self, text: str) -> None:
        self.version_label.setText(text)

    def set_status(self, title: str, detail: str = "", *, level: str = "info") -> None:
        self.status_title.setText(title)
        self.status_detail.setText(detail)
        color = {
            "info": self._palette.text,
            "success": self._palette.success,
            "warning": self._palette.warning,
            "error": self._palette.danger,
            "busy": self._palette.accent,
        }.get(level, self._palette.text)
        self.status_title.setStyleSheet(f"color: {color}; font-weight: 700;")

    def activate(self, key: str, *, animate: bool = True) -> None:
        if key not in self._buttons:
            return
        self._active = key
        for button_key, button in self._buttons.items():
            button.set_active(button_key == key)
        button = self._buttons[key]
        self.indicator.slide_to(button.y(), button.height(), animate=animate)
        self.indicator.show()
        if not animate:
            self.indicator.slide_to(button.y(), button.height(), animate=False)
        self.navigate.emit(key)

    def active(self) -> str:
        return self._active

    def set_active_key(self, key: str, *, animate: bool = True) -> None:
        """Highlight a page without emitting :attr:`navigate`."""
        if key not in self._buttons:
            return
        self._active = key
        for button_key, button in self._buttons.items():
            button.set_active(button_key == key)
        button = self._buttons[key]
        self.indicator.slide_to(button.y(), button.height(), animate=animate)
        self.indicator.show()
        self.indicator.raise_()

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.logo.setStyleSheet(f"color: {palette.accent}; font-size: 24px; font-weight: 800;")
        self.indicator.set_accent(palette.accent)
        for button in self._buttons.values():
            button.set_accent(palette.accent)
        self.set_status(self.status_title.text(), self.status_detail.text())

    def play_entrance(self) -> None:
        if self._entrance_done:
            return
        self._entrance_done = True
        widgets: list[QWidget] = [self.brand, self.tagline, self.group_label] + list(self._buttons.values())
        stagger(widgets, step=38, duration=240)
        fade_in(self.status_card, 320, delay=len(widgets) * 38)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        button = self._buttons.get(self._active)
        if button is not None:
            self.indicator.setGeometry(0, button.y(), self.indicator.width(), button.height())
            self.indicator.raise_()
