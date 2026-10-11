"""Shared, animated building blocks for every page."""

from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..anim import (
    AnimatedButtonMixin,
    HoverGlow,
    MOTION,
    animate_value,
    count_up,
    fade_in,
    fade_out,
    shimmer,
    stagger,
)
from ..theme import Palette


class Card(QFrame):
    """Rounded surface with an optional hover lift and click."""

    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None, *, tone: str = "base",
                 interactive: bool = False, padding: int = 16, spacing: int = 10,
                 palette: Optional[Palette] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("tone", tone)
        self.setProperty("interactive", "true" if interactive else "false")
        self._interactive = interactive
        self._palette = palette
        self._shadow: Optional[QGraphicsDropShadowEffect] = None
        self._glow_widget: Optional[HoverGlow] = None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(padding, padding, padding, padding)
        self.layout.setSpacing(spacing)
        if interactive:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._glow_widget = HoverGlow(self, (palette.accent if palette else "#5b8cff"),
                                          alpha=26, radius=14)
            self._glow_widget.lower()
            self.installEventFilter(self)

    # ------------------------------------------------------------------ motion
    def set_palette_ref(self, palette: Palette) -> None:
        self._palette = palette
        if self._glow_widget is not None:
            self._glow_widget.set_color(palette.accent)

    def attach_shadow(self, *, color: str = "#000000", blur: int = 26, alpha: int = 90,
                      offset: int = 8) -> None:
        effect = QGraphicsDropShadowEffect(self)
        shadow = QColor(color)
        shadow.setAlpha(alpha)
        effect.setColor(shadow)
        effect.setBlurRadius(blur)
        effect.setOffset(0, offset)
        self.setGraphicsEffect(effect)
        self._shadow = effect
        self._shadow_base = (blur, alpha, offset)

    def hover_lift(self, *, raise_by: int = 4) -> None:
        if self._shadow is None:
            return
        base_blur, base_alpha, base_offset = getattr(self, "_shadow_base", (26, 90, 8))
        self._lift_targets = (base_blur, base_alpha, base_offset, raise_by)

        def animate(entered: bool) -> None:
            target_blur = base_blur + (raise_by * 2 if entered else 0)
            target_alpha = min(210, base_alpha + (45 if entered else 0))
            target_offset = base_offset + (2 if entered else 0)
            start = (self._shadow.blurRadius(), self._shadow.color().alpha(), self._shadow.offset().y())
            color = self._shadow.color()

            def apply(value: Any) -> None:
                progress = max(0.0, min(1.0, float(value)))
                new_color = QColor(color)
                new_color.setAlpha(
                    int(start[1] + (target_alpha - start[1]) * progress)
                    if entered else int(start[1] + (target_alpha - start[1]) * progress)
                )
                self._shadow.setColor(new_color)
                self._shadow.setBlurRadius(start[0] + (target_blur - start[0]) * progress)
                self._shadow.setOffset(0, start[2] + (target_offset - start[2]) * progress)

            animate_value(0.0, 1.0, 170, apply, easing_name="out", parent=self)

        self._animate_shadow = animate

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self:
            if event.type() == QEvent.Type.Enter:
                if self._glow_widget:
                    self._glow_widget.animate_to(True)
                if hasattr(self, "_animate_shadow"):
                    self._animate_shadow(True)
            elif event.type() == QEvent.Type.Leave:
                if self._glow_widget:
                    self._glow_widget.animate_to(False)
                if hasattr(self, "_animate_shadow"):
                    self._animate_shadow(False)
            elif event.type() == QEvent.Type.MouseButtonRelease and self._interactive:
                if self.rect().contains(event.position().toPoint()):
                    self.clicked.emit()
            elif event.type() == QEvent.Type.Resize and self._glow_widget:
                self._glow_widget.setGeometry(0, 0, self.width(), self.height())
                self._glow_widget.lower()
        return super().eventFilter(obj, event)


