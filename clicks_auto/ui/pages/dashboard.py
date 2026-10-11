"""Landing page: quick actions, library snapshot, recent activity."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ...history import load as load_history, stats as history_stats
from ..anim import MOTION, fade_in, stagger
from ..widgets.common import (
    AnimatedButton,
    Card,
    Pill,
    ScrollPage,
    SectionHeader,
    StatTile,
)


def _item(text: str, right: str = "", tooltip: str = "") -> QListWidgetItem:
    widget = QListWidgetItem(f"{text}    {right}")
    if tooltip:
        widget.setToolTip(tooltip)
    return widget


class DashboardPage(ScrollPage):
    record_requested = pyqtSignal()
    run_requested = pyqtSignal()
    script_activated = pyqtSignal(str)

    def __init__(self, context, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, margin=24)
        self.ctx = context
        self.setObjectName("Page")

        header = SectionHeader(
            "Dashboard",
            "Record a session once, replay it as often as you like.",
        )
        refresh_button = AnimatedButton("Refresh", kind="ghost", icon_text="\u21bb")
        refresh_button.clicked.connect(self.refresh)
        right = QWidget()
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(refresh_button)
        header.layout().addWidget(right)
        self.add(header)

        self.add(self._build_hero())

        tiles = QGridLayout()
        tiles.setSpacing(14)
        self.tile_scripts = StatTile("Scripts", "0", "\u2637", accent=context.palette.accent)
        self.tile_runs = StatTile("Total runs", "0", "\u25b6", accent=context.palette.success)
        self.tile_loops = StatTile("Loops played", "0", "\u21bb", accent=context.palette.info)
        self.tile_success = StatTile("Success rate", "0%", "\u2691", accent=context.palette.warning)
        for index, tile in enumerate((self.tile_scripts, self.tile_runs, self.tile_loops, self.tile_success)):
            tile.clicked.connect(lambda _=False: self.ctx.goto("history"))
            tiles.addWidget(tile, 0, index)
        wrapper = QWidget()
        wrapper.setLayout(tiles)
        self.add(wrapper)
        self._tiles = [self.tile_scripts, self.tile_runs, self.tile_loops, self.tile_success]

        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self._build_library_card(), 3)
        columns.addWidget(self._build_activity_card(), 2)
        holder = QWidget()
        holder.setLayout(columns)
        self.add(holder)

        self.add(self._build_tips())

    # ------------------------------------------------------------------- hero
    def _build_hero(self) -> QWidget:
        hero = Card(tone="hi")
        hero.setObjectName("HeroCard")
        hero.layout.setContentsMargins(24, 22, 24, 22)
        hero.layout.setSpacing(14)

        row = QHBoxLayout()
        row.setSpacing(18)
        column = QVBoxLayout()
        column.setSpacing(6)
        title = QLabel("What do you want to automate today?")
        title.setObjectName("PageTitle")
        column.addWidget(title)
        subtitle = QLabel(
            "Clicks-Auto records your real browser actions at the DOM level - clicks, typing, "
            "dropdowns, navigation - then replays them reliably, in a loop if you want."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("role", "muted")
        column.addWidget(subtitle)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.record_button = AnimatedButton("Record Session", kind="danger", icon_text="\u25cf",
                                            accent=self.ctx.palette.danger)
        self.record_button.setMinimumHeight(42)
        self.record_button.clicked.connect(self.record_requested.emit)
        buttons.addWidget(self.record_button)

        self.run_button = AnimatedButton("Run a script", kind="primary", icon_text="\u25b6",
                                         accent=self.ctx.palette.accent)
        self.run_button.setMinimumHeight(42)
        self.run_button.clicked.connect(self.run_requested.emit)
        buttons.addWidget(self.run_button)

        self.settings_button = AnimatedButton("Settings", kind="ghost", icon_text="\u2699")
        self.settings_button.clicked.connect(lambda: self.ctx.goto("settings"))
        buttons.addWidget(self.settings_button)
        buttons.addStretch(1)
        column.addLayout(buttons)
        row.addLayout(column, 1)

        self.rec_badge = Pill("\u25cf  RECORDER READY", level="success")
        row.addWidget(self.rec_badge, alignment=Qt.AlignmentFlag.AlignTop)
        hero.layout.addLayout(row)

        self.browser_line = QLabel("")
        self.browser_line.setProperty("role", "faint")
        hero.layout.addWidget(self.browser_line)
        self.hero = hero
        return hero

    def _build_library_card(self) -> QWidget:
        card = Card(padding=16, spacing=10)
        header = QHBoxLayout()
        title = QLabel("Your scripts")
        title.setProperty("role", "h3")
        header.addWidget(title)
        header.addStretch(1)
        open_button = AnimatedButton("Open library", kind="ghost")
        open_button.clicked.connect(lambda: self.ctx.goto("scripts"))
        header.addWidget(open_button)
        card.layout.addLayout(header)

        self.library_list = QListWidget()
        self.library_list.setMinimumHeight(210)
        self.library_list.itemDoubleClicked.connect(self._on_item_activated)
        card.layout.addWidget(self.library_list)
        self.library_empty = QLabel("No scripts yet - record your first session!")
        self.library_empty.setProperty("role", "faint")
        card.layout.addWidget(self.library_empty)
        self.library_card = card
        return card

    def _build_activity_card(self) -> QWidget:
        card = Card(padding=16, spacing=10)
        header = QHBoxLayout()
        title = QLabel("Recent runs")
        title.setProperty("role", "h3")
        header.addWidget(title)
        header.addStretch(1)
        history_button = AnimatedButton("History", kind="ghost")
        history_button.clicked.connect(lambda: self.ctx.goto("history"))
        header.addWidget(history_button)
        card.layout.addLayout(header)

        self.activity_list = QListWidget()
        self.activity_list.setMinimumHeight(210)
        card.layout.addWidget(self.activity_list)
        self.activity_empty = QLabel("Nothing has been run yet.")
        self.activity_empty.setProperty("role", "faint")
        card.layout.addWidget(self.activity_empty)
        return card

    def _build_tips(self) -> QWidget:
        card = Card(tone="alt", padding=16, spacing=8)
        row = QHBoxLayout()
        row.setSpacing(14)
        for glyph, title, body in (
            ("\u25cf", "Smart record", "Every recorded action stores several selector candidates, so playback survives small site changes."),
            ("\u21bb", "Loop control", "Run once, N times, for a duration, or endlessly until you hit Stop."),
            ("\u2632", "Data driven", "Point a CSV at a script and use ${column} placeholders to run one row per loop."),
        ):
            column = QVBoxLayout()
            column.setSpacing(3)
            head = QLabel(f"{glyph}  {title}")
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            column.addWidget(head)
            text = QLabel(body)
            text.setProperty("role", "muted")
            text.setWordWrap(True)
            column.addWidget(text)
            holder = QWidget()
            holder.setLayout(column)
            row.addWidget(holder, 1)
        card.layout.addLayout(row)
        return card

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        ctx = self.ctx
        entries = ctx.refresh_library()
        stats = history_stats()
        scripts = len(entries)
        self.tile_scripts.set_value(str(scripts))
        self.tile_runs.set_value(str(stats.get("runs", 0)))
        self.tile_loops.set_value(str(stats.get("loops", 0)))
        self.tile_success.set_value(f"{stats.get('success_rate', 0)}%")
        self.tile_success.set_hint(f"{stats.get('runs_with_errors', 0)} run(s) with errors")
        if stats.get("last_run"):
            self.tile_runs.set_hint(f"last {stats['last_run'][:16].replace('T', ' ')}")

        self.library_list.clear()
        for entry in entries[:12]:
            item = _item(entry.display_name, f"{entry.step_count} steps",
                         f"updated {entry.updated_at[:19]}")
            item.setData(Qt.ItemDataRole.UserRole, str(entry.path))
            self.library_list.addItem(item)
        self.library_empty.setVisible(not entries)
        self.library_list.setVisible(bool(entries))

        self.activity_list.clear()
        rows = load_history(limit=12)
        for row in rows:
            icon = {"completed": "\u2713", "completed_with_errors": "\u26a0", "failed": "\u2716",
                    "stopped": "\u25a0"}.get(str(row.get("outcome")), "\u2022")
            text = f"{icon}  {row.get('script', '?')}"
            right = f"{row.get('loops_completed', 0)} loops \u2022 {row.get('duration', '')}"
            item = _item(text, right, str(row.get("started_at", ""))[:19])
            self.activity_list.addItem(item)
        self.activity_empty.setVisible(not rows)
        self.activity_list.setVisible(bool(rows))

        browser_kind = ctx.settings.browser.kind
        from ...browser import detect_browser

        choice = detect_browser(browser_kind)
        state = f"found at {choice.path}" if choice.found else "not found - open Settings"
        self.browser_line.setText(
            f"Automation browser: {choice.label} \u2022 {state}   |   version {__version__}"
        )
        self.rec_badge.set_level("success" if choice.found else "warning",
                                 "\u25cf  RECORDER READY" if choice.found else "\u25cf  BROWSER NOT FOUND")
        if MOTION.enabled:
            fade_in(self.hero, 260)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.script_activated.emit(str(path))

    def apply_palette(self, palette) -> None:
        self.tile_scripts.set_accent(palette.accent)
        self.tile_runs.set_accent(palette.success)
        self.tile_loops.set_accent(palette.info)
        self.tile_success.set_accent(palette.warning)
        self.record_button.set_accent(palette.danger)
        self.run_button.set_accent(palette.accent)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()
        if MOTION.enabled:
            stagger(self._tiles, step=60, duration=300)
