# Clicks-Auto

**A Windows desktop studio for recording and replaying repetitive web tasks.**

Clicks-Auto drives a real Brave / Chrome / Edge window with [Playwright](https://playwright.dev/python/),
records what you do **at the DOM level** (not video), turns it into a clean, editable JSON script, and
then replays that script once, N times, for a duration, or forever until you press **Stop**.

<p align="center">
  <img src="assets/clicks-auto-128.png" width="96" alt="Clicks-Auto icon">
</p>

---

## Download

Grab the latest portable build from the [releases page](../../releases/latest):

| File | What it is |
| --- | --- |
| `Clicks-Auto-1.0.0-win64.zip` | Portable build - unzip anywhere, run `Clicks-Auto.exe` |
| `Clicks-Auto-1.0.0-win64.zip.sha256` | Checksum you can verify with `certutil -hashfile <file> SHA256` |

Requirements: Windows 10/11 (x64) and any Chromium based browser - **Brave (recommended)**,
Google Chrome or Microsoft Edge. No browser installed? Settings → Browser can download
Playwright's own Chromium for you.

---

## What it does

### 1. In-app recorder ("Record Session")

Press **Record Session** and a dedicated test browser opens. Everything you do is captured at the DOM level:

* clicks, double clicks and right clicks (with the exact element, not screen coordinates),
* text typed into inputs and contenteditable areas (merged into one clean step),
* dropdown selections (stored with the human readable option label),
* checkbox / radio toggling,
* page navigations **and** single page app route changes,
* new tabs, tab switches and popups (`target="_blank"`),
* Enter/Tab/shortcut keys, uploads and alert/confirm dialogs,
* optional: scrolling, hovering and your natural "thinking pauses" as wait steps.

> **Password privacy:** For one-click replay, recorded password values are saved in the script JSON. They are marked sensitive so playback logs mask them, but the JSON is plain text. Keep scripts private; replace the value with `${password}` or use a data file if you do not want the credential stored in the script.

Each captured element comes with **ranked selector candidates**: `data-testid`, `id`,
`aria-label`/`<label>`, accessibility role + name, `name`, placeholder, visible text, a unique CSS
path and an XPath fallback. During playback the engine walks that list, so small site changes do not
break your automation - and when a fallback was needed the run offers to **save the healed selectors**
back into the script.

### 2. Playback engine with real loop control

* **Repeat N times** - an exact repetition count (e.g. 25 logins).
* **Run for a duration** - "keep going for 90 minutes".
* **Until I stop** - endless loop, stopped any time with the Stop button (or `F10`).
* Per step retries, per step timeouts, stop-on-error policy, pause/resume mid-run,
  periodic browser restarts, slow-motion mode for debugging.
* **Data driven runs**: attach a CSV/JSON file and use `${column}` placeholders - one row per loop.
* Built-in **scheduler**: run a script daily, on chosen weekdays, every N minutes or once at a time.

### 3. Live visibility

* Real-time console with colour coded levels, filters, text search, copy and export.
* Step list that highlights exactly which step is running, succeeded, retried or failed.
* Loop/step counters, elapsed timer, animated progress, run history with error details,
  automatic **screenshots on error**, and toasts when something needs your attention.

### 4. Interface with motion everywhere

Built with PyQt6: animated page transitions, rippling buttons, a sliding navigation indicator,
counters that count up, toasts that glide in, smooth eased scrolling, animated toggles, an animated
splash screen and a cross-fading theme switcher (Midnight, Aurora, Sunset, Graphite, Daylight).
Prefer a calmer feel? Settings → Appearance has an animation switch, a speed slider and a
"reduce motion" option.

---

## Screens at a glance

| Page | Purpose |
| --- | --- |
| **Dashboard** | Quick actions, library snapshot, recent runs, detected browser status |
| **Run** | Pick a script, choose the loop mode, watch the live console |
| **Record Session** | Launch the recorder browser and capture a session |
| **Scripts** | Library + full step editor + raw JSON view |
| **Schedules** | Daily / weekly / interval runs with a next-run countdown |
| **History** | Every run with outcome, counters, errors and CSV export |
| **Settings** | Appearance, browser & profile, timeouts, run defaults, data folders |

---

## Getting started (5 minutes)

1. **Unzip** the release folder and run `Clicks-Auto.exe`.
2. Open **Settings → Browser** and confirm your browser was detected (Brave by default).
   Tick "Custom path" only if you installed it somewhere unusual.
3. Go to **Record Session**, give the session a name and (optionally) a start URL, press
   **Record Session**.
4. Do your task in the browser window that opens: type, click, choose options.
   Slow pages? Press **Add wait step** while recording.
5. Press **Stop & save**. The session is saved into your script library.
6. Open **Scripts** to tune selectors, add checks, variables or screenshots.
7. Open **Run**, choose how many times to repeat, press **Run**. Use **Stop** (or `F10`) any time.

Everything lives in `%LOCALAPPDATA%\Clicks-Auto`:

```
scripts/            your recorded scripts (plain JSON)
logs/               console exports and crash logs
browser-profiles/   isolated browser profile(s) used for automation
screenshots/        screenshots taken by steps or on error
settings.json       your settings
history.jsonl       one line per finished run
schedules.json      your scheduled runs
```

---

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `F9` | Run the selected script |
| `F10` | Stop everything |
| `Ctrl+R` | Jump to the recorder |
| `Ctrl+S` | Save the script being edited |
| `Ctrl+T` | Cycle themes |
| `Ctrl+,` | Settings |
| `Ctrl+1…7` | Jump to a page |

---

## Command line (headless)

The portable build also ships `clicks-auto-cli.exe`:

```powershell
# run a script 5 times, headless
clicks-auto-cli.exe run "scripts\examples\wikipedia-search.json" --loops 5 --headless --browser brave

# run forever until Ctrl+C
clicks-auto-cli.exe run search-loop.json --forever --data terms.csv

# check a script without a browser
clicks-auto-cli.exe validate login-and-verify.json

# record a session from the terminal
clicks-auto-cli.exe record --name "Nightly check" --url https://example.com

# what is installed?
clicks-auto-cli.exe browsers
clicks-auto-cli.exe list
```

From a Python environment, `python -m clicks_auto run script.json` works the same way.

---

## Script format (short version)

```json
{
  "format": "clicks-auto-script",
  "version": 1,
  "name": "Daily check-in",
  "start_url": "https://example.com",
  "variables": { "username": "me@example.com" },
  "defaults": { "step_timeout_ms": 20000, "retries": 2 },
  "steps": [
    { "type": "goto", "value": "https://example.com/login" },
    { "type": "fill", "selector": "#email", "value": "${username}",
      "fallbacks": [ { "kind": "label", "value": "Email" } ] },
    { "type": "click", "selector": "#submit", "value": "",
      "fallbacks": [ { "kind": "text", "value": "Sign in" } ] }
  ]
}
```

*Steps, selector kinds, options, variables, nested logic and every step type are documented in
[docs/SCRIPT_FORMAT.md](docs/SCRIPT_FORMAT.md).*

---

## Building from source

```powershell
git clone https://github.com/sadapay404/Clicks.git
cd Clicks
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m playwright install chromium     # optional: only for the bundled browser option
python main.py                            # run from source

powershell -ExecutionPolicy Bypass -File packaging/build_windows.ps1     # portable ZIP
```

The build script runs the test suite, regenerates the icons, packages with PyInstaller into
`dist/Clicks-Auto/` and produces `dist/Clicks-Auto-<version>-win64.zip` (plus a `.sha256`).

Prefer a browser-free download? `BUNDLE_PLAYWRIGHT_BROWSERS=1` additionally ships a Chromium copy
inside the ZIP (~150 MB bigger) and `BundleBrowser` switch in the PowerShell script does the same.

### Project layout

```
clicks_auto/
  models.py        script/step model + JSON (de)serialisation
  engine.py        playback engine: loop control, retries, self-healing selectors
  browser.py       browser discovery (Brave/Chrome/Edge/Chromium), profiles, launching
  locator.py       selector candidate -> Playwright selector translation
  recorder/
    recorder.js    the DOM recorder injected into every frame
    builder.py     raw DOM events -> clean script steps
    session.py     Playwright glue + event plumbing
  datafeed.py      CSV/JSON rows for data driven loops
  scheduler.py     daily / weekly / interval schedules
  history.py       run log (JSONL) + statistics
  store.py         script library on disk
  settings.py      persistent settings
  cli.py           headless command line interface
  ui/              PyQt6 interface (theme, animations, pages, widgets, worker threads)
packaging/         PyInstaller spec, icon generator, build script
tests/             pytest suite incl. real browser record -> replay integration tests
```

---

## Testing

```bash
python -m pytest -q
```

* Unit tests cover the model layer, the recorder's event→step translation, storage, the data feed,
  the scheduler, the engine's error mapping and the settings file.
* GUI smoke tests build the whole window, every page, every dialog and run a dry run through the
  worker thread.
* Browser integration tests (`tests/test_browser_flow.py`) start a local test site, **record a real
  session in a real Chromium**, then replay that recorded script through the engine and assert the
  result - the strongest guarantee that recording and playback stay in sync.

Set `CLICKS_AUTO_SKIP_BROWSER_TESTS=1` to skip the browser tests in restricted environments.

Useful environment variables:

| Variable | Purpose |
| --- | --- |
| `CLICKS_AUTO_HOME` | Store scripts, logs, profiles and settings somewhere other than `%LOCALAPPDATA%\Clicks-Auto` |
| `CLICKS_AUTO_SKIP_BROWSER_TESTS` | Skip the browser integration tests |
| `CLICKS_AUTO_BROWSER_ARGS` | Extra Chromium flags appended to every launch, e.g. `--single-process --disable-dev-shm-usage` for containers, locked down desktops or CI |
| `PLAYWRIGHT_BROWSERS_PATH` | Point Playwright at an existing browser download folder |

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Brave was not found" | Settings → Browser: pick another browser, browse to the `.exe`, or download Playwright's Chromium |
| Automation browser opens but the site logs you out | Use *my real profile* (Settings → Browser) or sign in once inside the automation profile - it is remembered |
| "profile is already in use" | Chromium allows one instance per profile: close your normal browser, or use the isolated Clicks-Auto profile |
| A step times out on a slow page | Increase Settings → Timeouts, or add a **Wait for element** step in the editor |
| Steps broke after a site redesign | Re-record that part, or rely on the fallback chain and "Save healed selectors" |
| Uploads do nothing | File inputs need real paths: edit the recorded `Upload file` step and list full paths |
| The browser will not start in a container / hardened desktop | Set `CLICKS_AUTO_BROWSER_ARGS="--single-process --disable-dev-shm-usage --no-zygote"` and retry |

---

## License

MIT - see [LICENSE](LICENSE).
