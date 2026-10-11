"""Shared pytest fixtures.

The GUI/browser tests are skipped automatically when the sandbox has no display
or no Chromium - they run for real on the Windows CI runner.
"""

from __future__ import annotations

import os
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SITE = FIXTURES / "site"


@pytest.fixture()
def tmp_home(tmp_path, monkeypatch):
    """Point the app's data folder at a temporary directory."""
    home = tmp_path / "clicks-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLICKS_AUTO_HOME", str(home))
    return home


@pytest.fixture(scope="session")
def site_url():
    """Serve tests/fixtures/site on a free port and return the base URL."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(SITE))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def browser_available() -> str:
    """Return the executable path of a usable Chromium, or an empty string."""
    if os.environ.get("CLICKS_AUTO_SKIP_BROWSER_TESTS"):
        return ""
    from clicks_auto.browser import detect_all

    for kind in ("chromium", "chrome", "brave", "edge"):
        choice = detect_all().get(kind)
        if choice is not None and choice.found:
            return choice.path
    return ""


@pytest.fixture(scope="session")
def chromium_path() -> str:
    path = browser_available()
    if not path:
        pytest.skip("no Chromium based browser available in this environment")
    return path


@pytest.fixture()
def gui_app(tmp_home, monkeypatch):
    """A QApplication instance (offscreen when there is no display)."""
    if not os.environ.get("DISPLAY") and os.name != "nt":
        monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    from clicks_auto.settings import Settings
    from clicks_auto.store import ScriptStore
    from clicks_auto.ui.context import AppContext
    from clicks_auto.ui.theme import apply_stylesheet

    app = QApplication.instance() or QApplication([])
    settings = Settings()
    # Every test gets a throw-away home directory, so the first-run welcome
    # dialog would pop up (modal, unanswerable) in every single test.
    settings.first_run_done = True
    context = AppContext(settings, ScriptStore())
    apply_stylesheet(app, context.palette)
    yield app, context
    app.processEvents()
