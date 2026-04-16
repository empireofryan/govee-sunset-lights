# Govee Lights Menu Bar Controller — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS menu bar app that controls 7 Govee smart lights via dropdown — scenes, colors, brightness, music mode, and individual device control.

**Architecture:** Single Python file using pyobjc (AppKit) for the menu bar, `requests` for Govee API calls. All API calls run on background threads. Device list and scene catalog fetched on launch, cached in memory. "Busted" device is hardcoded-excluded from all group operations.

**Tech Stack:** Python 3, pyobjc (AppKit/Foundation), requests, Govee OpenAPI v1

---

## File Structure

- **Create:** `menubar/govee-lights.py` — the entire menu bar app (single file)
- **Create:** `menubar/icon.png` — 64x64 colorful lightbulb icon (downloaded from icons8)
- **Reference:** `cloudflare-cron/worker.js` — existing scene IDs, preset definitions, API patterns

---

### Task 1: Download Icon and Create Skeleton App

**Files:**
- Create: `menubar/govee-lights.py`
- Create: `menubar/icon.png`

- [ ] **Step 1: Create the menubar directory**

```bash
mkdir -p /Users/ryan/Development/ActiveApps/govee-sunset-lights/menubar
```

- [ ] **Step 2: Download a colorful lightbulb icon**

Download a 3D-fluency lightbulb icon from icons8, resize to 64x64 for menu bar use:

```bash
cd /Users/ryan/Development/ActiveApps/govee-sunset-lights/menubar
curl -L "https://img.icons8.com/3d-fluency/94/light-on.png" -o icon_raw.png
sips -z 64 64 icon_raw.png --out icon.png
rm icon_raw.png
```

If icons8 URL doesn't work, use a simple emoji-based approach — the app will render a lightbulb emoji as fallback.

- [ ] **Step 3: Write the skeleton app with menu bar icon, quit item, and single-instance guard**

