"""Packaged GUI self-test checks that do not require Qt."""

from __future__ import annotations

from types import SimpleNamespace

import clicks_auto.app as app_module


class FakeApp:
    def __init__(self):
        self.exit_code = None

    def processEvents(self):
        return None

    def exit(self, code):
        self.exit_code = code


class FakeWorker:
    def __init__(self, *, stuck, outcome="completed"):
        self.stuck = stuck
        self.running = True
        self.result = None if stuck else SimpleNamespace(outcome=outcome)

    def isRunning(self):
        return self.running

    def wait(self, _timeout_ms):
        if not self.stuck:
            self.running = False


class FakeRunPage:
    def __init__(self, *, stuck, outcome="completed"):
        self.stuck = stuck
        self.outcome = outcome
        self.worker = None

    def refresh_library(self):
        return None

    def load_script(self, _path):
        return None

    def start_run(self, *, dry_run):
        assert dry_run is True
        self.worker = FakeWorker(stuck=self.stuck, outcome=self.outcome)


class FakeWindow:
    def __init__(self, *, stuck, outcome="completed"):
        self.pages = []
        self.run_page = FakeRunPage(stuck=stuck, outcome=outcome)
        self.recorder_page = SimpleNamespace(busy=lambda: False, shutdown=lambda: None)
        self.toasts = SimpleNamespace(success=lambda _text: None)
        self.shutdown_called = False

    def show_page(self, key):
        self.pages.append(key)

    def shutdown(self):
        self.shutdown_called = True


class FakeContext:
    store = SimpleNamespace(list_entries=lambda: [SimpleNamespace(path="example.json")])


def test_packaged_self_test_fails_if_dry_run_worker_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "app_data_dir", lambda: tmp_path)
    app = FakeApp()
    window = FakeWindow(stuck=True)

    app_module._run_self_test(app, window, FakeContext())

    report = (tmp_path / "self-test-report.txt").read_text(encoding="utf-8")
    assert app.exit_code == 1
    assert "result: FAIL" in report
    assert "dry run timed out" in report.lower()
    assert window.shutdown_called is True


def test_packaged_self_test_shuts_down_cleanly_after_success(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(app_module.sys, "stdout", None)
    app = FakeApp()
    window = FakeWindow(stuck=False)

    app_module._run_self_test(app, window, FakeContext())

    report = (tmp_path / "self-test-report.txt").read_text(encoding="utf-8")
    assert app.exit_code == 0
    assert "result: PASS" in report
    assert "window shutdown: ok" in report
    assert window.shutdown_called is True


def test_packaged_self_test_fails_if_dry_run_result_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "app_data_dir", lambda: tmp_path)
    app = FakeApp()
    window = FakeWindow(stuck=False, outcome="failed")

    app_module._run_self_test(app, window, FakeContext())

    report = (tmp_path / "self-test-report.txt").read_text(encoding="utf-8")
    assert app.exit_code == 1
    assert "dry run outcome: failed" in report
    assert window.shutdown_called is True
