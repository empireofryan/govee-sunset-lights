# Govee Lights Distribution Package — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the existing macOS menu bar Govee lights controller into a shareable package (`~/Development/ActiveApps/govee-lights/`) that friends with their own Govee setups can install in under 5 minutes via a zip + `install.sh`. The original `~/Development/ActiveApps/govee-sunset-lights/` repo stays untouched as Ryan's private dev playground.

**Architecture:** Two-file split for the config layer: `menubar/config.py` (pure logic, no AppKit) handles load/save/validate; `menubar/config_dialog.py` (AppKit) handles first-run NSAlert flow. The main `govee-lights.py` is refactored to read all formerly-hardcoded values (API key, excluded devices, subset-scene anchors) from `~/.config/govee-lights/config.json`. Distribution is a self-contained zip the user transfers to a work laptop and pushes to a separate work GitHub repo.

**Tech Stack:** Python 3.9+, pyobjc (AppKit), requests, launchd (plist agent), bash (installer), unittest (stdlib testing).

**Reference spec:** `/Users/ryan/Development/ActiveApps/govee-sunset-lights/docs/superpowers/specs/2026-05-08-govee-lights-distribution-design.md`

---

## File Structure

**New package** at `~/Development/ActiveApps/govee-lights/`:

| File | Responsibility |
|---|---|
| `menubar/config.py` | Pure load/save/validate logic. No AppKit imports — testable in isolation. |
| `menubar/config_dialog.py` | NSAlert UI for first-run flow. Imports config.py + AppKit. |
| `menubar/govee-lights.py` | Main app. Calls `config_dialog.load_or_setup()` on startup. |
| `menubar/icon.png` | Copied verbatim from the existing repo. |
| `menubar/com.user.govee-lights.plist.template` | launchd plist with `__APP_DIR__` placeholder. |
| `tests/test_config.py` | Unit tests for `config.py` (load/save). Run via `python3 -m unittest`. |
| `requirements.txt` | `pyobjc-framework-Cocoa`, `requests` |
| `install.sh` | Sets up venv, copies app to `~/Library/Application Support/govee-lights`, registers launchd agent. |
| `README.md` | Public docs: API key instructions, install, configuration. |
| `INSTALL-INSTRUCTIONS.md` | Ryan-only notes for pushing to work GitHub. Gitignored. |
| `.gitignore` | Excludes `INSTALL-INSTRUCTIONS.md`, `__pycache__`, `*.pyc`, `.venv`, `tests/__pycache__`. |

---

## Task 1: Scaffold the new package directory

**Files:**
- Create: `~/Development/ActiveApps/govee-lights/` (directory only)
- Create: `~/Development/ActiveApps/govee-lights/menubar/` (directory)
- Create: `~/Development/ActiveApps/govee-lights/tests/` (directory)
- Copy: `~/Development/ActiveApps/govee-sunset-lights/menubar/icon.png` → `~/Development/ActiveApps/govee-lights/menubar/icon.png`

- [ ] **Step 1: Create directories**

```bash
mkdir -p ~/Development/ActiveApps/govee-lights/menubar
mkdir -p ~/Development/ActiveApps/govee-lights/tests
```

- [ ] **Step 2: Copy icon**

```bash
cp ~/Development/ActiveApps/govee-sunset-lights/menubar/icon.png \
   ~/Development/ActiveApps/govee-lights/menubar/icon.png
```

- [ ] **Step 3: Verify**

Run: `ls -la ~/Development/ActiveApps/govee-lights/menubar/`
Expected: `icon.png` present, ~5-50 KB.

---

## Task 2: Write `config.py` — load/save with TDD

**Files:**
- Create: `~/Development/ActiveApps/govee-lights/menubar/config.py`
- Create: `~/Development/ActiveApps/govee-lights/tests/test_config.py`
- Create: `~/Development/ActiveApps/govee-lights/tests/__init__.py` (empty, makes tests a package)

- [ ] **Step 1: Write the failing tests**

Create `tests/__init__.py` as an empty file:

```bash
touch ~/Development/ActiveApps/govee-lights/tests/__init__.py
```

Create `tests/test_config.py`:

