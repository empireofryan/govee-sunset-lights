# Govee Lights Distribution Package — Design

**Date:** 2026-05-08
**Status:** Approved
**Author:** Ryan + Claude

## Goal

Refactor the existing macOS menu bar Govee lights controller into a shareable
package that friends with their own (different) Govee light setups can install
on their Macs in under five minutes.

## Success Criteria

1. A friend with a Govee account, macOS, and Python 3 can install and run the
   app without editing any source code.
2. All previously-hardcoded values (API key, "Busted" exclusion, subset-scene
   anchor device names) are replaced by user config.
3. On first launch, the app validates the user's API key by fetching their
   devices and shows a friendly success or error dialog.
4. The original developer (Ryan) keeps the existing
   `empireofryan/govee-sunset-lights` repo as a private dev playground; the
   public package lives in a new, separate repo on Ryan's work GitHub
   account.
5. Distribution mechanism: a zip file Ryan transfers to his work laptop and
   pushes to the work GitHub account from there. No GitHub access from the
   current Mac is required.

## Out of Scope

- Auto-updates
- Multi-Mac config sync
- Linux / Windows support
- The Cloudflare worker / sunset automation (private to Ryan)
- `.app` bundling and code signing
- Pre-installed device exclusion picker (config-file only for v1)

## Architecture

### Two repos, two directories

| Directory | Purpose | Repo |
|---|---|---|
| `~/Development/ActiveApps/govee-sunset-lights/` (existing) | Private dev playground. Untouched by this work. | `empireofryan/govee-sunset-lights` |
| `~/Development/ActiveApps/govee-lights/` (new) | Clean, shareable package. | `<work-username>/govee-lights` (created later) |

The new directory is built fresh from copies of the existing `menubar/icon.png`
and `menubar/com.ryan.govee-lights.plist` (renamed and templated). The
refactored Python code is written from scratch in the new directory; the old
`menubar/govee-lights.py` stays in place in the old repo.

### Public package layout

```
govee-lights/
├── README.md                              public docs (API key, install, config)
├── INSTALL-INSTRUCTIONS.md                Ryan-only notes for pushing to work GitHub (gitignored)
├── install.sh                             extract-and-run installer
├── menubar/
│   ├── govee-lights.py                    refactored entry point
│   ├── config.py                          config loader + first-run flow (NEW)
│   ├── icon.png
│   └── com.user.govee-lights.plist.template
├── requirements.txt                       pyobjc, requests
└── .gitignore
```

### Config file

Path: `~/.config/govee-lights/config.json`

Schema:

```json
{
  "api_key": "abc-123-...",
  "excluded_devices": [],
  "subset_anchors": []
}
```

- `api_key` (required): the user's Govee Developer API key.
- `excluded_devices` (optional, default `[]`): list of device names (strings,
  exactly as returned by the Govee API) to hide from all menus and group
  operations. Equivalent to Ryan's `BUSTED_NAME` constant.
- `subset_anchors` (optional, default `[]`): list of device names that get
  their own "Scenes (minus X)" submenu showing scenes available when device X
  is excluded. Empty by default; advanced feature.

Atomic writes: write to a tempfile in the same directory then `os.replace()`.

## Components

### `menubar/config.py` (new, ~100 lines)

Public API:

- `CONFIG_PATH: Path` — `~/.config/govee-lights/config.json`
- `load() -> dict | None` — return parsed config, or `None` if missing /
  malformed JSON.
- `save(cfg: dict) -> None` — atomic write; creates parent dirs as needed.
- `validate_key(key: str) -> tuple[bool, list[str], str | None]` — calls
  `GET https://openapi.api.govee.com/router/api/v1/user/devices` with the key.
  Returns `(ok, device_names, error_message)`. Distinguishes auth failures
  (HTTP 401 / 403, or HTTP 200 with `code != 200` in the response body, both
  surfaced as `error_message="invalid_key"`) from network / 5xx errors
  (`error_message="network_error"`). The caller maps these tags to the user
  messages in the Error Handling table.