class AnimatedButton(AnimatedButtonMixin, QPushButton):
    """Push button with hover wash + ripple (works with the global stylesheet)."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None, *,
                 kind: str = "default", accent: str = "#ffffff", icon_text: str = "",
                 tooltip: str = "", radius: int = 10, glow_alpha: int = 44,
                 ripple_alpha: int = 80) -> None:
        super().__init__(text, parent)
        self.setProperty("kind", kind)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_text:
            self.setText(f"{icon_text}  {text}" if text else icon_text)
        if tooltip:
            self.setToolTip(tooltip)
        self._install_motion(accent=accent, glow_alpha=glow_alpha, ripple_alpha=ripple_alpha, radius=radius)
        self.setMinimumHeight(36)

    def set_accent(self, accent: str) -> None:
        self._glow.set_color(accent)
        self._ripple.set_color(accent)


class IconButton(QToolButton):
    """Square, flat icon-ish button used in toolbars."""

    def __init__(self, glyph: str = "", parent: Optional[QWidget] = None, *, tooltip: str = "",
                 size: int = 34) -> None:
        super().__init__(parent)
        self.setText(glyph)
        self.setToolTip(tooltip or glyph)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(size, size)
        font = self.font()
        font.setPointSize(max(11, int(size * 0.42)))
        self.setFont(font)


class ToggleSwitch(QAbstractButton):
    """Painted sliding switch with an animated knob."""

    def __init__(self, parent: Optional[QWidget] = None, *, checked: bool = False,
                 accent: str = "#5b8cff", track_off: str = "#3a4260") -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._accent = QColor(accent)
        self._track_off = QColor(track_off)
        self._position = 1.0 if checked else 0.0
        self._animation: Optional[QVariantAnimation] = None
        self.setFixedSize(46, 26)
        self.toggled.connect(self._animate)

    def set_colors(self, accent: str, track_off: str) -> None:
        self._accent = QColor(accent)
        self._track_off = QColor(track_off)
        self.update()

    def _animate(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        self._animation = animate_value(
            self._position, target, 190,
            lambda value: self._set_position(float(value)),
            easing_name="back", parent=self,
        )

    def _set_position(self, value: float) -> None:
        self._position = value
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(46, 26)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        track = QColor(self._track_off)
        if self._position > 0:
            track = QColor(
                int(self._track_off.red() + (self._accent.red() - self._track_off.red()) * self._position),
                int(self._track_off.green() + (self._accent.green() - self._track_off.green()) * self._position),
                int(self._track_off.blue() + (self._accent.blue() - self._track_off.blue()) * self._position),
            )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(rect), radius, radius)

        knob_size = rect.height() - 6
        travel = rect.width() - knob_size - 6
        knob_x = 3 + travel * self._position
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(knob_x, 3, knob_size, knob_size))
        painter.end()


class Pill(QLabel):
    """Small rounded status chip."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None, *, level: str = "info") -> None:
        super().__init__(text, parent)
        self.setObjectName("Pill")
        self.setProperty("level", level)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_level(self, level: str, text: Optional[str] = None) -> None:
        self.setProperty("level", level)
        if text is not None:
            self.setText(text)
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)


Badge = Pill


class _ThemedLabel(QLabel):
    """Base for the typographic helpers below."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None, *, role: str,
                 dim: bool = False, wrap: bool = False) -> None:
        super().__init__(text, parent)
        self.setProperty("role", role)
        if dim:
            self.setProperty("dim", "true")
        self.setWordWrap(wrap)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)


class TitleLabel(_ThemedLabel):
    """Large heading used at the top of cards and dialogs."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None, *,
                 level: int = 1, dim: bool = False, wrap: bool = True) -> None:
        level = max(1, min(3, int(level)))
        super().__init__(text, parent, role=f"h{level}", dim=dim, wrap=wrap)