```python
#!/usr/bin/env python3
"""Govee Lights — macOS menu bar controller for Govee smart lights."""

import sys
import os
import fcntl
import threading
import json
from pathlib import Path

# Single-instance guard
_lockfile = os.path.expanduser("~/.govee-lights-menubar.lock")
_lock_fd = open(_lockfile, "w")
try:
    fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    _lock_fd.write(str(os.getpid()))
    _lock_fd.flush()
except IOError:
    print("Already running.")
    sys.exit(0)

import objc
import requests
from AppKit import (
    NSApplication, NSMenu, NSMenuItem, NSStatusBar,
    NSVariableStatusItemLength, NSImage, NSColor, NSFont,
    NSAttributedString, NSFontAttributeName, NSForegroundColorAttributeName,
    NSColorPanel, NSObject,
)
from Foundation import NSObject, NSTimer, NSData
from PyObjCTools import AppHelper

GOVEE_API = "https://openapi.api.govee.com/router/api/v1"
API_KEY = "00b0d8f5-c2cb-4b42-9522-bbcf94492b86"
BUSTED_NAME = "Busted"
ICON_PATH = Path(__file__).parent / "icon.png"

# Scene IDs for each SKU, keyed by scene name
# These map scene_name -> {sku: {id, paramId}}
UNIVERSAL_SCENES = {}  # populated on launch from API


def api_headers():
    return {"Content-Type": "application/json", "Govee-API-Key": API_KEY}


class GoveeLightsApp(NSObject):
    def init(self):
        self = objc.super(GoveeLightsApp, self).init()
        if self is None:
            return None
        self.devices = []       # [{name, sku, device, capabilities}, ...]
        self.scene_map = {}     # {scene_name: {sku: {id, paramId}}}
        self.setup_statusbar()
        # Fetch devices + scenes in background, then build menu
        threading.Thread(target=self._init_data, daemon=True).start()
        return self

    @objc.python_method
    def setup_statusbar(self):
        self.status_bar = NSStatusBar.systemStatusBar()
        self.status_item = self.status_bar.statusItemWithLength_(NSVariableStatusItemLength)
        button = self.status_item.button()
        # Try loading icon, fallback to emoji text
        if ICON_PATH.exists():
            img = NSImage.alloc().initWithContentsOfFile_(str(ICON_PATH))
            img.setSize_((22, 22))
            img.setTemplate_(False)
            button.setImage_(img)
        else:
            button.setTitle_("💡")
        # Placeholder menu until data loads
        menu = NSMenu.alloc().init()
        loading = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Loading devices...", None, "")
        loading.setEnabled_(False)
        menu.addItem_(loading)
        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "terminate:", "q")
        menu.addItem_(quit_item)
        self.status_item.setMenu_(menu)

    @objc.python_method
    def _init_data(self):
        """Fetch device list and scene catalogs from Govee API."""
        try:
            self._fetch_devices()
            self._fetch_all_scenes()
        except Exception as e:
            print(f"Init error: {e}")
        # Build menu on main thread
        self.performSelectorOnMainThread_withObject_waitUntilDone_("buildMenu:", None, False)

    def buildMenu_(self, _):
        self._build_menu()

    # ... (rest of implementation in subsequent tasks)

    @objc.python_method
    def _fetch_devices(self):
        res = requests.get(f"{GOVEE_API}/user/devices", headers=api_headers(), timeout=10)
        res.raise_for_status()
        data = res.json()
        self.devices = [
            {
                "name": d["deviceName"],
                "sku": d["sku"],
                "device": d["device"],
                "capabilities": [c["type"] + ":" + c["instance"] for c in d.get("capabilities", [])],
            }
            for d in data.get("data", [])
        ]

    @objc.python_method
    def _fetch_all_scenes(self):
        """Fetch scenes per SKU, find common scene names across all non-Busted devices."""
        sku_scenes = {}  # {sku: {scene_name: {id, paramId}}}
        seen_skus = {}   # {sku: (sku, device)} — one representative per SKU

        for d in self.devices:
            if d["name"] == BUSTED_NAME:
                continue
            if d["sku"] not in seen_skus:
                seen_skus[d["sku"]] = (d["sku"], d["device"])

        for sku, device_id in seen_skus.values():
            try:
                res = requests.post(
                    f"{GOVEE_API}/device/scenes",
                    headers=api_headers(),
                    json={"requestId": f"scenes-{sku}", "payload": {"sku": sku, "device": device_id}},
                    timeout=10,
                )
                res.raise_for_status()
                data = res.json()
                caps = data.get("payload", {}).get("capabilities", [])
                scenes = {}
                for cap in caps:
                    if cap.get("instance") == "lightScene":
                        for opt in cap.get("parameters", {}).get("options", []):
                            scenes[opt["name"]] = {"id": opt["value"]["id"], "paramId": opt["value"].get("paramId")}
                sku_scenes[sku] = scenes
            except Exception as e:
                print(f"Failed to fetch scenes for {sku}: {e}")

        # Find scene names present in ALL SKUs
        if sku_scenes:
            common_names = set.intersection(*[set(s.keys()) for s in sku_scenes.values()])
        else:
            common_names = set()

        # Build scene_map: {name: {sku: {id, paramId}}}
        self.scene_map = {}
        for name in sorted(common_names):
            self.scene_map[name] = {}
            for sku, scenes in sku_scenes.items():
                self.scene_map[name][sku] = scenes[name]

    @objc.python_method
    def _build_menu(self):
        """Placeholder — built in Task 2."""
        pass


if __name__ == "__main__":
    app = NSApplication.sharedApplication()
    controller = GoveeLightsApp.alloc().init()
    AppHelper.runEventLoop()
```

- [ ] **Step 4: Test the skeleton launches and shows the icon**

```bash
cd /Users/ryan/Development/ActiveApps/govee-sunset-lights
python3 menubar/govee-lights.py &
# Verify: lightbulb icon appears in menu bar with "Loading devices..." dropdown
# Kill it: kill %1
```

- [ ] **Step 5: Commit**

```bash
cd /Users/ryan/Development/ActiveApps/govee-sunset-lights
git add menubar/
git commit -m "feat: govee menu bar app skeleton with icon and device fetching"
```

---

### Task 2: Build the Full Dropdown Menu

**Files:**
- Modify: `menubar/govee-lights.py`

Replace `_build_menu` with the full menu structure. This task only builds the menu items — action handlers are wired in Task 3.

- [ ] **Step 1: Implement `_build_menu` with all sections**