- `prompt_for_api_key(error: str | None = None) -> str | None` — shows a
  native `NSAlert` with `NSTextField` accessory view and three buttons:
  "Save", "Get API Key" (opens Govee developer URL in browser), "Quit".
  Returns the entered key, or `None` if user chose Quit.
- `setup_flow() -> dict` — main entry: loops `prompt_for_api_key` →
  `validate_key`, displays errors inline, on success writes config and shows
  a success NSAlert listing detected device names. Returns the saved config.
- `load_or_setup() -> dict` — if `load()` returns valid config, return it;
  otherwise call `setup_flow()`. If user quits the dialog, raise
  `SystemExit(0)`.

### `menubar/govee-lights.py` (refactored)

Diff vs. existing:

| Existing | Refactored |
|---|---|
| `API_KEY = "00b0d8f5-..."` (line 37) | Removed. App reads `self.config["api_key"]`. |
| `BUSTED_NAME = "Busted"` (line 38) | Removed. `_controllable_devices()` filters by `self.config["excluded_devices"]`. |
| `for exclude_name in ["Table Lamp", "Star Light Projector"]:` (line 201) | `for exclude_name in self.config["subset_anchors"]:` |
| Hardcoded "Busted (skipped)" greyed-out menu item (line 427) | Loop over `self.config["excluded_devices"]`, render one greyed-out item per excluded name. Skipped entirely if list is empty. |
| Constructor proceeds without checking config | Constructor calls `Config.load_or_setup()` first and stores the result on `self.config`. If setup is cancelled, the app exits. |

`api_headers()` becomes a method that reads `self.config["api_key"]`.

No behavioral changes to menu structure, scene fetching, or device control
calls beyond the substitutions above.

### `install.sh` (new)

Runs from inside the unzipped folder. Steps:

