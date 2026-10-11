"""Animation toolkit.

A small, dependency free collection of helpers that give the whole app
consistent, tasteful motion: fades, slides, colour tweens, counters, ripples,
smooth scrolling and page transitions.  Everything respects the user's
"animations" / "speed" preferences through :class:`Motion`.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QScrollArea,
    QStackedWidget,
    QWidget,
)

EASINGS: dict[str, QEasingCurve.Type] = {
    "linear": QEasingCurve.Type.Linear,
    "in": QEasingCurve.Type.InCubic,
    "out": QEasingCurve.Type.OutCubic,
    "in_out": QEasingCurve.Type.InOutCubic,
    "back": QEasingCurve.Type.OutBack,
    "elastic": QEasingCurve.Type.OutElastic,
    "bounce": QEasingCurve.Type.OutBounce,
    "quad_out": QEasingCurve.Type.OutQuad,
    "expo_out": QEasingCurve.Type.OutExpo,
}


def easing(name: str | QEasingCurve.Type) -> QEasingCurve.Type:
    if isinstance(name, QEasingCurve.Type):
        return name
    return EASINGS.get(str(name), QEasingCurve.Type.OutCubic)


# --------------------------------------------------------------------------


class Motion(QObject):
    """Global animation preferences (kept in sync with the settings)."""

    changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.enabled = True
        self.speed = 1.0
        self.reduce_motion = False

    def update_from(self, ui_settings: Any) -> None:
        self.enabled = bool(getattr(ui_settings, "animations", True))
        self.speed = float(getattr(ui_settings, "animation_speed", 1.0) or 1.0)
        self.reduce_motion = bool(getattr(ui_settings, "reduce_motion", False))
        try:
            self.changed.emit()
        except RuntimeError:
            # The C++ object was torn down (a fresh QApplication, or shutdown).
            revive_motion()

    def duration(self, ms: int) -> int:
        if not self.enabled or self.reduce_motion:
            return 1
        return max(1, int(ms / max(0.25, min(4.0, self.speed))))


MOTION = Motion()


def motion_alive() -> bool:
    """``True`` while the global :data:`MOTION` singleton still has a C++ object."""
    try:
        from PyQt6 import sip
    except Exception:  # pragma: no cover - PyQt6 always ships sip
        return True
    return not sip.isdeleted(MOTION)


def revive_motion() -> Motion:
    """Recreate the global motion singleton after a Qt application tear down."""
    global MOTION
    if motion_alive():
        return MOTION
    MOTION = Motion()
    return MOTION


def _alive(obj: Any) -> bool:
    """``True`` when the C++ object behind ``obj`` has not been destroyed."""
    if obj is None:
        return False
    try:
        from PyQt6 import sip
    except Exception:  # pragma: no cover
        return True
    try:
        return not sip.isdeleted(obj)
    except Exception:  # pragma: no cover - not a wrapped Qt object
        return True


def _defer_start(animation: QPropertyAnimation, widget: QWidget, delay: int) -> None:
    """Start ``animation`` after ``delay`` ms unless ``widget`` went away."""
    def _start() -> None:
        if _alive(widget) and _alive(animation):
            animation.start()

    if delay:
        QTimer.singleShot(MOTION.duration(delay), _start)
    else:
        _start()


def _keep(widget: QWidget, animation: QObject) -> QObject:
    try:
        animation.setParent(widget)
    except RuntimeError:
        # The widget was destroyed while the animation was being created.
        return animation
    return animation


# ------------------------------------------------------------------ fades


def fade(widget: QWidget, start: float, end: float, duration: int = 220,
         *, delay: int = 0, easing_name: str = "out",
         finished: Optional[Callable[[], None]] = None,
         keep_effect: bool = True) -> QPropertyAnimation:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    widget.setVisible(True)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setStartValue(float(start))
    animation.setEndValue(float(end))
    animation.setDuration(MOTION.duration(duration))
    animation.setEasingCurve(easing(easing_name))

    def _done() -> None:
        if _alive(widget):
            if not keep_effect and end >= 1.0:
                widget.setGraphicsEffect(None)
        if finished and _alive(widget):
            finished()

    animation.finished.connect(_done)
    _defer_start(animation, widget, delay)
    return _keep(widget, animation)


def fade_in(widget: QWidget, duration: int = 220, *, delay: int = 0,
            easing_name: str = "out", block_input: bool = False) -> None:
    """Fade a widget in and drop the opacity effect once it is fully visible."""
    if block_input:
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    effect.setOpacity(0.0)
    widget.setVisible(True)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setDuration(MOTION.duration(duration))
    animation.setEasingCurve(easing(easing_name))

    def _cleanup() -> None:
        # A leftover opacity effect forces the whole subtree through a pixmap
        # and can make text look blurry, so remove it when we are done.
        if not (_alive(widget) and _alive(effect)):
            return
        if effect.opacity() >= 0.999:
            widget.setGraphicsEffect(None)

    animation.finished.connect(_cleanup)
    _defer_start(animation, widget, delay)
    _keep(widget, animation)


def fade_out(widget: QWidget, duration: int = 180, *, hide: bool = True,
             finished: Optional[Callable[[], None]] = None) -> None:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        effect.setOpacity(1.0)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setStartValue(effect.opacity())
    animation.setEndValue(0.0)
    animation.setDuration(MOTION.duration(duration))
    animation.setEasingCurve(easing("in"))

    def _done() -> None:
        if not _alive(widget):
            return
        if hide:
            widget.setVisible(False)
        widget.setGraphicsEffect(None)
        if finished:
            finished()

    animation.finished.connect(_done)
    _defer_start(animation, widget, 0)
    _keep(widget, animation)


def cross_fade(widget: QWidget, duration: int = 260) -> None:
    """Quick dip-to-transparent-and-back, used for theme changes."""
    fade(widget, 1.0, 0.0, duration // 2, easing_name="in",
         finished=lambda: fade(widget, 0.0, 1.0, duration // 2, easing_name="out"))


def reveal_height(widget: QWidget, duration: int = 260, *, delay: int = 0,
                  fade_too: bool = True) -> None:
    """Layout-safe "grow into place" reveal used for cards and rows."""
    target = widget.sizeHint().height() or widget.minimumHeight() or 40
    widget.setMaximumHeight(0)
    if fade_too:
        fade_in(widget, duration, delay=delay)
    animation = QPropertyAnimation(widget, b"maximumHeight", widget)
    animation.setStartValue(0)
    animation.setEndValue(target)
    animation.setDuration(MOTION.duration(duration))
    animation.setEasingCurve(easing("out"))

    def _done() -> None:
        if _alive(widget):
            widget.setMaximumHeight(16_777_215)

    animation.finished.connect(_done)
    _defer_start(animation, widget, delay)
    _keep(widget, animation)


def stagger(widgets: list[QWidget], *, step: int = 45, duration: int = 260,
            base_delay: int = 0) -> None:
    """Reveal a list of widgets one after another."""
    for index, widget in enumerate(widgets):
        fade_in(widget, duration, delay=base_delay + index * step)


# ------------------------------------------------------------- value tweens


def animate_value(start: float, end: float, duration: int, on_value: Callable[[Any], None],
                  *, easing_name: str = "out", parent: Optional[QObject] = None,
                  finished: Optional[Callable[[], None]] = None,
                  dtype: str = "float") -> QVariantAnimation:
    animation = QVariantAnimation(parent)
    animation.setStartValue(float(start) if dtype != "color" else start)
    animation.setEndValue(float(end) if dtype != "color" else end)
    animation.setDuration(MOTION.duration(duration))
    animation.setEasingCurve(easing(easing_name))
    animation.valueChanged.connect(on_value)
    if finished:
        animation.finished.connect(finished)
    animation.start()
    return animation


def tween_color(widget: QWidget, start: QColor, end: QColor, duration: int,
                apply: Callable[[QColor], None], *, easing_name: str = "out") -> QVariantAnimation:
    return animate_value(start, end, duration, lambda value: apply(value),
                         easing_name=easing_name, parent=widget, dtype="color")


def count_up(label, start: float, end: float, duration: int = 700,
             *, formatter: Optional[Callable[[float], str]] = None,
             easing_name: str = "expo_out") -> None:
    fmt = formatter or (lambda value: f"{int(round(value)):,}")

    def apply(value: Any) -> None:
        label.setText(fmt(float(value)))

    animate_value(start, end, duration, apply, easing_name=easing_name, parent=label)


def pulse(widget: QWidget, *, low: float = 0.35, high: float = 1.0, period: int = 900) -> QPropertyAnimation:
    """Endless opacity pulse (recording indicator, live dots)."""
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setStartValue(high)
    animation.setKeyValueAt(0.5, low)
    animation.setEndValue(high)
    animation.setDuration(MOTION.duration(period))
    animation.setLoopCount(-1)
    animation.start()
    return _keep(widget, animation)


def stop_pulse(animation: Optional[QPropertyAnimation], widget: QWidget) -> None:
    if animation is not None:
        animation.stop()
    if widget.graphicsEffect() is not None:
        widget.setGraphicsEffect(None)


def glow(widget: QWidget, *, color: str = "#5b8cff", radius: int = 22, alpha: int = 130,
         offset: int = 0, animate_to: Optional[dict] = None) -> QGraphicsDropShadowEffect:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsDropShadowEffect):
        effect = QGraphicsDropShadowEffect(widget)
        widget.setGraphicsEffect(effect)
    shadow_color = QColor(color)
    shadow_color.setAlpha(alpha)
    effect.setColor(shadow_color)
    effect.setBlurRadius(radius)
    effect.setOffset(0, offset)
    if animate_to:
        target_radius = animate_to.get("radius", radius + 14)
        target_alpha = animate_to.get("alpha", min(255, alpha + 60))
        target_offset = animate_to.get("offset", offset + 3)
        start_color = QColor(shadow_color)
        end_color = QColor(shadow_color)
        end_color.setAlpha(target_alpha)

        def apply(value: Any) -> None:
            effect.setColor(value)
            progress = 0.0
            if target_radius != radius:
                progress = (value.alpha() - alpha) / max(1, (target_alpha - alpha))
            effect.setBlurRadius(radius + (target_radius - radius) * max(0.0, min(1.0, progress)))
            effect.setOffset(0, offset + (target_offset - offset) * max(0.0, min(1.0, progress)))

        animate_value(start_color, end_color, 180, apply, parent=widget, dtype="color")
    return effect


def shimmer(progress_bar: QWidget, *, accent: str = "#5b8cff", period: int = 1400) -> QTimer:
    """Left-to-right light sweep over a progress bar (pure paint, no GIF)."""
    timer = QTimer(progress_bar)
    state = {"offset": -0.4}

    def step() -> None:
        state["offset"] += 0.035
        if state["offset"] > 1.4:
            state["offset"] = -0.4
        progress_bar.setProperty("shimmer", state["offset"])
        progress_bar.update()

    timer.timeout.connect(step)
    if MOTION.enabled:
        timer.start(MOTION.duration(period) // 14 or 40)
    return timer


# --------------------------------------------------------------- transitions


class AnimatedStackedWidget(QStackedWidget):
    """A QStackedWidget whose page changes slide + fade smoothly."""

    transition_finished = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._duration = 300
        self._direction = 1
        self._animating = False
        self._current_animation: Optional[QPropertyAnimation] = None

    def set_duration(self, ms: int) -> None:
        self._duration = ms

    def slide_to(self, index: int, *, direction: Optional[int] = None, duration: Optional[int] = None) -> None:
        if index == self.currentIndex() or index < 0 or index >= self.count():
            return
        width = max(1, self.width())
        if direction is None:
            direction = 1 if index > self.currentIndex() else -1
        duration = MOTION.duration(duration or self._duration)
        if not MOTION.enabled or duration <= 1:
            self.setCurrentIndex(index)
            self.transition_finished.emit(index)
            return

        current = self.currentWidget()
        target = self.widget(index)
        target.setGeometry(0, 0, width, self.height())
        target.setVisible(True)
        target.raise_()
        target.move(direction * width, 0)
        fade_in(target, max(120, duration // 2))
        self._animating = True

        anim_target = QPropertyAnimation(target, b"pos", self)
        anim_target.setDuration(duration)
        anim_target.setStartValue(QPoint(direction * width, 0))
        anim_target.setEndValue(QPoint(0, 0))
        anim_target.setEasingCurve(easing("out"))

        if current is not None and current is not target:
            anim_current = QPropertyAnimation(current, b"pos", self)
            anim_current.setDuration(duration)
            anim_current.setStartValue(QPoint(0, 0))
            anim_current.setEndValue(QPoint(-direction * width // 4, 0))
            anim_current.setEasingCurve(easing("out"))
            anim_current.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        def _done() -> None:
            self._animating = False
            self.setCurrentIndex(index)
            target.move(0, 0)
            self.transition_finished.emit(index)

        anim_target.finished.connect(_done)
        anim_target.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._current_animation = anim_target

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._animating:
            widget = self.currentWidget()
            if widget is not None:
                widget.setGeometry(0, 0, self.width(), self.height())


# ---------------------------------------------------------------- scrolling


class SmoothScrollArea(QScrollArea):
    """Scroll area with eased wheel scrolling - every scroll is animated."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._animation: Optional[QVariantAnimation] = None
        self._target = 0
        self.verticalScrollBar().setSingleStep(28)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if not MOTION.enabled:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        bar = self.verticalScrollBar()
        self._target = max(bar.minimum(), min(bar.maximum(), self._target + int(-delta * 1.15)))
        if self._animation and self._animation.state() == QVariantAnimation.State.Running:
            return
        self._animation = animate_value(
            bar.value(), self._target, 320,
            lambda value: bar.setValue(int(value)), easing_name="expo_out", parent=self,
        )
        event.accept()

    def animate_to(self, value: int, duration: int = 420) -> None:
        bar = self.verticalScrollBar()
        self._target = value
        animate_value(bar.value(), value, duration, lambda v: bar.setValue(int(v)),
                      easing_name="expo_out", parent=self)

    def scroll_to_bottom(self, animated: bool = True) -> None:
        bar = self.verticalScrollBar()
        if animated and MOTION.enabled:
            self.animate_to(bar.maximum(), 260)
        else:
            bar.setValue(bar.maximum())


