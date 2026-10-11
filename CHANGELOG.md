# Changelog

All notable changes to Clicks-Auto are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-11

First public release.

### Added

**Recorder**
- "Record Session" button that opens a dedicated Playwright driven browser (Brave by default).
- DOM level capture: clicks, double/right clicks, typing, dropdowns, checkboxes/radios,
  Enter and shortcuts, uploads, navigations, SPA route changes, popup tabs, tab switches and dialogs.
- Ranked selector candidates per action (`data-testid`, `id`, label/aria, role+name, `name`,
  placeholder, text, unique CSS path, XPath) plus iframe frame chains.
- Optional scrolling, hovering and "thinking pause" recording; keystroke-by-keystroke typing mode.
- Passwords recorded as masked secret steps.

**Playback engine**
- Loop control: repeat N times, run for a duration, or run until Stop.
- Pause/resume mid run, per step retries and timeouts, stop-on-error policy, slow motion,
  periodic browser restarts, data driven loops (CSV/JSON rows), run variables and built-ins.
- Self-healing selectors: fallback chain with automatic promotion and an offer to save the healed
  selectors back into the script.
- 35 step types covering interaction, navigation, tabs, verification, data extraction, screenshots,
  JavaScript, conditionals, loops and comments.

**Interface (PyQt6)**
- Animated page transitions, rippling buttons, sliding navigation indicator, count-up statistics,
  gliding toasts, eased smooth scrolling, animated toggles and splash screen.
- Five themes with live switching; animation speed slider and reduce-motion option.
- Dashboard, Run, Record Session, Scripts (library + editor + JSON view), Schedules, History and
  Settings pages, plus a system tray menu and keyboard shortcuts (F9 run, F10 stop, Ctrl+R record).
- Live console with colour coded levels, filters, search, copy and export; step list that highlights
  the running/retried/failed step; error screenshots; run history with CSV export.

**Automation extras**
- Built-in scheduler (once / daily / weekly / interval) with next-run countdowns.
- Browser discovery for Brave, Chrome, Edge and Playwright Chromium, isolated profiles, profile
  copying, custom executable paths, extra Chromium flags and a Chromium downloader.
- Headless CLI (`clicks-auto-cli.exe`): `run`, `record`, `validate`, `list`, `browsers`.

**Fixed**
- Checkboxes, radios, file inputs and sliders are no longer recorded as "Type text" steps
  (`type "on" into I agree to the terms`), which could never be replayed; only real text entries
  (text inputs, textareas, contenteditable areas) produce fill/type steps.
- Placeholder-only steps (`wait`, `times`, `index`, `code`, ...) now fall back to the step's `value`
  when playback reads their arguments.
- First run welcome dialog opened with a broken layout and could abort the app; the loop counter
  label, the indeterminate progress shimmer and the animation helpers are also hardened against
  widgets that are torn down mid-animation.
- `CLICKS_AUTO_BROWSER_ARGS` lets you append extra Chromium flags on unusual hosts.

**Packaging & tests**
- PyInstaller portable build (`Clicks-Auto.exe` + `clicks-auto-cli.exe`), SHA256 checksums,
  generated icons, PowerShell build script and a GitHub Actions pipeline that tests on Linux and
  Windows and publishes the release ZIP.
- pytest suite with unit tests, GUI smoke tests and real browser record → replay integration tests
  against a bundled local test site.