```python
"""Tests for menubar/config.py — load/save/backup behavior."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Make menubar/ importable
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE.parent / "menubar"))

import config  # noqa: E402


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "config.json"
        self._patcher = patch.object(config, "CONFIG_PATH", self.path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self.tmpdir.cleanup()

    def test_load_returns_none_when_missing(self):
        self.assertIsNone(config.load())

    def test_load_returns_dict_for_valid_json(self):
        self.path.write_text(json.dumps({"api_key": "abc"}))
        cfg = config.load()
        self.assertEqual(cfg, {"api_key": "abc"})

    def test_load_backs_up_and_returns_none_for_malformed_json(self):
        self.path.write_text("{not valid json")
        self.assertIsNone(config.load())
        backups = list(self.path.parent.glob("config.json.bak.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "{not valid json")
        # Original is gone
        self.assertFalse(self.path.exists())

    def test_load_returns_none_when_api_key_missing(self):
        self.path.write_text(json.dumps({"excluded_devices": []}))
        self.assertIsNone(config.load())

    def test_load_returns_none_when_api_key_empty(self):
        self.path.write_text(json.dumps({"api_key": ""}))
        self.assertIsNone(config.load())


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "subdir" / "config.json"
        self._patcher = patch.object(config, "CONFIG_PATH", self.path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self.tmpdir.cleanup()

    def test_save_creates_parent_dir(self):
        config.save({"api_key": "xyz"})
        self.assertTrue(self.path.exists())

    def test_save_round_trips(self):
        cfg = {
            "api_key": "key-123",
            "excluded_devices": ["Busted"],
            "subset_anchors": ["Table Lamp"],
        }
        config.save(cfg)
        loaded = json.loads(self.path.read_text())
        self.assertEqual(loaded, cfg)

    def test_save_is_atomic_no_tempfile_left(self):
        config.save({"api_key": "k"})
        # No leftover .tmp files
        leftover = list(self.path.parent.glob("*.tmp*"))
        self.assertEqual(leftover, [])


class DefaultsTest(unittest.TestCase):
    def test_defaults_has_required_keys(self):
        d = config.defaults()
        self.assertIn("api_key", d)
        self.assertIn("excluded_devices", d)
        self.assertIn("subset_anchors", d)
        self.assertEqual(d["excluded_devices"], [])
        self.assertEqual(d["subset_anchors"], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Development/ActiveApps/govee-lights && python3 -m unittest tests.test_config -v`
Expected: All tests fail with `ModuleNotFoundError: No module named 'config'`.

- [ ] **Step 3: Write `menubar/config.py`**

Create the file:

```python
"""Govee Lights config loader and saver.

Pure logic only. No AppKit imports — keeps this module testable in isolation.
The companion module `config_dialog.py` handles the first-run NSAlert UI.
"""
import json
import os
import time
from pathlib import Path

import requests

CONFIG_PATH = Path.home() / ".config" / "govee-lights" / "config.json"
GOVEE_API = "https://openapi.api.govee.com/router/api/v1"


def defaults() -> dict:
    """Return the default config shape."""
    return {
        "api_key": "",
        "excluded_devices": [],
        "subset_anchors": [],
    }


def load() -> dict | None:
    """Load config from CONFIG_PATH.

    Returns the parsed dict if valid (must have non-empty api_key).
    Returns None if the file is missing, malformed, or lacks an api_key.
    On malformed JSON, backs up the file to config.json.bak.<timestamp>
    so the user does not lose what they had.
    """
    if not CONFIG_PATH.exists():
        return None
    raw = CONFIG_PATH.read_text()
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        backup = CONFIG_PATH.with_suffix(f".json.bak.{int(time.time())}")
        CONFIG_PATH.rename(backup)
        return None
    if not isinstance(cfg, dict) or not cfg.get("api_key"):
        return None
    # Fill in any missing defaults
    merged = defaults()
    merged.update(cfg)
    return merged


def save(cfg: dict) -> None:
    """Atomically write config to CONFIG_PATH. Creates parent dirs."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(f".json.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(cfg, indent=2))
    os.replace(tmp, CONFIG_PATH)


def validate_key(api_key: str) -> tuple[bool, list[str], str | None]:
    """Validate an API key by calling Govee's /user/devices endpoint.

    Returns (ok, device_names, error_tag) where error_tag is one of:
        None             — success
        "invalid_key"    — HTTP 401/403 or response body code != 200
        "network_error"  — timeout, DNS, 5xx, etc.
    """
    headers = {"Content-Type": "application/json", "Govee-API-Key": api_key}
    try:
        res = requests.get(f"{GOVEE_API}/user/devices", headers=headers, timeout=10)
    except requests.RequestException:
        return False, [], "network_error"

    if res.status_code in (401, 403):
        return False, [], "invalid_key"
    if 500 <= res.status_code < 600:
        return False, [], "network_error"
    if res.status_code != 200:
        return False, [], "invalid_key"

    try:
        body = res.json()
    except ValueError:
        return False, [], "network_error"

    if body.get("code") != 200:
        return False, [], "invalid_key"

    devices = body.get("data", [])
    names = [d["deviceName"] for d in devices]
    return True, names, None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/Development/ActiveApps/govee-lights && python3 -m unittest tests.test_config -v`
Expected: All 9 tests pass.