def smooth_autoscroll(text_edit, *, animated: bool = True) -> None:
    """Keep a console pinned to the bottom with a glide instead of a jump."""
    bar = text_edit.verticalScrollBar()
    if animated and MOTION.enabled:
        animate_value(bar.value(), bar.maximum(), 200, lambda v: bar.setValue(int(v)),
                      easing_name="out", parent=text_edit)
    else:
        bar.setValue(bar.maximum())


# ------------------------------------------------------------------- ripple


class RippleOverlay(QWidget):
    """Expanding circle painted on top of a button when it is clicked."""

    def __init__(self, parent: QWidget, color: str = "#ffffff") -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._color = QColor(color)
        self._ripples: list[dict[str, Any]] = []
        self._radius = 16

    def set_color(self, color: str) -> None:
        self._color = QColor(color)

    def set_corner_radius(self, radius: int) -> None:
        self._radius = radius

    def start(self, center: QPoint, *, max_alpha: int = 110) -> None:
        ripple = {"center": center, "progress": 0.0, "alpha": max_alpha}
        self._ripples.append(ripple)
        animate_value(0.0, 1.0, 460, lambda value, r=ripple: self._update_ripple(r, float(value)),
                      easing_name="out", parent=self)
        self.update()

    def _update_ripple(self, ripple: dict[str, Any], value: float) -> None:
        ripple["progress"] = value
        if value >= 1.0 and ripple in self._ripples:
            self._ripples.remove(ripple)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._ripples:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), self._radius, self._radius)
        painter.setClipPath(path)
        for ripple in self._ripples:
            progress = ripple["progress"]
            radius = int(progress * max(self.width(), self.height()) * 1.15) + 4
            alpha = int(ripple["alpha"] * (1.0 - progress))
            if alpha <= 0:
                continue
            color = QColor(self._color)
            color.setAlpha(max(0, min(255, alpha)))
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(ripple["center"], radius, radius)
        painter.end()