1. Determine `SRC` (script's own directory) and `DEST`
   (`~/Library/Application Support/govee-lights`).
2. Create `DEST` and copy `menubar/` into it.
3. Create a venv at `$DEST/venv` and `pip install -r requirements.txt`.
4. Render the plist template: substitute `__APP_DIR__` → `$DEST` and
   `__USER__` → `$USER`, write to
   `$HOME/Library/LaunchAgents/com.user.govee-lights.plist`.
5. `launchctl unload` (ignore errors) then `launchctl load` the plist.
6. Print a final message: "App installed. It will launch and prompt for your
   Govee API key. Get one at https://developer.govee.com/reference/apply-you-api-key"

`set -euo pipefail`. No `sudo` required (everything is per-user).

### `com.user.govee-lights.plist.template`

Same shape as Ryan's existing plist, but with placeholders:

- `Label` → `com.user.govee-lights`
- `ProgramArguments[0]` → `__APP_DIR__/venv/bin/python3`
- `ProgramArguments[1]` → `__APP_DIR__/menubar/govee-lights.py`
- `WorkingDirectory` → `__APP_DIR__`
- `RunAtLoad` → `true`
- `KeepAlive` → `false` (matches Ryan's existing plist; avoids respawn-loop
  if the user quits during the first-run dialog)
- `StandardOutPath` / `StandardErrorPath` → `__APP_DIR__/govee-lights.log`

### `README.md`

Sections:

1. What it is (short paragraph + screenshot)
2. Requirements (macOS, Python 3.9+, a Govee account)
3. Get your API key (step-by-step: Govee Home app → Profile → About Us →
   Apply for API Key. Note: arrives by email in ~5 min.)
4. Install (`unzip` then `./install.sh`)
5. First launch (dialog appears, paste key, done)
6. Configuration (how to edit `~/.config/govee-lights/config.json` for
   exclusions and subset anchors, with examples)
7. Uninstall (`launchctl unload` + remove three directories)
8. Troubleshooting (common issues: launchd not running, key invalid, no
   devices found)

### `INSTALL-INSTRUCTIONS.md` (Ryan-only, gitignored)

Steps Ryan runs on his work laptop after unzipping:

1. `cd ~/Development/govee-lights` (or wherever)
2. `git init && git add . && git commit -m "Initial commit: shareable govee menubar"`
3. Create empty repo on work GitHub: `<work-username>/govee-lights`
4. `git remote add origin git@github.com:<work-username>/govee-lights.git`
5. `git push -u origin main`
6. Update the install URL in `README.md` to point to that repo, commit, push.
7. Test the install flow on a fresh machine if possible (or just on the work
   laptop in a temp dir).

## Data Flow (first-run happy path)

1. launchd starts the app → Python loads → `GoveeLightsApp.init()`.
2. `init()` calls `Config.load_or_setup()`. Config file is missing.
3. `setup_flow()` calls `prompt_for_api_key(error=None)` → modal NSAlert with
   text field. User pastes key, clicks Save.
4. `validate_key()` calls `GET /user/devices`. Returns
   `(True, ["Living Room Lamp", "Bedroom Strip"], None)`.
5. `setup_flow()` calls `save(cfg)` → writes config atomically.
6. Success NSAlert: "Found 2 devices: Living Room Lamp, Bedroom Strip".
7. `setup_flow()` returns the config. `init()` stores `self.config`.
8. Existing flow proceeds: `_init_data()` → `_fetch_devices()` →
   `_fetch_all_scenes()` → `_build_menu()`.

## Error Handling

| Failure | Behavior |
|---|---|
| Missing config file | First-run flow |
| Malformed JSON | Rename existing file to `config.json.bak.<timestamp>`, treat as missing, run first-run flow |
| API key clearly invalid (HTTP 401 / 403, or HTTP 200 with `code != 200` in body) | NSAlert "Invalid API key. Please try again." → re-prompt |
| API network error / timeout / 5xx | NSAlert "Cannot reach Govee. Check your connection and try again." → re-prompt |
| User clicks "Quit" in dialog | App exits with code 0. Because `KeepAlive: false`, launchd does not respawn until next login. |
| Config write fails (permissions) | NSAlert with the error, app exits. |

## Testing Plan

### Pre-zip verification on Ryan's Mac

All steps run against the new `~/Development/ActiveApps/govee-lights/`
package without affecting the existing `govee-sunset-lights` install.

1. **Migrate Ryan's setup to new format:** write
   `~/.config/govee-lights/config.json` with Ryan's real API key,
   `excluded_devices: ["Busted"]`, and
   `subset_anchors: ["Table Lamp", "Star Light Projector"]`.
2. **Quit existing menu bar app** (avoid two instances; the new package uses
   the same single-instance lock).
3. **Run new app directly:**
   `python3 ~/Development/ActiveApps/govee-lights/menubar/govee-lights.py`
4. **Verify:** menu structure matches the screenshot exactly: All Lights On /
   Off, Music Mode (DreamView), Scenes, Scenes (minus Table Lamp), Scenes
   (minus Star Light Projector), Set All Color, Set All Brightness, all 6
   controllable devices, "Busted (skipped)", Refresh, Quit.
5. **Test first-run flow with empty config:** quit app, `mv` config aside,
   re-launch, verify dialog appears.
6. **Test bad-key path:** enter "junk" → verify error message.
7. **Test good-key path:** paste real key → verify success dialog lists the
   7 device names → verify menu builds.
8. **Restore original state:** quit the new app, restore Ryan's config,
   restart the existing menu bar app (or the new one — they're
   functionally equivalent now).
9. **Optional:** run `install.sh` from the package root into a temp dir,
   confirm launchd registration works.

### Zip verification

After producing the zip:
1. Extract to `/tmp/govee-test-extract/`
2. Read every file inside, confirm no API key, no Denver references, no
   personal device names leaked into the public surface.
3. Confirm `INSTALL-INSTRUCTIONS.md` is the only Ryan-specific file and it
   is included in `.gitignore`.

## Open Questions

None. All resolved during brainstorming:
- Scope: menu bar app only (not Cloudflare worker).
- Distribution: zip transferred to work laptop, pushed from there.
- Repo strategy: Option Y — separate clean repo, existing dev repo
  unchanged.
- Exclusion UX: config-file only, no first-run picker.
