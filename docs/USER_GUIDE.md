# Clicks-Auto user guide

A slower, friendlier walkthrough than the README.

---

## 1. First launch

1. Unzip the release somewhere permanent (Desktop, `C:\Tools`, a USB stick - the app is portable).
2. Run `Clicks-Auto.exe`. Windows SmartScreen may warn about an unsigned app the first time:
   *More info → Run anyway*, or verify the SHA256 checksum first:

   ```powershell
   certutil -hashfile Clicks-Auto-1.0.1-win64.zip SHA256
   ```

3. The welcome dialog explains the three steps: record → fine tune → run.
4. Open **Settings → Browser**. Clicks-Auto auto-detects Brave, Chrome, Edge and Playwright's own
   Chromium. If your browser is installed somewhere unusual, use *Find .exe…*.
   Press *Download Chromium* if you have no Chromium browser at all.

### Which profile should I use?

| Option | When to use |
| --- | --- |
| **Isolated Clicks-Auto profile** (default) | Safest. Automation gets its own cookies/logins, completely separate from your daily browsing. Sign in once inside it and it stays signed in. |
| **My real Brave/Chrome profile** | You are already signed in to everything and do not want to log in again. Requirement: that browser must be **closed** while Clicks-Auto runs (Chromium allows one instance per profile). |

---

## 2. Recording a session

1. **Record Session** page → give the session a name (e.g. *Daily invoice check-in*).
2. Optionally set a **start page** - the recorder browser opens it for you and records it as the first
   step.
3. Choose recording extras:

   | Option | Effect |
   | --- | --- |
   | Record scrolling | adds `scroll` steps |
   | Record hovering | adds `hover` steps (menus, tooltips) |
   | Type like a human | records keystroke by keystroke (`type` steps with a delay) |
   | Keep browser open after saving | handy when you want to continue browsing |
   | Recorded pauses | inserts `wait` steps for your thinking pauses (max 12 s) |

4. Press **Record Session**. A browser window opens - *that* window is the recorder.
5. Do the task at a natural pace. Watch the step list grow in the app.
6. Useful controls while recording:
   * **Pause recording** - keep browsing without capturing (good for exploratory clicks).
   * **Add wait step** - insert a deliberate pause (great right before a slow page settles).
7. Press **Stop & save**. The script lands in your library and the app offers *Open in editor* and
   *Run it now*.

### What gets recorded (and what needs a tweak)

| Recorded automatically | Needs a manual edit |
| --- | --- |
| Clicks, double clicks, right clicks | File uploads (the browser hides real paths - add paths in the editor) |
| Typing, including Enter to submit | Native OS dialogs (print, save as) |
| Dropdown selections (by label *and* value) | Captchas / 2FA (do them once in the isolated profile and stay signed in) |
| Checkboxes and radios | Anything outside the browser window |
| Navigation, SPA route changes, popup tabs, tab switches | |
| Alert / confirm dialogs (auto-accepted by default) | |

**Password privacy:** To preserve one-click replay, values typed into password fields are saved in the local JSON script. They are marked `secret` so playback logs mask them, but this is not encryption. Keep those scripts private, or replace the value with a variable such as `${password}` / a data-file column before sharing or running elsewhere.

---

## 3. Editing the script

Open **Scripts**. The left side is your library, the right side is the editor with four tabs.

* **Steps** - add, edit, duplicate, reorder, enable/disable and delete steps. Double click a step to
  open the editor: pick any of the ~35 step types, set the selector kind, the value, timeouts and
  retries, and see the recorded fallback chain.
* **Settings** - per script timeouts, retries and pacing (they override the global defaults).
* **Variables** - `name=value` lines usable as `${name}` anywhere in the script.
* **JSON** - the raw file. Edit it and press *Apply JSON*, or use *Reformat* to tidy it up.

Useful habits:

* Add a **Check text** step after a form submit so failures are loud instead of silent.
* Replace brittle selectors with the highest ranked candidate: hover a step to see the CSS path
  recorded, then swap in the `data-testid` version in the editor.
