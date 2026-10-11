# Clicks-Auto script format

A script is a single JSON file. Everything the recorder produces uses this format, and hand written
scripts are first class citizens.

```json
{
  "format": "clicks-auto-script",
  "version": 1,
  "id": "sc_1a2b3c4d",
  "name": "Daily check-in",
  "description": "What this script does",
  "author": "you",
  "start_url": "https://example.com",
  "created_at": "2026-01-01T09:00:00+00:00",
  "updated_at": "2026-01-02T10:30:00+00:00",
  "source": "recorded",
  "keep_alive": true,
  "variables": { "username": "me@example.com" },
  "defaults": {
    "step_timeout_ms": 20000,
    "navigation_timeout_ms": 45000,
    "retries": 2,
    "retry_delay_ms": 700,
    "delay_between_steps_ms": 250,
    "delay_between_loops_ms": 1200
  },
  "steps": []
}
```

## Step anatomy

```json
{
  "type": "click",
  "id": "s_9f8e7d6c",
  "description": "Sign in button",
  "selector": "[data-testid=\"login\"]",
  "selector_kind": "css",
  "selector_index": 0,
  "fallbacks": [
    { "kind": "role", "value": "button[name=\"Sign in\"]" },
    { "kind": "text", "value": "Sign in" }
  ],
  "value": "text to type / url / key",
  "options": { "clear_first": true, "press_enter": true },
  "timeout_ms": 15000,
  "retries": 1,
  "optional": false,
  "wait_after_ms": 300,
  "enabled": true
}
```

| Field | Meaning |
| --- | --- |
| `type` | One of the step types below |
| `description` | Human label shown in the UI (recorder fills this from the element) |
| `selector` | Primary way to find the element |
| `selector_kind` | `css` (default), `xpath`, `text`, `role`, `label`, `placeholder`, `testid`, `alt`, `title` |
| `selector_index` | Use this match when the selector matches several elements (0 = first) |
| `fallbacks` | Ranked alternatives tried when the primary selector finds nothing (self-healing) |
| `value` | The text/URL/key/amount for the step |
| `options` | Step specific settings (see below) |
| `timeout_ms` | Overrides the script default for this step |
| `retries` | Overrides the script default for this step |
| `optional` | Never fail the run because of this step |
| `wait_after_ms` | Extra pause after the step |
| `enabled` | Set to `false` to keep a step but skip it |
| `steps` / `else_steps` | Nested steps for `repeat` and `if_visible` |

### Selector kinds

| Kind | Example | Notes |
| --- | --- | --- |
| `css` | `#login .btn-primary` | Default; also accepts Playwright's `text=` / `xpath=` prefixes |
| `xpath` | `//button[1]` | Written without the `xpath=` prefix |
| `text` | `Sign in` | Matches visible text |
| `role` | `button[name="Sign in"]` | Accessibility role + accessible name |
| `label` | `Email address` | Field label (form inputs) |
| `placeholder` | `you@example.com` | Input placeholder |
| `testid` | `login-button` | Maps to `[data-testid="..."]` |
| `alt` / `title` | `Company logo` | Image alt text / title attribute |

## Variables

Use `${name}` anywhere inside `value`, `selector` or JavaScript. Sources, in order:

1. `variables` in the script file,
2. `--var NAME=VALUE` on the command line,
3. the current row of an attached **CSV/JSON data file** (one row per loop),
4. built-ins:

| Variable | Value |
| --- | --- |
| `${__loop__}` | 1-based loop number |
| `${__loop_index__}` | 0-based loop number |
| `${__total_loops__}` | Planned loop count (if any) |
| `${__date__}` | `2026-01-31` |
| `${__time__}` | `14:05:09` |
| `${__datetime__}` | `2026-01-31 14:05:09` |
| `${__timestamp__}` | Unix seconds |
| `${__script__}` | Script name |

Unknown placeholders are left untouched so mistakes are easy to spot in the console.

## Step types

| Type | Label | Key options |
| --- | --- | --- |
| `goto` | Open URL | `value` = URL |
| `click` | Click | `button` (`left`/`right`/`middle`), `click_count`, `expect_popup` |
| `dblclick` | Double click | - |
| `fill` | Type text | `clear_first`, `press_enter`, `secret` (mask in logs) |
| `type` | Type slowly (keystrokes) | `clear_first`, `delay_ms`, `press_enter` |
| `clear` | Clear field | - |
| `select` | Choose dropdown option | `by` (`label`/`value`/`index`), `value` |
| `check` / `uncheck` | Tick / untick checkbox | - |
| `hover` | Hover | - |
| `press` | Press key | `value` = key (`Enter`, `Control+A`); optional `selector` |
| `upload` | Upload file | `value` = one full path per line |
| `scroll` | Scroll | `dx`, `dy`, `into_view` |
| `wait` | Wait | `ms` (or `value`) |
| `wait_for` | Wait for element | `state` = `visible`/`hidden`/`attached`/`detached`, `timeout_ms` |
| `assert_text` | Check text | `value` = expected, `match` = `contains`/`equals`/`regex`/`not_contains`, `optional` |
| `assert_url` | Check URL | `value`, `match` |
| `assert_visible` | Check element visible | `timeout_ms` |
| `extract` | Extract text to variable | `variable`, `attribute` (optional) |
| `set_var` | Set variable | `variable`, `value` |
| `screenshot` | Screenshot | `path`, `full_page` |
| `run_js` | Run JavaScript | `value` = code, `variable` (optional result target) |
| `if_visible` | If element visible... | `timeout_ms`, nested `steps` (then) and `else_steps` (else) |
| `repeat` | Repeat block | `times`, nested `steps` |
| `go_back` / `go_forward` / `reload` | History / refresh | - |
| `new_tab` | New tab | `value` = URL (optional) |
| `switch_tab` | Switch tab | `value`/`index` = 1-based tab number |
| `close_tab` | Close tab | - |
| `dialog` | Handle popup dialog | `action` = `accept`/`dismiss`, `prompt_text`, `fires_next` |
| `note` | Comment | `text` (does nothing at run time) |

## Tips

* **Prefer stable selectors.** `data-testid` and `id` survive redesigns best; the recorder ranks them
  highest and keeps everything else as fallbacks.
* **Add checks.** `assert_text` / `assert_visible` turn silent failures into clear errors.
* **Reuse secrets.** Store credentials as variables (or a CSV row) and mark password fills `secret`
  so they are masked in the console.
* **Use waits wisely.** A `wait_for` on a stable element beats a fixed `wait`.
* **Nest with care.** `if_visible` and `repeat` keep long flows readable.

## Running a script

```powershell
# GUI: Run page  |  CLI:
clicks-auto-cli.exe run daily-checkin.json --loops 10 --data accounts.csv --headless
```

Command line flags: `--loops N`, `--forever`, `--duration MINUTES`, `--headless`, `--browser KIND`,
`--browser-path EXE`, `--profile FOLDER`, `--data FILE`, `--var NAME=VALUE`, `--stop-on-error`,
`--slow-mo MS`, `--json` (machine readable result), `--quiet`.