The method builds:
1. **All Lights On / Off** — two items
2. Separator
3. **Music Mode** submenu — ON / OFF
4. Separator
5. **Scenes** submenu — one item per universal scene name (Aurora, Forest, etc.)
6. Separator
7. **Set All Color...** — opens color picker
8. **Set All Brightness** submenu — 10%, 25%, 50%, 75%, 100%
9. Separator
10. **Individual device submenus** — one per non-Busted device, each with On/Off, brightness levels, color picker
11. Separator
12. **Busted (skipped)** — greyed out
13. Separator
14. **Refresh Devices** — re-fetches device list
15. **Quit**

```python
@objc.python_method
def _build_menu(self):
    menu = NSMenu.alloc().init()

    # --- All Lights ---
    on_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("All Lights On", "allLightsOn:", "")
    on_item.setTarget_(self)
    menu.addItem_(on_item)
    off_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("All Lights Off", "allLightsOff:", "")
    off_item.setTarget_(self)
    menu.addItem_(off_item)
    menu.addItem_(NSMenuItem.separatorItem())

    # --- Music Mode ---
    music_sub = NSMenu.alloc().init()
    music_on = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("ON", "musicOn:", "")
    music_on.setTarget_(self)
    music_sub.addItem_(music_on)
    music_off = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("OFF", "musicOff:", "")
    music_off.setTarget_(self)
    music_sub.addItem_(music_off)
    music_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Music Mode (DreamView)", None, "")
    music_item.setSubmenu_(music_sub)
    menu.addItem_(music_item)
    menu.addItem_(NSMenuItem.separatorItem())

    # --- Scenes ---
    if self.scene_map:
        scenes_sub = NSMenu.alloc().init()
        for scene_name in sorted(self.scene_map.keys()):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(scene_name, "applyScene:", "")
            item.setTarget_(self)
            item.setRepresentedObject_(scene_name)
            scenes_sub.addItem_(item)
        scenes_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Scenes", None, "")
        scenes_item.setSubmenu_(scenes_sub)
        menu.addItem_(scenes_item)
    else:
        no_scenes = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Scenes (none loaded)", None, "")
        no_scenes.setEnabled_(False)
        menu.addItem_(no_scenes)
    menu.addItem_(NSMenuItem.separatorItem())

    # --- Set All Color ---
    color_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Set All Color...", "setAllColor:", "")
    color_item.setTarget_(self)
    menu.addItem_(color_item)

    # --- Set All Brightness ---
    bright_sub = NSMenu.alloc().init()
    for level in [10, 25, 50, 75, 100]:
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(f"{level}%", "setAllBrightness:", "")
        item.setTarget_(self)
        item.setTag_(level)
        bright_sub.addItem_(item)
    bright_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Set All Brightness", None, "")
    bright_item.setSubmenu_(bright_sub)
    menu.addItem_(bright_item)
    menu.addItem_(NSMenuItem.separatorItem())

    # --- Individual Devices ---
    controllable = [d for d in self.devices if d["name"] != BUSTED_NAME]
    for dev in controllable:
        dev_sub = NSMenu.alloc().init()

        # On/Off
        dev_on = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Turn On", "deviceOn:", "")
        dev_on.setTarget_(self)
        dev_on.setRepresentedObject_(dev)
        dev_sub.addItem_(dev_on)
        dev_off = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Turn Off", "deviceOff:", "")
        dev_off.setTarget_(self)
        dev_off.setRepresentedObject_(dev)
        dev_sub.addItem_(dev_off)
        dev_sub.addItem_(NSMenuItem.separatorItem())

        # Brightness
        for level in [10, 25, 50, 75, 100]:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(f"Brightness {level}%", "deviceBrightness:", "")
            item.setTarget_(self)
            item.setRepresentedObject_({"device": dev, "brightness": level})
            dev_sub.addItem_(item)
        dev_sub.addItem_(NSMenuItem.separatorItem())

        # Color
        color = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Set Color...", "deviceColor:", "")
        color.setTarget_(self)
        color.setRepresentedObject_(dev)
        dev_sub.addItem_(color)

        dev_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(dev["name"], None, "")
        dev_item.setSubmenu_(dev_sub)
        menu.addItem_(dev_item)

    menu.addItem_(NSMenuItem.separatorItem())

    # --- Busted ---
    busted_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Busted (skipped)", None, "")
    busted_item.setEnabled_(False)
    menu.addItem_(busted_item)
    menu.addItem_(NSMenuItem.separatorItem())

    # --- Refresh / Quit ---
    refresh = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Refresh Devices", "refreshDevices:", "")
    refresh.setTarget_(self)
    menu.addItem_(refresh)
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "terminate:", "q")
    menu.addItem_(quit_item)

    self.status_item.setMenu_(menu)
```