* Turn a step into a *wait for element* when the site needs a moment.

---

## 4. Running it

Go to **Run**:

1. Choose the script.
2. Choose the loop mode:
   * **Repeat N times** - type the exact number of repetitions.
   * **Run for a duration** - e.g. 90 minutes, then stop.
   * **Until I stop** - runs forever; press **Stop** (`F10`) whenever you want.
3. Optional toggles: headless (no window), stop on first error, new browser each loop, close browser
   when done, slow motion, and a data file.
4. Press **Run**. The live panel shows the current loop, the current step, elapsed time and a progress
   bar; the console below shows every action with colour coded levels.
5. **Pause** mid-run if you need to intervene, **Stop** to finish cleanly. If the browser was left
   open on purpose, a **Close browser** button appears.

### Data driven loops

Attach a CSV/JSON file (Run page → *Attach data file…*):

```csv
username,password
alice@example.com,secret-one
bob@example.com,secret-two
```

Reference the columns as `${username}` / `${password}` in the script. Each loop consumes the next row
and wraps around at the end. JSON files work too: `[{"username": "alice"}, ...]`.

### Schedules

**Schedules** page → *New schedule*: choose a script, "every day at 09:30", "Mon/Wed/Fri at 18:00",
"every 45 minutes", or a single run. Clicks-Auto must be running for schedules to fire; the header
shows a live countdown for the next three runs.

---

## 5. Understanding what happened

* **History** lists every run (manual, scheduled or CLI) with outcome, loops, failures, duration and
  the full error text of the selected run. Export to CSV or clear it.
* **Console** (Run page) supports filters, text search, copy and *Save log*.
* **Screenshots on error** are written to `%LOCALAPPDATA%\Clicks-Auto\screenshots` - the console logs
  the exact path.
* **Self healing**: when a fallback selector saved the day, the run reports it and offers
  *Save healed selectors* so the next run is faster.

---

## 6. Making it look and feel right

**Settings → Appearance**:

* five themes (Midnight, Aurora, Sunset, Graphite, Daylight) with live preview swatches,
* animation switch + speed slider (0.25×–4×) + *Reduce motion*,
* compact layout, toast notifications, native title bar (for unusual DPI setups),
* console line limit.

Everything else lives under *Timeouts, retries and pacing* and *Run defaults*, so you set the pacing
once and every new run respects it.

---

## 7. Headless and unattended use

`clicks-auto-cli.exe` (shipped in the same folder) runs scripts with no window:

```powershell
clicks-auto-cli.exe run "daily-checkin.json" --loops 25 --headless --data accounts.csv --json
```

Combine that with Windows Task Scheduler for real unattended automation:

```powershell
schtasks /create /tn "Clicks-Auto nightly" /sc daily /st 23:30 ^
  /tr "\"C:\Tools\Clicks-Auto\clicks-auto-cli.exe\" run \"C:\Tools\scripts\checkin.json\" --loops 1 --headless --quiet"
```

Exit codes: `0` success (including "completed with errors" and user stop), `1` failure, `130` Ctrl+C.

---

## 8. Troubleshooting quick reference

| Symptom | Fix |
| --- | --- |
| Browser does not start | Settings → Browser: re-detect, browse to the `.exe`, or download Chromium |
| "profile is already in use" | Close your normal browser or switch to the isolated profile |
| Session logged out next run | Use the isolated profile and sign in once there |
| Steps time out | Raise Settings → Timeouts, add `wait_for` steps, or enable slow motion while debugging |
| Script broke after a site update | Re-record that section; playback also tries fallback selectors automatically |
| Runs are too fast for the site | Increase *Pause between steps* or use *Type slowly* steps |
| Antivirus complains about the ZIP | Verify the SHA256 checksum; the build is unsigned but reproducible from this repo |
| GUI stays behind other windows | Settings → Appearance → *Native title bar* (restart required) |