class HoverGlow(QWidget):
    """Faint accent wash that fades in when the pointer enters a widget."""

    def __init__(self, parent: QWidget, color: str, *, alpha: int = 40, radius: int = 10,
                 side: str = "all", thickness: int = 0) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._color = QColor(color)
        self._max_alpha = alpha
        self._alpha = 0.0
        self._radius = radius
        self._side = side
        self._thickness = thickness
        self.setGeometry(parent.rect())

    def set_color(self, color: str) -> None:
        self._color = QColor(color)

    def set_radius(self, radius: int) -> None:
        self._radius = radius

    def animate_to(self, visible: bool) -> None:
        target = float(self._max_alpha if visible else 0)
        if abs(target - self._alpha) < 1:
            return
        animate_value(self._alpha, target, 180, lambda v: self._set_alpha(float(v)),
                      easing_name="out", parent=self)

    def _set_alpha(self, value: float) -> None:
        self._alpha = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._alpha <= 0.5:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._color)
        color.setAlpha(int(self._alpha))
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = self.rect()
        if self._side == "left" and self._thickness:
            width = int(rect.width() * 0.10) + self._thickness
            painter.drawRoundedRect(QRect(0, 0, width, rect.height()), self._radius, self._radius)
        else:
            painter.drawRoundedRect(rect, self._radius, self._radius)
        painter.end()