- [ ] **Step 2: Test the menu renders correctly**

```bash
cd /Users/ryan/Development/ActiveApps/govee-sunset-lights
python3 menubar/govee-lights.py &
# Click the lightbulb icon
# Verify: All sections visible — All Lights On/Off, Music Mode submenu, Scenes submenu with 10 scenes,
#         Set All Color, Set All Brightness, individual devices, Busted greyed out, Quit
# Kill: kill %1
```

- [ ] **Step 3: Commit**

```bash
git add menubar/govee-lights.py
git commit -m "feat: build full dropdown menu structure with scenes and device submenus"
```

---

### Task 3: Implement All Action Handlers

**Files:**
- Modify: `menubar/govee-lights.py`

Wire up every menu action. All API calls happen on background threads.

- [ ] **Step 1: Add the Govee API control helper**

```python
@objc.python_method
def _send_control(self, sku, device_id, capability):
    """Send a single control command to the Govee API."""
    try:
        res = requests.post(
            f"{GOVEE_API}/device/control",
            headers=api_headers(),
            json={
                "requestId": f"menu-{id(capability)}-{device_id}",
                "payload": {
                    "sku": sku,
                    "device": device_id,
                    "capability": capability,
                },
            },
            timeout=10,
        )
        res.raise_for_status()
        return True
    except Exception as e:
        print(f"Control error ({sku} {device_id}): {e}")
        return False

@objc.python_method
def _controllable_devices(self):
    """Return all devices except Busted."""
    return [d for d in self.devices if d["name"] != BUSTED_NAME]
```

- [ ] **Step 2: Implement All Lights On/Off**

```python
def allLightsOn_(self, sender):
    threading.Thread(target=self._all_lights, args=(True,), daemon=True).start()

def allLightsOff_(self, sender):
    threading.Thread(target=self._all_lights, args=(False,), daemon=True).start()

@objc.python_method
def _all_lights(self, on):
    for d in self._controllable_devices():
        self._send_control(d["sku"], d["device"], {
            "type": "devices.capabilities.on_off",
            "instance": "powerSwitch",
            "value": 1 if on else 0,
        })
```

- [ ] **Step 3: Implement Music Mode On/Off**

Music mode ON powers on all devices that have `dreamViewToggle` capability. Music mode OFF powers them off. The DreamView group resumes automatically when devices are powered on.

```python
# Devices in the DreamView music group (all with dreamViewToggle except Busted)
DREAMVIEW_CAPABILITY = "devices.capabilities.toggle:dreamViewToggle"

def musicOn_(self, sender):
    threading.Thread(target=self._music_power, args=(True,), daemon=True).start()

def musicOff_(self, sender):
    threading.Thread(target=self._music_power, args=(False,), daemon=True).start()

@objc.python_method
def _music_power(self, on):
    for d in self._controllable_devices():
        if DREAMVIEW_CAPABILITY in d["capabilities"]:
            self._send_control(d["sku"], d["device"], {
                "type": "devices.capabilities.on_off",
                "instance": "powerSwitch",
                "value": 1 if on else 0,
            })
```

- [ ] **Step 4: Implement Scene Application**

```python
def applyScene_(self, sender):
    scene_name = sender.representedObject()
    threading.Thread(target=self._apply_scene, args=(scene_name,), daemon=True).start()

@objc.python_method
def _apply_scene(self, scene_name):
    scene_data = self.scene_map.get(scene_name)
    if not scene_data:
        return
    for d in self._controllable_devices():
        sku_scene = scene_data.get(d["sku"])
        if not sku_scene:
            continue
        # Turn on first
        self._send_control(d["sku"], d["device"], {
            "type": "devices.capabilities.on_off",
            "instance": "powerSwitch",
            "value": 1,
        })
        # Apply scene
        self._send_control(d["sku"], d["device"], {
            "type": "devices.capabilities.dynamic_scene",
            "instance": "lightScene",
            "value": sku_scene,
        })
```