class SubtitleLabel(_ThemedLabel):
    """Smaller, muted supporting text."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None, *,
                 faint: bool = False, wrap: bool = True) -> None:
        super().__init__(text, parent, role="faint" if faint else "muted", wrap=wrap)


class Divider(QFrame):
    def __init__(self, parent: Optional[QWidget] = None, *, horizontal: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        if horizontal:
            self.setFixedHeight(1)
        else:
            self.setFixedWidth(1)


class SectionHeader(QWidget):
    """Title + subtitle + optional right hand widget."""

    def __init__(self, title: str, subtitle: str = "", parent: Optional[QWidget] = None,
                 *, right: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("PageTitle")
        column.addWidget(self.title)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("PageSubtitle")
        self.subtitle.setVisible(bool(subtitle))
        column.addWidget(self.subtitle)
        layout.addLayout(column)
        layout.addStretch(1)
        self.right = right
        if right is not None:
            layout.addWidget(right)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))


class StatTile(Card):
    """Dashboard metric with an animated counter."""

    def __init__(self, label: str, value: str = "0", glyph: str = "", parent: Optional[QWidget] = None,
                 *, accent: str = "#5b8cff", palette: Optional[Palette] = None) -> None:
        super().__init__(parent, palette=palette, padding=14, spacing=6, interactive=True)
        self.setMinimumHeight(92)
        self.attach_shadow(color="#000000", blur=22, alpha=70, offset=6)
        self.hover_lift(raise_by=3)
        self._numeric = _parse_number(value)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self.glyph = QLabel(glyph)
        self.glyph.setStyleSheet(f"color: {accent}; font-size: 19px; font-weight: 700;")
        self.glyph.setVisible(bool(glyph))
        top.addWidget(self.glyph)
        top.addStretch(1)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        top.addWidget(self.value_label)
        self.layout.addLayout(top)
        self.label = QLabel(label.upper())
        self.label.setObjectName("StatLabel")
        self.layout.addWidget(self.label)
        self.layout.addStretch(1)
        self._hint = QLabel("")
        self._hint.setProperty("role", "faint")
        self._hint.setVisible(False)
        self.layout.addWidget(self._hint)

    def set_value(self, value: str, *, animate: bool = True) -> None:
        target = _parse_number(value)
        if target is None or self._numeric is None or not animate:
            self.value_label.setText(value)
        else:
            suffix = _number_suffix(value)
            prefix = _number_prefix(value)
            decimals = _decimals(value)
            count_up(
                self.value_label, self._numeric, target, 700,
                formatter=lambda v: f"{prefix}{v:,.{decimals}f}{suffix}",
            )
        self._numeric = target

    def set_hint(self, text: str) -> None:
        self._hint.setText(text)
        self._hint.setVisible(bool(text))

    def set_accent(self, accent: str) -> None:
        self.glyph.setStyleSheet(f"color: {accent}; font-size: 19px; font-weight: 700;")


class AnimatedProgressBar(QProgressBar):
    """Progress bar with eased value changes and an optional shimmer sweep."""

    def __init__(self, parent: Optional[QWidget] = None, *, tone: str = "accent",
                 show_text: bool = False, accent: str = "") -> None:
        super().__init__(parent)
        self.setProperty("tone", tone)
        self.setTextVisible(show_text)
        self.setFixedHeight(12)
        self._value_anim: Optional[QVariantAnimation] = None
        self._shimmer_timer: Optional[QTimer] = None
        self._shimmer_pos = -0.4
        self._indeterminate = False
        self._accent = accent
        if accent:
            self.setProperty("shimmer_accent", accent)
        self.setProperty("shimmer", self._shimmer_pos)

    def set_shimmer_accent(self, accent: str) -> None:
        """Tint the indeterminate shimmer sweep (empty string = white)."""
        self._accent = accent
        if accent:
            self.setProperty("shimmer_accent", accent)
        self.update()

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        style = self.style()
        if style:
            style.unpolish(self)
            style.polish(self)

    def set_value_animated(self, value: int, duration: int = 420) -> None:
        value = max(self.minimum(), min(self.maximum(), int(value)))
        self._value_anim = animate_value(self.value(), value, duration,
                                         lambda v: self.setValue(int(v)), easing_name="out", parent=self)

    def start_indeterminate(self, label: str = "") -> None:
        self._indeterminate = True
        self.setTextVisible(bool(label))
        if label:
            self.setFormat(label)
        self.setRange(0, 0)
        if self._shimmer_timer is None:
            self._shimmer_timer = shimmer(self, accent=self._accent)
        self._shimmer_timer.start(40)

    def stop_indeterminate(self, *, tone: str = "accent", value: int = 0) -> None:
        self._indeterminate = False
        self.setRange(0, 100)
        self.setValue(value)
        self.set_tone(tone)
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not MOTION.enabled:
            return
        position = float(self.property("shimmer") or -1.0)
        if position < -0.2 and not self._indeterminate:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 7, 7)
        painter.setClipPath(path)
        width = int(self.width() * 0.28)
        x = int(self.width() * position)
        tint = self.property("shimmer_accent")
        gradient_color = QColor(tint) if tint else QColor("#ffffff")
        gradient_color.setAlpha(56 if tint else 38)
        painter.setBrush(gradient_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(x, 0, width, self.height())
        painter.end()


class SearchBox(QLineEdit):
    def __init__(self, placeholder: str = "Search...", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumHeight(34)


class SegmentControl(QWidget):
    """Animated segmented control (chips with a sliding highlight)."""

    changed = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str]], parent: Optional[QWidget] = None,
                 *, accent: str = "#5b8cff") -> None:
        super().__init__(parent)
        self._accent = accent
        self._buttons: list[QPushButton] = []
        self._indicator = HoverGlow(self, accent, alpha=70, radius=12)
        self._indicator.lower()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        for key, label in options:
            button = QPushButton(label)
            button.setProperty("kind", "flat")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setCheckable(True)
            button.setMinimumHeight(30)
            button.clicked.connect(lambda _checked, k=key: self.set_current(k, emit=True))
            layout.addWidget(button)
            self._buttons.append(button)
        self._keys = [key for key, _ in options]
        self._current = self._keys[0] if self._keys else ""
        self._buttons[0].setChecked(True) if self._buttons else None
        self._indicator.setGeometry(0, 0, 0, 0)

    def current(self) -> str:
        return self._current

    def set_current(self, key: str, *, emit: bool = False) -> None:
        if key not in self._keys:
            return
        self._current = key
        target_button = None
        for index, button in enumerate(self._buttons):
            checked = self._keys[index] == key
            button.setChecked(checked)
            if checked:
                target_button = button
        if target_button is not None:
            self._slide_indicator(target_button)
        if emit:
            self.changed.emit(key)

    def _slide_indicator(self, button: QPushButton) -> None:
        target = button.geometry()
        start = self._indicator.geometry()
        self._indicator.raise_()
        self._indicator.setVisible(True)

        def apply(value: Any) -> None:
            progress = float(value)
            x = int(start.x() + (target.x() - start.x()) * progress)
            y = int(start.y() + (target.y() - start.y()) * progress)
            w = int(start.width() + (target.width() - start.width()) * progress)
            h = int(start.height() + (target.height() - start.height()) * progress)
            self._indicator.setGeometry(x, y, w, h)

        if start.width() == 0:
            apply(1.0)
        else:
            animate_value(0.0, 1.0, 220, apply, easing_name="out", parent=self)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        current = next((b for i, b in enumerate(self._buttons) if self._keys[i] == self._current), None)
        if current is not None:
            self._indicator.setGeometry(current.geometry())
            self._indicator.setVisible(True)


class KeyValueRow(QWidget):
    def __init__(self, key: str, value: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(10)
        self.key = QLabel(key)
        self.key.setProperty("role", "muted")
        self.key.setMinimumWidth(150)
        self.value = QLabel(value)
        self.value.setWordWrap(True)
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.key)
        layout.addWidget(self.value, 1)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


class EmptyState(QWidget):
    def __init__(self, title: str, subtitle: str = "", glyph: str = "\u25cc",
                 parent: Optional[QWidget] = None, *, action_text: str = "",
                 on_action: Optional[Callable[[], None]] = None, accent: str = "#5b8cff") -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 40, 30, 40)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.glyph = QLabel(glyph)
        self.glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.glyph.setStyleSheet(f"color: {accent}; font-size: 44px;")
        layout.addWidget(self.glyph)
        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.title.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        self.title.setFont(font)
        layout.addWidget(self.title)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setProperty("role", "muted")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        layout.addWidget(self.subtitle)
        self.action: Optional[AnimatedButton] = None
        if action_text:
            self.action = AnimatedButton(action_text, kind="primary", accent=accent)
            if on_action:
                self.action.clicked.connect(on_action)
            layout.addWidget(self.action, alignment=Qt.AlignmentFlag.AlignCenter)


class ScrollPage(QWidget):
    """Base class for a page: smooth scrolling content + entry animation."""

    def __init__(self, parent: Optional[QWidget] = None, *, margin: int = 26) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        from ..anim import SmoothScrollArea

        self.scroll = SmoothScrollArea(self)
        self.content = QWidget()
        self.content.setObjectName("PageContent")
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(margin, margin, margin, margin)
        self.body.setSpacing(18)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if MOTION.enabled:
            fade_in(self.content, 240)
            children = [
                self.body.itemAt(i).widget()
                for i in range(min(6, self.body.count()))
                if self.body.itemAt(i).widget() is not None
            ]
            if children:
                stagger(children, step=40, duration=220)


# --------------------------------------------------------------------- toasts


class Toast(QFrame):
    closed = pyqtSignal(object)

    def __init__(self, message: str, parent: QWidget, *, level: str = "info",
                 title: str = "", duration: int = 4200, accent: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("level", level)
        self.level = level
        self._duration = duration
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 12, 11)
        layout.setSpacing(10)
        glyph = {"success": "\u2713", "error": "\u26a0", "warning": "\u26a1", "info": "\u2139"}.get(level, "\u2139")
        self.icon = QLabel(glyph)
        color = accent or {"success": "#37d399", "error": "#ff6188", "warning": "#ffb454", "info": "#59c2ff"}.get(level, accent)
        self.icon.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: 700;")
        layout.addWidget(self.icon, alignment=Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        if title:
            head = QLabel(title)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            column.addWidget(head)
        body = QLabel(message)
        body.setWordWrap(True)
        body.setMaximumWidth(320)
        body.setProperty("role", "muted")
        column.addWidget(body)
        layout.addLayout(column)
        self.setMinimumWidth(260)
        self.setMaximumWidth(380)
        self.adjustSize()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.dismiss())
        if duration:
            self._timer.start(duration)

    def dismiss(self) -> None:
        self._timer.stop()
        fade_out(self, 200, hide=True, finished=lambda: self.closed.emit(self))


class ToastManager:
    """Owns the toast stack and animates toasts in/out on the right edge."""

    def __init__(self, host: QWidget, *, palette: Optional[Palette] = None) -> None:
        self.host = host
        self.palette = palette
        self.toasts: list[Toast] = []
        self.margin = 20
        self.top_offset = 66
        self.spacing = 10

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette

    def show(self, message: str, *, level: str = "info", title: str = "",
             duration: int = 4200) -> Toast:
        toast = Toast(message, self.host, level=level, title=title, duration=duration,
                      accent=self.palette.accent if self.palette else "")
        toast.closed.connect(self._remove)
        self.toasts.append(toast)
        toast.show()
        toast.adjustSize()
        self._reposition(animate_from_right=True)
        return toast

    def success(self, message: str, title: str = "") -> Toast:
        return self.show(message, level="success", title=title)

    def error(self, message: str, title: str = "Something went wrong") -> Toast:
        return self.show(message, level="error", title=title, duration=6500)

    def warning(self, message: str, title: str = "") -> Toast:
        return self.show(message, level="warning", title=title, duration=5200)

    def info(self, message: str, title: str = "") -> Toast:
        return self.show(message, level="info", title=title)

    def _remove(self, toast: Toast) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
        toast.deleteLater()
        self._reposition()

    def _reposition(self, *, animate_from_right: bool = False) -> None:
        if not self.toasts:
            return
        y = self.top_offset + self.margin
        for toast in self.toasts:
            toast.adjustSize()
            width = min(toast.width(), 380)
            height = toast.height()
            x = self.host.width() - width - self.margin
            if animate_from_right and toast is self.toasts[-1]:
                toast.move(self.host.width() + 10, y)
            target = QPoint(x, y)
            start = toast.pos()
            toast.raise_()
            if MOTION.enabled:
                animate_value(0.0, 1.0, 260,
                              lambda v, t=toast, s=start, e=target: t.move(
                                  int(s.x() + (e.x() - s.x()) * v), int(s.y() + (e.y() - s.y()) * v)
                              ),
                              easing_name="out", parent=toast)
                if animate_from_right and toast is self.toasts[-1]:
                    fade_in(toast, 240)
            else:
                toast.move(target)
            y += height + self.spacing


def _parse_number(text: str) -> Optional[float]:
    cleaned = "".join(ch for ch in str(text) if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _number_suffix(text: str) -> str:
    stripped = str(text).rstrip()
    while stripped and (stripped[-1].isdigit() or stripped[-1] in ".,"):
        stripped = stripped[:-1]
    return stripped if len(stripped) <= 3 else ""


def _number_prefix(text: str) -> str:
    out = []
    for ch in str(text):
        if ch.isdigit() or ch in ".-":
            break
        out.append(ch)
    prefix = "".join(out)
    return prefix if len(prefix) <= 3 else ""


def _decimals(text: str) -> int:
    text = str(text)
    if "." in text:
        return min(2, len(text.split(".")[-1]))
    return 0