If `requests` is missing, install it: `pip3 install requests` (system or in a venv — tests just need the import to succeed; they don't actually hit the network).

- [ ] **Step 5: Commit**

The plan is being implemented in `~/Development/ActiveApps/govee-lights/` which is not yet a git repo. Skip individual commits during implementation — initialize git as a final step before zipping (Task 12). Continue to next task.

---

## Task 3: Write `config_dialog.py` — NSAlert first-run flow

**Files:**
- Create: `~/Development/ActiveApps/govee-lights/menubar/config_dialog.py`

This module is GUI code (NSAlert + NSTextField). Unit-testing AppKit dialogs requires extensive mocking; instead the spec calls for manual verification on the live app (Task 11). Keep this module thin.

- [ ] **Step 1: Create the file**

```python
"""First-run dialog for collecting and validating the user's Govee API key.

Imports AppKit, so this module is loaded only when the app is running.
Pure logic lives in config.py, which is independently testable.
"""
import sys
import webbrowser

from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSAlertSecondButtonReturn,
    NSAlertThirdButtonReturn,
    NSMakeRect,
    NSTextField,
)

import config

GOVEE_DEVELOPER_URL = "https://developer.govee.com/reference/apply-you-api-key"

_ERROR_MESSAGES = {
    "invalid_key": "That API key was rejected by Govee. Double-check it and try again.",
    "network_error": "Could not reach Govee. Check your internet connection and try again.",
}


def _prompt_for_api_key(error: str | None) -> str | None:
    """Show the API-key input dialog. Returns the entered key, or None if user quit."""
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Welcome to Govee Lights")

    body = "Paste your Govee Developer API key to get started."
    if error:
        body = _ERROR_MESSAGES.get(error, error) + "\n\n" + body
    alert.setInformativeText_(body)

    alert.addButtonWithTitle_("Save")
    alert.addButtonWithTitle_("Get API Key")
    alert.addButtonWithTitle_("Quit")

    field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 320, 24))
    field.setPlaceholderString_("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    alert.setAccessoryView_(field)

    while True:
        response = alert.runModal()
        if response == NSAlertFirstButtonReturn:
            key = field.stringValue().strip()
            if key:
                return key
            # Empty input: re-show the same dialog
            continue
        if response == NSAlertSecondButtonReturn:
            webbrowser.open(GOVEE_DEVELOPER_URL)
            # Re-show dialog after opening browser
            continue
        if response == NSAlertThirdButtonReturn:
            return None
        return None


def _show_success(device_names: list[str]) -> None:
    alert = NSAlert.alloc().init()
    alert.setMessageText_("Connected!")
    n = len(device_names)
    listing = ", ".join(device_names) if device_names else "(none)"
    alert.setInformativeText_(
        f"Found {n} device{'s' if n != 1 else ''}: {listing}"
    )
    alert.addButtonWithTitle_("OK")
    alert.runModal()


def setup_flow() -> dict:
    """Run first-run setup. Returns the saved config, or exits the app on cancel."""
    error: str | None = None
    while True:
        key = _prompt_for_api_key(error)
        if key is None:
            sys.exit(0)
        ok, device_names, err = config.validate_key(key)
        if ok:
            cfg = config.defaults()
            cfg["api_key"] = key
            config.save(cfg)
            _show_success(device_names)
            return cfg
        error = err


def load_or_setup() -> dict:
    """Return existing config if valid; otherwise run first-run setup."""
    cfg = config.load()
    if cfg is not None:
        return cfg
    return setup_flow()
```

- [ ] **Step 2: Smoke-import the module**

Run: `cd ~/Development/ActiveApps/govee-lights/menubar && python3 -c "import config_dialog; print('OK')"`
Expected: prints `OK`. If `ModuleNotFoundError: No module named 'AppKit'`, install pyobjc: `pip3 install pyobjc-framework-Cocoa`.

- [ ] **Step 3: Re-run config tests**

Run: `cd ~/Development/ActiveApps/govee-lights && python3 -m unittest tests.test_config -v`
Expected: all 9 tests still pass.

---

## Task 4: Refactor `govee-lights.py` — read everything from config

**Files:**
- Create: `~/Development/ActiveApps/govee-lights/menubar/govee-lights.py` (new file, copied from existing then modified)

Start by copying the existing app verbatim, then apply the four changes below.

- [ ] **Step 1: Copy existing app as starting point**

```bash
cp ~/Development/ActiveApps/govee-sunset-lights/menubar/govee-lights.py \
   ~/Development/ActiveApps/govee-lights/menubar/govee-lights.py
```

- [ ] **Step 2: Replace hardcoded constants and add config import**

Open `~/Development/ActiveApps/govee-lights/menubar/govee-lights.py`.

**Find** (lines ~33-42):

```python
from Foundation import NSObject, NSTimer
from PyObjCTools import AppHelper

GOVEE_API = "https://openapi.api.govee.com/router/api/v1"
API_KEY = "00b0d8f5-c2cb-4b42-9522-bbcf94492b86"
BUSTED_NAME = "Busted"
ICON_PATH = Path(__file__).parent / "icon.png"
DREAMVIEW_CAP = "devices.capabilities.toggle:dreamViewToggle"
COLOR_CAP = "devices.capabilities.color_setting:colorRgb"
BRIGHTNESS_CAP = "devices.capabilities.range:brightness"
```

**Replace with:**

```python
from Foundation import NSObject, NSTimer
from PyObjCTools import AppHelper

import config_dialog

GOVEE_API = "https://openapi.api.govee.com/router/api/v1"
ICON_PATH = Path(__file__).parent / "icon.png"
DREAMVIEW_CAP = "devices.capabilities.toggle:dreamViewToggle"
COLOR_CAP = "devices.capabilities.color_setting:colorRgb"
BRIGHTNESS_CAP = "devices.capabilities.range:brightness"
```

(`API_KEY` and `BUSTED_NAME` constants removed entirely.)

- [ ] **Step 3: Replace `api_headers` with a method**

**Find** (lines ~59-60):

```python
def api_headers():
    return {"Content-Type": "application/json", "Govee-API-Key": API_KEY}
```

**Replace with:** delete this function entirely. We'll inline the headers as a method on the class in the next step.

- [ ] **Step 4: Update `init()` to load config and define `api_headers` as a method**

**Find** (lines ~63-73):

```python
class GoveeLightsApp(NSObject):
    def init(self):
        self = objc.super(GoveeLightsApp, self).init()
        if self is None:
            return None
        self.devices = []
        self.scene_map = {}
        self._color_target = None
        self.setup_statusbar()
        threading.Thread(target=self._init_data, daemon=True).start()
        return self
```

**Replace with:**

```python
class GoveeLightsApp(NSObject):
    def init(self):
        self = objc.super(GoveeLightsApp, self).init()
        if self is None:
            return None
        self.config = config_dialog.load_or_setup()
        self.devices = []
        self.scene_map = {}
        self._color_target = None
        self.setup_statusbar()
        threading.Thread(target=self._init_data, daemon=True).start()
        return self

    @objc.python_method
    def api_headers(self):
        return {
            "Content-Type": "application/json",
            "Govee-API-Key": self.config["api_key"],
        }
```

- [ ] **Step 5: Update all `api_headers()` callers to `self.api_headers()`**

There are two call sites:
- `_fetch_devices()` (line ~120): `headers=api_headers()` → `headers=self.api_headers()`
- `_fetch_all_scenes()` (line ~152): `headers=api_headers()` → `headers=self.api_headers()`
- `_send_control()` (line ~454): `headers=api_headers()` → `headers=self.api_headers()`

Use Edit's `replace_all` to swap `headers=api_headers()` → `headers=self.api_headers()` (3 occurrences).

- [ ] **Step 6: Replace `BUSTED_NAME` with config-driven exclusions**

**Find** (line ~471-473):

```python
    @objc.python_method
    def _controllable_devices(self):
        return [d for d in self.devices if d["name"] != BUSTED_NAME]
```

**Replace with:**

```python
    @objc.python_method
    def _controllable_devices(self):
        excluded = set(self.config.get("excluded_devices", []))
        return [d for d in self.devices if d["name"] not in excluded]
```

Then search for any other reference to `BUSTED_NAME` in the file:

Run: `grep -n BUSTED_NAME ~/Development/ActiveApps/govee-lights/menubar/govee-lights.py`

Replace each remaining occurrence:
- `if d["name"] == BUSTED_NAME:` → `if d["name"] in self.config.get("excluded_devices", []):`
- `if d["name"] != BUSTED_NAME` → `if d["name"] not in self.config.get("excluded_devices", [])`

After all replacements, `grep BUSTED_NAME` should return nothing.

- [ ] **Step 7: Replace hardcoded subset device list**

**Find** (line ~201):

```python
        for exclude_name in ["Table Lamp", "Star Light Projector"]:
```

**Replace with:**

```python
        for exclude_name in self.config.get("subset_anchors", []):
```

- [ ] **Step 8: Replace hardcoded "Busted (skipped)" menu item with a loop over excluded devices**

**Find** (lines ~426-432):

```python
        # Busted
        busted_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Busted (skipped)", None, ""
        )
        busted_item.setEnabled_(False)
        menu.addItem_(busted_item)
        menu.addItem_(NSMenuItem.separatorItem())
```

**Replace with:**

```python
        # Excluded devices (informational, not actionable)
        excluded = self.config.get("excluded_devices", [])
        if excluded:
            for name in excluded:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    f"{name} (excluded)", None, ""
                )
                item.setEnabled_(False)
                menu.addItem_(item)
            menu.addItem_(NSMenuItem.separatorItem())
```

- [ ] **Step 9: Verify the refactor compiles**

Run: `cd ~/Development/ActiveApps/govee-lights/menubar && python3 -c "import ast; ast.parse(open('govee-lights.py').read()); print('OK')"`
Expected: `OK`. (Pure syntax check; behavioral verification is Task 11.)

- [ ] **Step 10: Confirm no hardcoded values remain**

```bash
grep -nE 'API_KEY|BUSTED_NAME|"Busted"|"Table Lamp"|"Star Light Projector"|00b0d8f5' \
    ~/Development/ActiveApps/govee-lights/menubar/govee-lights.py
```

Expected: no matches.

---

## Task 5: Write `requirements.txt` and `.gitignore`

**Files:**
- Create: `~/Development/ActiveApps/govee-lights/requirements.txt`
- Create: `~/Development/ActiveApps/govee-lights/.gitignore`

- [ ] **Step 1: requirements.txt**

```
pyobjc-framework-Cocoa>=9.0
requests>=2.28
```

- [ ] **Step 2: .gitignore**

```
# Ryan-only notes, not for the public repo
INSTALL-INSTRUCTIONS.md

# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/

# Local venvs
.venv/
venv/

# macOS
.DS_Store
```

---

## Task 6: Write the launchd plist template

**Files:**
- Create: `~/Development/ActiveApps/govee-lights/menubar/com.user.govee-lights.plist.template`

- [ ] **Step 1: Create the template**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.govee-lights</string>
    <key>ProgramArguments</key>
    <array>
        <string>__APP_DIR__/venv/bin/python3</string>
        <string>__APP_DIR__/menubar/govee-lights.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>__APP_DIR__</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>__APP_DIR__/govee-lights.log</string>
    <key>StandardErrorPath</key>
    <string>__APP_DIR__/govee-lights.log</string>
</dict>
</plist>
```

---

## Task 7: Write `install.sh`

**Files:**
- Create: `~/Development/ActiveApps/govee-lights/install.sh`

- [ ] **Step 1: Write the installer**

```bash
#!/usr/bin/env bash
# Installer for Govee Lights menu bar app.
# Run from inside the unzipped/cloned package root.

set -euo pipefail

# Resolve the directory this script lives in (the package root).
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/Library/Application Support/govee-lights"
PLIST="$HOME/Library/LaunchAgents/com.user.govee-lights.plist"

echo "==> Installing Govee Lights"
echo "    Source: $SRC"
echo "    Target: $DEST"

# 1. Copy menubar/ into ~/Library/Application Support/govee-lights
mkdir -p "$DEST"
rm -rf "$DEST/menubar"
cp -R "$SRC/menubar" "$DEST/menubar"

# 2. Set up venv and install deps
if [ ! -d "$DEST/venv" ]; then
    echo "==> Creating Python virtual environment"
    python3 -m venv "$DEST/venv"
fi
echo "==> Installing dependencies (this may take a minute)"
"$DEST/venv/bin/pip" install --quiet --upgrade pip
"$DEST/venv/bin/pip" install --quiet -r "$SRC/requirements.txt"

# 3. Render plist template
echo "==> Registering launchd agent"
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__APP_DIR__|$DEST|g" \
    "$DEST/menubar/com.user.govee-lights.plist.template" > "$PLIST"

# 4. Reload launchd agent
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "==> Done!"
echo "    The menu bar app is starting now."
echo "    A dialog will appear asking for your Govee API key."
echo ""
echo "    Don't have an API key yet?"
echo "    1. Open the Govee Home app on your phone"
echo "    2. Profile (bottom-right) -> About Us -> Apply for API Key"
echo "    3. Fill in name + reason ('personal use'), submit"
echo "    4. Key arrives by email in ~5 minutes"
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x ~/Development/ActiveApps/govee-lights/install.sh
```

- [ ] **Step 3: Lint with bash -n**

Run: `bash -n ~/Development/ActiveApps/govee-lights/install.sh`
Expected: no output (syntax OK).

---

## Task 8: Write `README.md`

**Files:**
- Create: `~/Development/ActiveApps/govee-lights/README.md`

- [ ] **Step 1: Write the public README**

```markdown
# Govee Lights — macOS Menu Bar Controller

Control your Govee smart lights from a tiny icon in your Mac's menu bar.
All your lights, scenes, and music modes — one click away.

![Menu bar screenshot](docs/screenshot.png)

## Features

- **All Lights On/Off** — instant control of every light at once
- **Scenes** — apply any Govee preset scene across all lights, plus per-device scene menus
- **Music Mode (DreamView)** — toggle DreamView sync on capable devices
- **Color & Brightness** — preset colors, native macOS color picker, brightness levels
- **Per-device control** — every light gets its own submenu (on/off, color, brightness, scenes)
- **Auto-discovers your devices** — no per-light configuration needed

## Requirements

- macOS (tested on Sonoma and later)
- Python 3.9+
- A Govee account with at least one paired light
- A Govee Developer API key (free, instructions below)

## Get a Govee API Key

1. Open the **Govee Home** app on your phone
2. Tap **Profile** (bottom-right)
3. Tap **About Us** → **Apply for API Key**
4. Enter your name and reason (e.g. "personal use")
5. Submit. The key arrives by email within ~5 minutes.

## Install

```bash
unzip govee-lights.zip
cd govee-lights
./install.sh
```

The installer:
- Copies the app into `~/Library/Application Support/govee-lights`
- Creates a Python virtual environment with the required dependencies
- Registers a `launchd` agent so the app starts automatically on login

After install, the menu bar icon appears and a dialog asks for your API key.
Paste it in, click **Save**, and your lights populate the menu.

## Configuration

The app stores its config at `~/.config/govee-lights/config.json`:

```json
{
  "api_key": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "excluded_devices": [],
  "subset_anchors": []
}
```

### `excluded_devices`

Names of lights to hide from menus and group operations. Useful for broken
bulbs or lights you don't want included in "All Lights On". Names must match
exactly what Govee's API returns (the names in your Govee Home app).

```json
"excluded_devices": ["Garage Light", "Old Strip"]
```

### `subset_anchors`

For each name in this list, the app adds an extra "Scenes (minus X)" submenu
that shows scenes available when light X is excluded. Useful for setups
where one light supports a different scene catalog than the others.

```json
"subset_anchors": ["Bedroom Lamp"]
```

After editing the config, click **Refresh Devices** in the menu (or quit and
relaunch) to apply changes.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.user.govee-lights.plist
rm ~/Library/LaunchAgents/com.user.govee-lights.plist
rm -rf ~/Library/Application\ Support/govee-lights
rm -rf ~/.config/govee-lights
```

## Troubleshooting

**Menu bar icon doesn't appear after install**
Check the log: `tail ~/Library/Application\ Support/govee-lights/govee-lights.log`

**"Invalid API key" error**
Re-check the key in your Govee email. Keys are case-sensitive. If it's been
many months, the key may have expired — re-apply.

**No devices found**
Make sure your Govee account has at least one Wi-Fi-connected light. Some
older / Bluetooth-only Govee lights aren't accessible via the API.

**App doesn't auto-start**
Re-run `./install.sh`. If that fails, check `launchctl list | grep govee` —
should show `com.user.govee-lights`.

## License

MIT.
```

---

## Task 9: Write `INSTALL-INSTRUCTIONS.md` (Ryan-only)

**Files:**
- Create: `~/Development/ActiveApps/govee-lights/INSTALL-INSTRUCTIONS.md`

This file is gitignored (Task 5) so it never lands in the public repo.

- [ ] **Step 1: Write the instructions**

```markdown
# How to publish this package to your work GitHub

This file is for Ryan only. It is gitignored and will NOT appear in the
public repo.

## On the work laptop

1. Transfer `govee-lights-v1.zip` from the personal Mac (AirDrop, USB, etc.).
2. Unzip somewhere convenient:
   ```bash
   unzip govee-lights-v1.zip -d ~/Development/
   cd ~/Development/govee-lights
   ```
3. Initialize git:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: shareable govee menubar"
   ```
4. Create an empty repo on the work GitHub account (web UI):
   `<work-username>/govee-lights`. **Do not** add a README or .gitignore in
   the GitHub UI; this would conflict with the local commit.
5. Add the remote and push:
   ```bash
   git remote add origin git@github.com:<work-username>/govee-lights.git
   git push -u origin main
   ```
6. (Optional) Update the install URL in `README.md` if you want to add a
   one-line `curl | bash` flow later. The current zip-based install does
   not need a URL.

## Sharing with friends

Just send them the zip. They run:
```bash
unzip govee-lights.zip
cd govee-lights
./install.sh
```

That's it.
```

---

## Task 10: Manual verification on Ryan's live setup

**Files:** none modified.

This task verifies the refactored app works against the real Govee API and
matches the menu structure in Ryan's screenshot. All steps run on Ryan's
personal Mac.

- [ ] **Step 1: Install requests + pyobjc system-wide if missing**

Run: `python3 -c "import requests, AppKit; print('OK')"`
Expected: `OK`. If either import fails, install with `pip3 install --user pyobjc-framework-Cocoa requests`.

- [ ] **Step 2: Quit the existing menu bar app**

Run: `pkill -f "menubar/govee-lights.py" || true`
Then verify: `pgrep -f "govee-lights.py" || echo "no instance running"`

- [ ] **Step 3: Migrate config to new format**

Find Ryan's existing API key from the old hardcoded value:

Run: `grep -E '^API_KEY' ~/Development/ActiveApps/govee-sunset-lights/menubar/govee-lights.py`

Use that value to write the new config:

```bash
mkdir -p ~/.config/govee-lights
cat > ~/.config/govee-lights/config.json <<'JSON'
{
  "api_key": "00b0d8f5-c2cb-4b42-9522-bbcf94492b86",
  "excluded_devices": ["Busted"],
  "subset_anchors": ["Table Lamp", "Star Light Projector"]
}
JSON
```

- [ ] **Step 4: Run the new app directly**

Run (in a Terminal window, leave it open to see logs):

```bash
cd ~/Development/ActiveApps/govee-lights/menubar
python3 govee-lights.py
```

Expected:
- No first-run dialog (config already valid)
- Menu bar icon appears
- Click the icon: menu structure should match Ryan's screenshot exactly:
  - All Lights On / All Lights Off
  - Music Mode (DreamView) → ON / OFF
  - Scenes →
  - Scenes (minus Table Lamp) →
  - Scenes (minus Star Light Projector) →
  - Set All Color → / Set All Brightness →
  - Left Corner Light, Uplighter Floor Lamp, Table Lamp, Right Corner Light, Star Light Projector, Side Light (each with submenu)
  - Busted (excluded)  ← was "Busted (skipped)" before; now "Busted (excluded)"
  - Refresh Devices / Quit

- [ ] **Step 5: Smoke-test a control action**

Click "All Lights Off" (only if it's not currently a critical lighting moment in Ryan's room). Lights should turn off. Click "All Lights On" to restore.

- [ ] **Step 6: Test a scene**

Pick any scene from the Scenes submenu (e.g., "Sunrise"). All non-Busted lights should turn on and apply that scene.

- [ ] **Step 7: Quit, then test first-run flow with empty config**

```bash
# Quit the running test app first (Ctrl+C in the Terminal, or Quit from menu)
mv ~/.config/govee-lights/config.json ~/.config/govee-lights/config.json.real-backup
cd ~/Development/ActiveApps/govee-lights/menubar
python3 govee-lights.py
```

Expected: NSAlert dialog appears: "Welcome to Govee Lights".

- [ ] **Step 8: Test the bad-key path**

Type "junk" into the field, click Save.
Expected: dialog re-shows with error "That API key was rejected by Govee. Double-check it and try again."

- [ ] **Step 9: Test the "Get API Key" button**

Click "Get API Key".
Expected: default browser opens to https://developer.govee.com/reference/apply-you-api-key . Dialog re-appears.

- [ ] **Step 10: Test the good-key path**

Paste the real API key (`00b0d8f5-c2cb-4b42-9522-bbcf94492b86`), click Save.
Expected:
1. "Connected!" success dialog listing 7 device names.
2. Click OK. Menu bar populates with all 7 devices (no exclusions, since the new config defaults to empty `excluded_devices`).
3. Verify `~/.config/govee-lights/config.json` now contains the key with empty exclusion lists.

- [ ] **Step 11: Test the Quit button**

Quit this test app (Ctrl+C). Move config aside again, relaunch app, click Quit on the dialog.
Expected: app exits cleanly with no error.

- [ ] **Step 12: Restore Ryan's real config and resume normal operation**

```bash
# Quit any running test instance first
pkill -f "menubar/govee-lights.py" || true
rm -f ~/.config/govee-lights/config.json
mv ~/.config/govee-lights/config.json.real-backup ~/.config/govee-lights/config.json
# Optionally, restart the OLD app (which uses the hardcoded key, so unaffected by config)
launchctl kickstart -k gui/$UID/com.ryan.govee-lights 2>/dev/null || true
```

Verify the menu bar icon is back and functional.

- [ ] **Step 13: Run unit tests one more time**

Run: `cd ~/Development/ActiveApps/govee-lights && python3 -m unittest tests.test_config -v`
Expected: all tests pass.

If any of Steps 4-12 failed, debug and fix before proceeding to Task 11. Common issues:
- "Module not found" → install deps with pip
- Lockfile conflict ("Already running") → `rm ~/.govee-lights-menubar.lock` and retry
- Menu structure mismatch → re-grep for `BUSTED_NAME` / `"Busted"` / hardcoded names

---

## Task 11: Initialize git and produce the zip

**Files:**
- Create: `~/Desktop/govee-lights-v1.zip`

- [ ] **Step 1: Initialize git in the new package**

```bash
cd ~/Development/ActiveApps/govee-lights
git init -q
git add .
git status   # confirm INSTALL-INSTRUCTIONS.md is NOT staged (gitignored)
```

Expected: `git status` shows `README.md`, `install.sh`, `requirements.txt`, `.gitignore`, `menubar/...`, `tests/...` staged, but NOT `INSTALL-INSTRUCTIONS.md`.

- [ ] **Step 2: Commit**

```bash
git commit -q -m "Initial commit: shareable govee-lights menubar package"
```

- [ ] **Step 3: Audit the zip-bound contents for personal data leaks**

Run: `grep -rE '00b0d8f5|empireofryan|rjohnson2001|ryan@|/Users/ryan|"Busted"|"Table Lamp"|"Star Light Projector"|Denver|sunset' ~/Development/ActiveApps/govee-lights/ --include='*.py' --include='*.md' --include='*.sh' --include='*.template' --include='*.txt'`

Expected: ZERO matches. (`INSTALL-INSTRUCTIONS.md` may match `<work-username>` template text, that's fine.)

If any leak is found, fix it before proceeding.

- [ ] **Step 4: Create the zip**

```bash
cd ~/Development/ActiveApps
zip -r ~/Desktop/govee-lights-v1.zip govee-lights \
    -x 'govee-lights/.git/*' \
    -x 'govee-lights/__pycache__/*' \
    -x 'govee-lights/**/__pycache__/*' \
    -x 'govee-lights/.DS_Store' \
    -x 'govee-lights/**/.DS_Store'
```

Expected: zip created at `~/Desktop/govee-lights-v1.zip`, ~50-200 KB.

- [ ] **Step 5: Verify the zip is clean**

```bash
unzip -l ~/Desktop/govee-lights-v1.zip
```

Expected listing (order may vary):

```
govee-lights/
govee-lights/.gitignore
govee-lights/INSTALL-INSTRUCTIONS.md
govee-lights/README.md
govee-lights/install.sh
govee-lights/requirements.txt
govee-lights/menubar/
govee-lights/menubar/com.user.govee-lights.plist.template
govee-lights/menubar/config.py
govee-lights/menubar/config_dialog.py
govee-lights/menubar/govee-lights.py
govee-lights/menubar/icon.png
govee-lights/tests/
govee-lights/tests/__init__.py
govee-lights/tests/test_config.py
```

No `.git/`, no `__pycache__/`, no `.DS_Store`.

- [ ] **Step 6: Test extraction in a temp dir**

```bash
mkdir -p /tmp/govee-zip-test
cd /tmp/govee-zip-test
unzip -q ~/Desktop/govee-lights-v1.zip
ls govee-lights/
bash -n govee-lights/install.sh   # syntax check the installer
python3 -c "import ast; ast.parse(open('govee-lights/menubar/govee-lights.py').read()); print('main app OK')"
python3 -c "import ast; ast.parse(open('govee-lights/menubar/config.py').read()); print('config OK')"
python3 -c "import ast; ast.parse(open('govee-lights/menubar/config_dialog.py').read()); print('config_dialog OK')"
rm -rf /tmp/govee-zip-test
```

Expected: all three "OK" lines, no errors.

- [ ] **Step 7: Final summary message to Ryan**

Print the absolute path of the zip and a short usage note:

```
Zip ready: ~/Desktop/govee-lights-v1.zip
Transfer this to your work laptop, then follow the steps in
INSTALL-INSTRUCTIONS.md (inside the zip) to push to your work GitHub.
```

---

## Self-Review

**Spec coverage check:**

- ✅ Goal — addressed by entire plan
- ✅ Two repos / two directories — Task 1 + Task 11 (git init in new dir only)
- ✅ Public package layout — Tasks 1, 2, 3, 4, 5, 6, 7, 8, 9
- ✅ Config file format — Task 2 (`config.py` + tests)
- ✅ `config.py` interface (load, save, validate_key) — Task 2
- ✅ NSAlert first-run flow — Task 3 (`config_dialog.py`)
- ✅ Refactor table (API_KEY, BUSTED_NAME, subset list, greyed-out items) — Task 4 (steps 2-8)
- ✅ `install.sh` — Task 7
- ✅ plist template — Task 6
- ✅ README.md — Task 8
- ✅ INSTALL-INSTRUCTIONS.md — Task 9
- ✅ Data flow / first-run happy path — exercised in Task 10 step 10
- ✅ Error handling table (malformed JSON, invalid key, network, quit) — Task 2 tests cover load behavior; Task 10 steps 8 and 11 cover invalid key and quit
- ✅ Pre-zip verification testing plan — Task 10
- ✅ Zip verification — Task 11 step 5-6
- ✅ Personal data leak audit — Task 11 step 3

**Placeholder scan:** none found. All steps contain actual code, exact paths, exact commands.

**Type consistency:** `Config.load_or_setup()` in spec matches `config_dialog.load_or_setup()` in plan (functions, not class methods, since `config.py` and `config_dialog.py` are modules with module-level functions, not classes — this is a deliberate simplification noted by removing the `Config` class wrapper from the spec; the public API surface is module-level functions).