- [ ] **Step 5: Implement Set All Color**

Uses macOS NSColorPanel. The color picker runs on the main thread; the API call goes to background.

```python
def setAllColor_(self, sender):
    self._color_target = "all"
    panel = NSColorPanel.sharedColorPanel()
    panel.setTarget_(self)
    panel.setAction_("colorPicked:")
    panel.makeKeyAndOrderFront_(None)
    # Bring our app to front so the panel is interactive
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

def deviceColor_(self, sender):
    self._color_target = sender.representedObject()
    panel = NSColorPanel.sharedColorPanel()
    panel.setTarget_(self)
    panel.setAction_("colorPicked:")
    panel.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

def colorPicked_(self, sender):
    color = sender.color().colorUsingColorSpaceName_("NSCalibratedRGBColorSpace")
    r = int(color.redComponent() * 255)
    g = int(color.greenComponent() * 255)
    b = int(color.blueComponent() * 255)
    color_int = (r << 16) | (g << 8) | b
    target = self._color_target
    threading.Thread(target=self._apply_color, args=(target, color_int), daemon=True).start()

@objc.python_method
def _apply_color(self, target, color_int):
    if target == "all":
        devices = self._controllable_devices()
    else:
        devices = [target]
    for d in devices:
        # Only set color if device supports it
        if "devices.capabilities.color_setting:colorRgb" in d["capabilities"]:
            self._send_control(d["sku"], d["device"], {
                "type": "devices.capabilities.color_setting",
                "instance": "colorRgb",
                "value": color_int,
            })
```

- [ ] **Step 6: Implement Set All Brightness and Device Brightness**

```python
def setAllBrightness_(self, sender):
    level = sender.tag()
    threading.Thread(target=self._set_brightness_all, args=(level,), daemon=True).start()

@objc.python_method
def _set_brightness_all(self, level):
    for d in self._controllable_devices():
        if "devices.capabilities.range:brightness" in d["capabilities"]:
            self._send_control(d["sku"], d["device"], {
                "type": "devices.capabilities.range",
                "instance": "brightness",
                "value": level,
            })

def deviceBrightness_(self, sender):
    obj = sender.representedObject()
    dev = obj["device"]
    level = obj["brightness"]
    threading.Thread(
        target=self._send_control,
        args=(dev["sku"], dev["device"], {
            "type": "devices.capabilities.range",
            "instance": "brightness",
            "value": level,
        }),
        daemon=True,
    ).start()
```

- [ ] **Step 7: Implement Individual Device On/Off**

```python
def deviceOn_(self, sender):
    dev = sender.representedObject()
    threading.Thread(
        target=self._send_control,
        args=(dev["sku"], dev["device"], {
            "type": "devices.capabilities.on_off",
            "instance": "powerSwitch",
            "value": 1,
        }),
        daemon=True,
    ).start()

def deviceOff_(self, sender):
    dev = sender.representedObject()
    threading.Thread(
        target=self._send_control,
        args=(dev["sku"], dev["device"], {
            "type": "devices.capabilities.on_off",
            "instance": "powerSwitch",
            "value": 0,
        }),
        daemon=True,
    ).start()
```

- [ ] **Step 8: Implement Refresh Devices**

```python
def refreshDevices_(self, sender):
    threading.Thread(target=self._init_data, daemon=True).start()
```

- [ ] **Step 9: Test all actions work**

```bash
cd /Users/ryan/Development/ActiveApps/govee-sunset-lights
python3 menubar/govee-lights.py &
# Test each action:
# 1. All Lights On — all lights turn on
# 2. All Lights Off — all lights turn off
# 3. Music Mode > ON — DreamView devices power on, resume music sync
# 4. Scenes > Aurora — all lights switch to Aurora scene
# 5. Set All Color — color picker opens, pick red, lights change
# 6. Set All Brightness > 50% — lights dim to 50%
# 7. Left Corner Light > Turn Off — only that light turns off
# 8. Left Corner Light > Brightness 100% — back to full
# 9. Refresh Devices — menu rebuilds
# Kill: kill %1
```

