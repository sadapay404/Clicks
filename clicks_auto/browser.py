"""Browser discovery, launching and lifecycle management (Playwright)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .paths import default_user_data_dir, profiles_dir

# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


@dataclass
class BrowserChoice:
    kind: str
    label: str
    path: str = ""
    source: str = ""

    @property
    def found(self) -> bool:
        return bool(self.path and Path(self.path).exists())

    @property
    def display(self) -> str:
        if self.found:
            return f"{self.label}  ({self.source})"
        return f"{self.label}  (not found)"


@dataclass
class LaunchRequest:
    kind: str = "brave"
    executable: str = ""
    user_data_dir: str = ""
    headless: bool = False
    slow_mo_ms: int = 0
    window_width: int = 1280
    window_height: int = 860
    start_maximized: bool = False
    extra_args: list[str] = field(default_factory=list)
    download_dir: str = ""
    navigation_timeout_ms: int = 45000


class BrowserError(Exception):
    """Raised with a user friendly message."""


def _env_paths() -> list[Path]:
    keys = ["PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "LOCALAPPDATA", "APPDATA", "HOME"]
    out: list[Path] = []
    for key in keys:
        value = os.environ.get(key)
        if value:
            out.append(Path(value))
    return out


def _registry_app_path(exe_name: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg  # type: ignore

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (0, getattr(winreg, "KEY_WOW64_32KEY", 0), getattr(winreg, "KEY_WOW64_64KEY", 0)):
                try:
                    with winreg.OpenKey(
                        root,
                        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}",
                        0,
                        winreg.KEY_READ | view,
                    ) as key:
                        value, _ = winreg.QueryValueEx(key, "")
                        if value:
                            return str(value).strip('"')
                except OSError:
                    continue
    except Exception:
        return ""
    return ""


def _candidates_for(kind: str) -> list[tuple[str, str]]:
    """Return (path, source-description) guesses for a browser kind."""
    out: list[tuple[str, str]] = []
    bases = _env_paths()

    def add(relative: list[str], source: str) -> None:
        for base in bases:
            path = base.joinpath(*relative)
            out.append((str(path), source))

    if kind == "brave":
        for flavour in ("Brave-Browser", "Brave-Browser-Beta", "Brave-Browser-Dev", "Brave-Browser-Nightly"):
            add([flavour, "Application", "brave.exe" if sys.platform == "win32" else "Brave Browser"], r"%PROGRAMFILES%")
        add(["BraveSoftware", "Brave-Browser", "Application", "brave.exe"], r"%LOCALAPPDATA%")
        add(["BraveSoftware", "Brave-Browser-Beta", "Application", "brave.exe"], r"%LOCALAPPDATA%")
        add(["Programs", "BraveSoftware", "Brave-Browser", "Application", "brave.exe"], r"%LOCALAPPDATA%")
        for name in ("brave", "brave-browser", "brave.exe"):
            which = shutil.which(name) if sys.platform != "win32" else None
            if which:
                out.append((which, "PATH"))
    elif kind == "chrome":
        add(["Google", "Chrome", "Application", "chrome.exe"], r"%PROGRAMFILES%")
        add(["Google", "Chrome Beta", "Application", "chrome.exe"], r"%PROGRAMFILES%")
        add(["Programs", "Google", "Chrome", "Application", "chrome.exe"], r"%LOCALAPPDATA%")
        which = shutil.which("google-chrome") or shutil.which("chrome")
        if which:
            out.append((which, "PATH"))
    elif kind == "edge":
        add(["Microsoft", "Edge", "Application", "msedge.exe"], r"%PROGRAMFILES%")
        which = shutil.which("microsoft-edge") or shutil.which("msedge")
        if which:
            out.append((which, "PATH"))
    elif kind == "chromium":
        # Playwright's own downloaded build
        cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"))
        if cache.exists():
            for folder in sorted(cache.glob("chromium-*"), reverse=True):
                for rel in (["chrome-win", "chrome.exe"], ["chrome-linux", "chrome"], ["chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"]):
                    out.append((str(folder.joinpath(*rel)), "Playwright cache"))
        for name in ("chromium", "chromium-browser", "chrome"):
            which = shutil.which(name)
            if which:
                out.append((which, "PATH"))
    elif kind == "custom":
        pass

    return out


def detect_browser(kind: str) -> BrowserChoice:
    labels = {
        "brave": "Brave",
        "chrome": "Google Chrome",
        "edge": "Microsoft Edge",
        "chromium": "Playwright Chromium",
        "custom": "Custom executable",
    }
    label = labels.get(kind, kind.title())
    # 1. registry (fast + accurate on Windows)
    exe_map = {"brave": "brave.exe", "chrome": "chrome.exe", "edge": "msedge.exe"}
    if kind in exe_map:
        reg = _registry_app_path(exe_map[kind])
        if reg and Path(reg).exists():
            return BrowserChoice(kind, label, reg, "registry")
    # 2. well known folders
    for path, source in _candidates_for(kind):
        if path and Path(path).exists():
            return BrowserChoice(kind, label, str(path), source)
    return BrowserChoice(kind, label, "", "")


def detect_all() -> dict[str, BrowserChoice]:
    return {kind: detect_browser(kind) for kind in ("brave", "chrome", "edge", "chromium")}


def _profile_dirs_for(kind: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if kind == "brave":
        out.append((str(local / "BraveSoftware" / "Brave-Browser" / "User Data"), "Brave default user data"))
        out.append((str(roaming / "BraveSoftware" / "Brave-Browser" / "User Data"), "Brave roamer"))
    elif kind == "chrome":
        out.append((str(local / "Google" / "Chrome" / "User Data"), "Chrome default user data"))
    elif kind == "edge":
        out.append((str(local / "Microsoft" / "Edge" / "User Data"), "Edge default user data"))
    return [(p, label) for p, label in out if Path(p).exists()]


def is_profile_locked(user_data_dir: str | Path) -> bool:
    """Best effort check whether a Chromium profile is currently in use."""
    path = Path(user_data_dir)
    if not path.exists():
        return False
    for name in ("SingletonLock", "lockfile"):
        lock = path / name
        if lock.exists():
            return True
    if sys.platform == "win32":
        try:
            # Chromium keeps a "lock" file handle on Windows - try to rename it.
            probe = path / "LOCK_PROBE_TMP"
            probe.write_text("x")
            probe.rename(path / "lock")
        except Exception:
            return True
    return False


def copy_profile(source: str | Path, destination: str | Path, *, include_cache: bool = False) -> Path:
    """Copy an existing browser profile into an app owned folder.

    Chromium refuses to run two instances on one profile, so Clicks-Auto copies
    the profile when a user wants their real Brave/Chrome logins while keeping
    their normal browser open.
    """
    src = Path(source)
    dest = Path(destination)
    if not src.exists():
        raise BrowserError(f"Profile folder does not exist: {src}")
    skip_dirs = {"Cache", "Code Cache", "GPUCache", "DawnCache", "ShaderCache", "GrShaderCache",
                 "Crashpad", "component_crx_cache", "extensions_crx_cache", "Service Worker"}
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_dir():
            if item.name in skip_dirs and not include_cache:
                continue
            shutil.copytree(item, dest / item.name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*skip_dirs) if not include_cache else None,
                            symlinks=False)
        else:
            try:
                shutil.copy2(item, dest / item.name)
            except Exception:
                continue
    return dest


# --------------------------------------------------------------------------
# Launch / lifecycle
# --------------------------------------------------------------------------


class BrowserSession:
    """Owns one Playwright persistent context (browser instance + profile)."""

    def __init__(self, request: LaunchRequest, logger=None) -> None:
        self.request = request
        self.log = logger or (lambda *a, **k: None)
        self.playwright = None
        self.context = None
        self._started = False
        self._downloads_dir = request.download_dir or ""

    # ------------------------------------------------------------------ setup
    def executable(self) -> Optional[str]:
        if self.request.kind == "custom":
            if self.request.executable and Path(self.request.executable).exists():
                return self.request.executable
            raise BrowserError("No custom browser path configured (Settings -> Browser).")
        if self.request.executable and Path(self.request.executable).exists():
            return self.request.executable
        choice = detect_browser(self.request.kind)
        if not choice.found:
            if self.request.kind == "chromium":
                raise BrowserError(
                    "Playwright's Chromium build is not installed yet.\n"
                    "Open Settings -> Browser and press 'Download Chromium',\n"
                    "or pick Brave / Chrome / Edge instead."
                )
            raise BrowserError(
                f"{choice.label} was not found on this computer.\n"
                "Open Settings -> Browser and choose another browser or set a custom path."
            )
        return choice.path

    def resolve_user_data_dir(self) -> str:
        if self.request.user_data_dir:
            path = Path(self.request.user_data_dir)
            path.mkdir(parents=True, exist_ok=True)
            return str(path)
        return str(default_user_data_dir())

    def args(self) -> list[str]:
        args = [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate,ChromeWhatsNewUI,OptimizationHints",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--hide-crash-restore-bubble",
        ]
        if not self.request.start_maximized:
            args.append(f"--window-size={self.request.window_width},{self.request.window_height}")
        else:
            args.append("--start-maximized")
        if self.request.download_dir:
            Path(self.request.download_dir).mkdir(parents=True, exist_ok=True)
            args.append(f"--download-directory={self.request.download_dir}")
        args.extend(a for a in self.request.extra_args if a)
        return args

    # ----------------------------------------------------------------- launch
    def start(self, *, allow_profile_retry: bool = True):
        from playwright.sync_api import sync_playwright  # imported lazily

        executable = self.executable()
        user_data_dir = self.resolve_user_data_dir()
        self.log(f"Launching {self.request.kind} ({executable})")

        self.playwright = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": user_data_dir,
            "executable_path": executable,
            "headless": bool(self.request.headless),
            "slow_mo": int(self.request.slow_mo_ms or 0),
            "accept_downloads": True,
            "args": self.args(),
            "no_viewport": True,
            "chromium_sandbox": False,
        }
        if self.request.download_dir:
            launch_kwargs["downloads_path"] = self.request.download_dir
        try:
            self.context = self.playwright.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self._shutdown_playwright()
            message = str(exc)
            lowered = message.lower()
            if allow_profile_retry and ("singleton" in lowered or "in use" in lowered or "cannot create" in lowered):
                raise BrowserError(
                    "The browser profile is already in use by another browser window.\n"
                    "Close that browser (or pick a different profile) and try again.\n"
                    f"Profile: {user_data_dir}\n\nDetails: {message.splitlines()[0][:200]}"
                )
            raise BrowserError(_friendly_launch_error(message, executable))

        self.context.set_default_timeout(self.request.navigation_timeout_ms)
        self.context.set_default_navigation_timeout(self.request.navigation_timeout_ms)
        self._started = True
        return self.context

    # ----------------------------------------------------------------- access
    @property
    def is_running(self) -> bool:
        return bool(self._started and self.context)

    def page(self):
        """Return the active (or a fresh) page."""
        if not self.context:
            raise BrowserError("Browser is not running.")
        pages = [p for p in self.context.pages if not p.is_closed()]
        if not pages:
            return self.context.new_page()
        return pages[-1]

    def pages(self):
        return [p for p in self.context.pages if not p.is_closed()] if self.context else []

    def close_page(self, page) -> None:
        try:
            if page and not page.is_closed():
                page.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ close
    def _shutdown_playwright(self) -> None:
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        finally:
            self.playwright = None
            self.context = None
            self._started = False

    def stop(self) -> None:
        saved_state = None
        try:
            if self.context:
                try:
                    saved_state = self.context.storage_state()
                except Exception:
                    saved_state = None
                try:
                    self.context.close()
                except Exception:
                    pass
        finally:
            self._shutdown_playwright()
        self.last_storage_state = saved_state


def _friendly_launch_error(message: str, executable: Optional[str]) -> str:
    first = message.splitlines()[0] if message else "unknown error"
    hints: list[str] = []
    if executable and not Path(executable).exists():
        hints.append("The browser executable could not be found.")
    if "executable" in first.lower() and "doesn't exist" in first.lower():
        hints.append("Check Settings -> Browser and point Clicks-Auto at the right .exe file.")
    if "permission" in first.lower():
        hints.append("Try running Clicks-Auto without administrator restrictions, or move the profile folder.")
    if "user data" in first.lower():
        hints.append("Choose a different profile folder in the Run panel (Advanced).")
    text = f"Could not start the browser.\n\n{first}"
    if hints:
        text += "\n\n" + "\n".join(f"- {h}" for h in hints)
    text += f"\n\nFull details: {message[:600]}"
    return text


def playwright_browsers_installed() -> bool:
    cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"))
    return any(cache.glob("chromium-*/**/chrome.exe"))


def install_playwright_chromium(log=None) -> int:
    """Run ``playwright install chromium`` (used by Settings -> Browser)."""
    logger = log or (lambda *_: None)
    env = dict(os.environ)
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    command = [sys.executable, "-m", "playwright", "install", "chromium"]
    logger("Downloading Chromium for Playwright... this can take a few minutes.")
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    assert proc.stdout is not None
    for line in proc.stdout:
        logger(line.rstrip())
    return proc.wait()


def available_profiles(kind: str) -> list[tuple[str, str]]:
    return _profile_dirs_for(kind)


def app_profiles() -> list[tuple[str, str]]:
    """Profiles Clicks-Auto created itself (isolated, safe to reuse)."""
    base = profiles_dir()
    out: list[tuple[str, str]] = []
    for child in sorted(base.iterdir()) if base.exists() else []:
        if child.is_dir():
            out.append((str(child), child.name))
    return out
