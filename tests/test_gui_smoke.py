"""GUI smoke tests: build every page, open dialogs, run a dry run through the UI.

These run headless (offscreen) on Linux and normally on the Windows runner.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("PyQt6")


@pytest.fixture(autouse=True)
def _mark_test(request):
    """Print a marker per test: when a headless run dies, the log names it."""
    print(f"\n--- {request.node.name}", file=sys.stderr, flush=True)
    yield


@pytest.fixture(scope="module")
def window(gui_app):
    app, context = gui_app
    from clicks_auto.models import Script, Step
    from clicks_auto.ui.main_window import MainWindow

    context.store.save(Script(name="Smoke script", steps=[
        Step(type="goto", value="https://example.com"),
        Step(type="click", selector="#a", description="A link"),
        Step(type="wait", value="250"),
    ]), context.store.unique_path_for("Smoke script"))

    win = MainWindow(context)
    win.show()
    app.processEvents()
    yield win
    # ``shutdown`` stops and *joins* every worker; destroying a window while a
    # worker still runs is what used to abort the Windows runner.
    win.shutdown()
    win.close()
    app.processEvents()


def test_window_and_pages_build(window):
    window.show_page("dashboard")
    for key in ("dashboard", "run", "recorder", "scripts", "schedules", "history", "settings"):
        window.show_page(key)
        window.ctx and None
    assert window.pages  # all pages exist
    assert window.width() > 100 and window.height() > 100


def test_theme_cycling_repaints(window):
    from clicks_auto.ui.theme import PALETTES

    for _ in range(len(PALETTES) + 1):
        window.cycle_theme()
    assert window.settings.ui.theme in PALETTES


def test_run_page_loads_script_and_lists_steps(window):
    window.show_page("run")
    window.run_page.refresh_library()
    entries = window.ctx.store.list_entries()
    assert entries, "the smoke script should be in the library"
    window.run_page.load_script(entries[0].path)
    assert window.run_page.script is not None
    assert len(window.run_page.step_list.rows()) == 3


def test_dry_run_through_the_worker_thread(window):
    window.show_page("run")
    window.run_page.refresh_library()
    window.run_page.load_script(window.ctx.store.list_entries()[0].path)
    window.run_page.start_run(dry_run=True)
    worker = window.run_page.worker
    assert worker is not None
    assert worker.wait(20000), "dry run worker did not finish"
    for _ in range(50):
        window.ctx and None
        from PyQt6.QtWidgets import QApplication

        QApplication.processEvents()
    assert window.run_page.console.entry_count() > 0


def test_step_editor_dialog_builds_for_every_type(window):
    from clicks_auto.models import STEP_TYPES, Step
    from clicks_auto.ui.dialogs import StepEditorDialog

    for key in STEP_TYPES:
        dialog = StepEditorDialog(window, step=Step(type=key), palette=window.ctx.palette)
        assert dialog.type_combo.count() > 5
        dialog.deleteLater()


def test_other_dialogs_build(window):
    from clicks_auto.ui.dialogs import (
        AboutDialog,
        BrowserPickerDialog,
        ScriptPickerDialog,
        WelcomeDialog,
    )

    for factory in (
        lambda: AboutDialog(window, palette=window.ctx.palette),
        lambda: BrowserPickerDialog(window, palette=window.ctx.palette),
        lambda: ScriptPickerDialog(window, palette=window.ctx.palette),
        lambda: WelcomeDialog(window, palette=window.ctx.palette),
    ):
        dialog = factory()
        dialog.deleteLater()


def test_scripts_page_loads_and_saves(window, tmp_home):
    window.show_page("scripts")
    page = window.scripts_page
    page.refresh_library()
    entries = window.ctx.store.list_entries()
    page.load_script(entries[0].path)
    assert page.script is not None
    page.name_edit.setText("Renamed smoke script")
    page.save_script(quiet=True)
    assert page.path is not None and page.path.exists()
    assert not page.dirty


def test_history_page_with_data(window, tmp_home):
    from clicks_auto.history import HistoryRecord, append

    append(HistoryRecord(script="Smoke script", started_at="2024-01-01T00:00:00",
                         outcome="completed", loops_completed=3, steps_ok=9, duration="4s"))
    window.show_page("history")
    window.history_page.refresh()
    assert window.history_page.table.rowCount() == 1


def test_schedules_page_adds_and_lists(window, tmp_home):
    from clicks_auto.scheduler import Schedule

    schedule = Schedule(name="Smoke schedule", mode="interval", interval_minutes=5,
                        script_path=str(window.ctx.store.list_entries()[0].path))
    window.scheduler.add(schedule)
    window.show_page("schedules")
    window.schedules_page.refresh()
    assert window.schedules_page.list_widget.count() == 1


def test_settings_page_applies_changes(window):
    window.show_page("settings")
    page = window.settings_page
    page.speed_slider.setValue(150)
    assert window.settings.ui.animation_speed == pytest.approx(1.5)
    page._flush()
    from clicks_auto.settings import Settings

    assert Settings.load().ui.animation_speed == pytest.approx(1.5)


def test_toast_manager_shows_notifications(window):
    # The window is shared by the whole module, so count the new toasts instead
    # of assuming the stack starts empty.
    before = len(window.toasts.toasts)
    window.toasts.success("hello from the test suite")
    window.toasts.error("and an error", title="Uh oh")
    assert len(window.toasts.toasts) >= before + 2