- [ ] **Step 10: Commit**

```bash
git add menubar/govee-lights.py
git commit -m "feat: wire up all menu actions — scenes, color, brightness, music mode, individual control"
```

---

### Task 4: Assemble Final File, Launch Agent, and Polish

**Files:**
- Modify: `menubar/govee-lights.py` — assemble all pieces into final working file
- Create: `menubar/com.ryan.govee-lights.plist` — launchd plist for auto-start

- [ ] **Step 1: Assemble the complete `govee-lights.py`**

Combine all code from Tasks 1-3 into a single coherent file. The complete file structure is:

1. Imports and single-instance guard
2. Constants (API URL, API key, Busted name, icon path, DreamView capability string)
3. `api_headers()` helper
4. `GoveeLightsApp` class with all methods:
   - `init` / `setup_statusbar` / `_init_data` / `buildMenu_`
   - `_fetch_devices` / `_fetch_all_scenes`
   - `_build_menu`
   - `_send_control` / `_controllable_devices`
   - `allLightsOn_` / `allLightsOff_` / `_all_lights`
   - `musicOn_` / `musicOff_` / `_music_power`
   - `applyScene_` / `_apply_scene`
   - `setAllColor_` / `deviceColor_` / `colorPicked_` / `_apply_color`
   - `setAllBrightness_` / `_set_brightness_all`
   - `deviceBrightness_`
   - `deviceOn_` / `deviceOff_`
   - `refreshDevices_`
5. `if __name__ == "__main__"` block

Verify the file runs and all menu items work end-to-end.

- [ ] **Step 2: Create a launchd plist for auto-start**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ryan.govee-lights</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/ryan/Development/ActiveApps/govee-sunset-lights/menubar/govee-lights.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/govee-lights.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/govee-lights.log</string>
</dict>
</plist>
```

Save to `menubar/com.ryan.govee-lights.plist`.

- [ ] **Step 3: Install the launch agent**

```bash
cp /Users/ryan/Development/ActiveApps/govee-sunset-lights/menubar/com.ryan.govee-lights.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ryan.govee-lights.plist
```

Verify it starts automatically and the icon appears.

- [ ] **Step 4: Final end-to-end test**

Run through each feature:
1. Icon visible in menu bar (colorful lightbulb)
2. All Lights On/Off works
3. Music Mode ON/OFF works (DreamView resumes)
4. Each of the 10 universal scenes applies to all lights
5. Color picker works for all + individual
6. Brightness works for all + individual
7. Individual device on/off works
8. Busted is greyed out and untouchable
9. Refresh rebuilds the menu
10. Quit exits cleanly

- [ ] **Step 5: Commit**

```bash
git add menubar/
git commit -m "feat: complete govee lights menu bar app with launch agent"
```

---

### Task 5: Update CLAUDE.md

**Files:**
- Modify: `/Users/ryan/Development/ActiveApps/govee-sunset-lights/CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md with menu bar app info**

Add a section about the menu bar app:

```markdown
## Menu Bar App

macOS menu bar controller for all Govee lights. Python + pyobjc.

### Run
```bash
python3 menubar/govee-lights.py
```

### Auto-start
LaunchAgent: `~/Library/LaunchAgents/com.ryan.govee-lights.plist`
```bash
launchctl load ~/Library/LaunchAgents/com.ryan.govee-lights.plist   # enable
launchctl unload ~/Library/LaunchAgents/com.ryan.govee-lights.plist # disable
```

### Features
- All lights on/off (excludes "Busted" device)
- Music Mode (DreamView) on/off — power toggles, preserves custom DreamView config
- 10 universal scenes (Aurora, Forest, Firefly, Sunrise, Sunset, Sunset Glow, Christmas, Christmas Bell, Halloween, Valentine's Day)
- Set all color (macOS color picker)
- Set all brightness (10/25/50/75/100%)
- Individual device control (on/off, brightness, color)
- "Busted" lamp always excluded from group operations

### Key file
- `menubar/govee-lights.py` — single-file app
- `menubar/icon.png` — menu bar icon
- `menubar/com.ryan.govee-lights.plist` — launch agent
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add menu bar app section to CLAUDE.md"
```