class AnimatedButtonMixin:
    """Adds an animated hover wash + click ripple to any QAbstractButton."""

    def _install_motion(self, *, accent: str = "#ffffff", glow_alpha: int = 46,
                        ripple_alpha: int = 90, radius: int = 10) -> None:
        self._glow = HoverGlow(self, accent, alpha=glow_alpha, radius=radius)
        self._glow.lower()
        self._ripple = RippleOverlay(self, accent)
        self._ripple.set_corner_radius(radius)
        self._ripple.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._ripple_alpha = ripple_alpha
        self.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self:
            if event.type() == QEvent.Type.Enter:
                self._glow.animate_to(True)
            elif event.type() == QEvent.Type.Leave:
                self._glow.animate_to(False)
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._ripple.start(event.position().toPoint(), max_alpha=self._ripple_alpha)
            elif event.type() == QEvent.Type.Resize:
                self._layout_overlays()
            elif event.type() == QEvent.Type.EnabledChange:
                self._glow.setVisible(self.isEnabled())
        return super().eventFilter(obj, event)

    def _layout_overlays(self) -> None:
        for overlay in (getattr(self, "_glow", None), getattr(self, "_ripple", None)):
            if overlay is not None:
                overlay.setGeometry(0, 0, self.width(), self.height())
                overlay.raise_()
        glow = getattr(self, "_glow", None)
        if glow is not None:
            glow.lower()


def drag_resize_handle(widget: QWidget, target: QWidget) -> None:
    """Placeholder hook kept for API symmetry (unused)."""
    return None


__all__ = [
    "MOTION", "Motion", "easing", "EASINGS", "animate_value", "tween_color", "count_up",
    "fade", "fade_in", "fade_out", "cross_fade", "reveal_height", "stagger", "pulse",
    "stop_pulse", "glow", "shimmer", "AnimatedStackedWidget", "SmoothScrollArea",
    "motion_alive", "revive_motion",
    "smooth_autoscroll", "RippleOverlay", "HoverGlow", "AnimatedButtonMixin",
]
