#!/usr/bin/env python3
"""Govee Lights — macOS menu bar controller for Govee smart lights."""

import sys
import os
import fcntl
import threading
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
    NSApplication,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSImage,
    NSColorPanel,
    NSObject,
)
from Foundation import NSObject, NSTimer
from PyObjCTools import AppHelper

GOVEE_API = "https://openapi.api.govee.com/router/api/v1"
API_KEY = "00b0d8f5-c2cb-4b42-9522-bbcf94492b86"
BUSTED_NAME = "Busted"
ICON_PATH = Path(__file__).parent / "icon.png"
DREAMVIEW_CAP = "devices.capabilities.toggle:dreamViewToggle"
COLOR_CAP = "devices.capabilities.color_setting:colorRgb"
BRIGHTNESS_CAP = "devices.capabilities.range:brightness"


def api_headers():
    return {"Content-Type": "application/json", "Govee-API-Key": API_KEY}


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

    @objc.python_method
    def setup_statusbar(self):
        self.status_bar = NSStatusBar.systemStatusBar()
        self.status_item = self.status_bar.statusItemWithLength_(NSVariableStatusItemLength)
        button = self.status_item.button()
        if ICON_PATH.exists():
            img = NSImage.alloc().initWithContentsOfFile_(str(ICON_PATH))
            img.setSize_((22, 22))
            img.setTemplate_(False)
            button.setImage_(img)
        else:
            button.setTitle_("💡")
        # Placeholder menu
        menu = NSMenu.alloc().init()
        loading = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Loading devices...", None, ""
        )
        loading.setEnabled_(False)
        menu.addItem_(loading)
        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", "q"
        )
        menu.addItem_(quit_item)
        self.status_item.setMenu_(menu)

    # ── Data fetching ──────────────────────────────────────────────

    @objc.python_method
    def _init_data(self):
        try:
            self._fetch_devices()
            self._fetch_all_scenes()
        except Exception as e:
            print(f"Init error: {e}")
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "buildMenu:", None, False
        )

    def buildMenu_(self, _):
        self._build_menu()

    @objc.python_method
    def _fetch_devices(self):
        res = requests.get(
            f"{GOVEE_API}/user/devices", headers=api_headers(), timeout=10
        )
        res.raise_for_status()
        data = res.json()
        self.devices = [
            {
                "name": d["deviceName"],
                "sku": d["sku"],
                "device": d["device"],
                "capabilities": [
                    c["type"] + ":" + c["instance"]
                    for c in d.get("capabilities", [])
                ],
            }
            for d in data.get("data", [])
        ]

    @objc.python_method
    def _fetch_all_scenes(self):
        sku_scenes = {}
        seen_skus = {}
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
                    json={
                        "requestId": f"scenes-{sku}",
                        "payload": {"sku": sku, "device": device_id},
                    },
                    timeout=10,
                )
                res.raise_for_status()
                data = res.json()
                caps = data.get("payload", {}).get("capabilities", [])
                scenes = {}
                for cap in caps:
                    if cap.get("instance") == "lightScene":
                        for opt in cap.get("parameters", {}).get("options", []):
                            scenes[opt["name"]] = {
                                "id": opt["value"]["id"],
                                "paramId": opt["value"].get("paramId"),
                            }
                sku_scenes[sku] = scenes
            except Exception as e:
                print(f"Failed to fetch scenes for {sku}: {e}")

        if sku_scenes:
            common_names = set.intersection(
                *[set(s.keys()) for s in sku_scenes.values()]
            )
        else:
            common_names = set()

        self.scene_map = {}
        for name in sorted(common_names):
            self.scene_map[name] = {}
            for sku, scenes in sku_scenes.items():
                self.scene_map[name][sku] = scenes[name]

    # ── Menu building ──────────────────────────────────────────────

    @objc.python_method
    def _build_menu(self):
        menu = NSMenu.alloc().init()

        # All Lights On/Off
        on_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "All Lights On", "allLightsOn:", ""
        )
        on_item.setTarget_(self)
        menu.addItem_(on_item)
        off_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "All Lights Off", "allLightsOff:", ""
        )
        off_item.setTarget_(self)
        menu.addItem_(off_item)
        menu.addItem_(NSMenuItem.separatorItem())

        # Music Mode
        music_sub = NSMenu.alloc().init()
        music_on = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "ON", "musicOn:", ""
        )
        music_on.setTarget_(self)
        music_sub.addItem_(music_on)
        music_off = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "OFF", "musicOff:", ""
        )
        music_off.setTarget_(self)
        music_sub.addItem_(music_off)
        music_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Music Mode (DreamView)", None, ""
        )
        music_item.setSubmenu_(music_sub)
        menu.addItem_(music_item)
        menu.addItem_(NSMenuItem.separatorItem())

        # Scenes
        if self.scene_map:
            scenes_sub = NSMenu.alloc().init()
            for scene_name in sorted(self.scene_map.keys()):
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    scene_name, "applyScene:", ""
                )
                item.setTarget_(self)
                item.setRepresentedObject_(scene_name)
                scenes_sub.addItem_(item)
            scenes_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Scenes", None, ""
            )
            scenes_item.setSubmenu_(scenes_sub)
            menu.addItem_(scenes_item)
        else:
            no_scenes = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Scenes (none loaded)", None, ""
            )
            no_scenes.setEnabled_(False)
            menu.addItem_(no_scenes)
        menu.addItem_(NSMenuItem.separatorItem())

        # Set All Color
        color_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Set All Color...", "setAllColor:", ""
        )
        color_item.setTarget_(self)
        menu.addItem_(color_item)

        # Set All Brightness
        bright_sub = NSMenu.alloc().init()
        for level in [10, 25, 50, 75, 100]:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                f"{level}%", "setAllBrightness:", ""
            )
            item.setTarget_(self)
            item.setTag_(level)
            bright_sub.addItem_(item)
        bright_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Set All Brightness", None, ""
        )
        bright_item.setSubmenu_(bright_sub)
        menu.addItem_(bright_item)
        menu.addItem_(NSMenuItem.separatorItem())

        # Individual Devices
        controllable = [d for d in self.devices if d["name"] != BUSTED_NAME]
        for dev in controllable:
            dev_sub = NSMenu.alloc().init()

            dev_on = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Turn On", "deviceOn:", ""
            )
            dev_on.setTarget_(self)
            dev_on.setRepresentedObject_(dev)
            dev_sub.addItem_(dev_on)

            dev_off = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Turn Off", "deviceOff:", ""
            )
            dev_off.setTarget_(self)
            dev_off.setRepresentedObject_(dev)
            dev_sub.addItem_(dev_off)

            dev_sub.addItem_(NSMenuItem.separatorItem())

            for level in [10, 25, 50, 75, 100]:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    f"Brightness {level}%", "deviceBrightness:", ""
                )
                item.setTarget_(self)
                item.setRepresentedObject_({"device": dev, "brightness": level})
                dev_sub.addItem_(item)

            dev_sub.addItem_(NSMenuItem.separatorItem())

            color = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Set Color...", "deviceColor:", ""
            )
            color.setTarget_(self)
            color.setRepresentedObject_(dev)
            dev_sub.addItem_(color)

            dev_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                dev["name"], None, ""
            )
            dev_item.setSubmenu_(dev_sub)
            menu.addItem_(dev_item)

        menu.addItem_(NSMenuItem.separatorItem())

        # Busted
        busted_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Busted (skipped)", None, ""
        )
        busted_item.setEnabled_(False)
        menu.addItem_(busted_item)
        menu.addItem_(NSMenuItem.separatorItem())

        # Refresh / Quit
        refresh = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Refresh Devices", "refreshDevices:", ""
        )
        refresh.setTarget_(self)
        menu.addItem_(refresh)
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", "q"
        )
        menu.addItem_(quit_item)

        self.status_item.setMenu_(menu)

    # ── API helpers ────────────────────────────────────────────────

    @objc.python_method
    def _send_control(self, sku, device_id, capability):
        try:
            res = requests.post(
                f"{GOVEE_API}/device/control",
                headers=api_headers(),
                json={
                    "requestId": f"menu-{threading.current_thread().ident}-{device_id}",
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
        return [d for d in self.devices if d["name"] != BUSTED_NAME]

    # ── Actions: All Lights ────────────────────────────────────────

    def allLightsOn_(self, sender):
        threading.Thread(target=self._all_lights, args=(True,), daemon=True).start()

    def allLightsOff_(self, sender):
        threading.Thread(target=self._all_lights, args=(False,), daemon=True).start()

    @objc.python_method
    def _all_lights(self, on):
        for d in self._controllable_devices():
            self._send_control(
                d["sku"],
                d["device"],
                {
                    "type": "devices.capabilities.on_off",
                    "instance": "powerSwitch",
                    "value": 1 if on else 0,
                },
            )

    # ── Actions: Music Mode ────────────────────────────────────────

    def musicOn_(self, sender):
        threading.Thread(
            target=self._music_power, args=(True,), daemon=True
        ).start()

    def musicOff_(self, sender):
        threading.Thread(
            target=self._music_power, args=(False,), daemon=True
        ).start()

    @objc.python_method
    def _music_power(self, on):
        for d in self._controllable_devices():
            if DREAMVIEW_CAP in d["capabilities"]:
                self._send_control(
                    d["sku"],
                    d["device"],
                    {
                        "type": "devices.capabilities.on_off",
                        "instance": "powerSwitch",
                        "value": 1 if on else 0,
                    },
                )

    # ── Actions: Scenes ────────────────────────────────────────────

    def applyScene_(self, sender):
        scene_name = sender.representedObject()
        threading.Thread(
            target=self._apply_scene, args=(scene_name,), daemon=True
        ).start()

    @objc.python_method
    def _apply_scene(self, scene_name):
        scene_data = self.scene_map.get(scene_name)
        if not scene_data:
            return
        for d in self._controllable_devices():
            sku_scene = scene_data.get(d["sku"])
            if not sku_scene:
                continue
            self._send_control(
                d["sku"],
                d["device"],
                {
                    "type": "devices.capabilities.on_off",
                    "instance": "powerSwitch",
                    "value": 1,
                },
            )
            self._send_control(
                d["sku"],
                d["device"],
                {
                    "type": "devices.capabilities.dynamic_scene",
                    "instance": "lightScene",
                    "value": sku_scene,
                },
            )

    # ── Actions: Color ─────────────────────────────────────────────

    def setAllColor_(self, sender):
        self._color_target = "all"
        panel = NSColorPanel.sharedColorPanel()
        panel.setTarget_(self)
        panel.setAction_("colorPicked:")
        panel.makeKeyAndOrderFront_(None)
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
        if color is None:
            return
        r = int(color.redComponent() * 255)
        g = int(color.greenComponent() * 255)
        b = int(color.blueComponent() * 255)
        color_int = (r << 16) | (g << 8) | b
        target = self._color_target
        threading.Thread(
            target=self._apply_color, args=(target, color_int), daemon=True
        ).start()

    @objc.python_method
    def _apply_color(self, target, color_int):
        if target == "all":
            devices = self._controllable_devices()
        else:
            devices = [target]
        for d in devices:
            if COLOR_CAP in d["capabilities"]:
                self._send_control(
                    d["sku"],
                    d["device"],
                    {
                        "type": "devices.capabilities.color_setting",
                        "instance": "colorRgb",
                        "value": color_int,
                    },
                )

    # ── Actions: Brightness ────────────────────────────────────────

    def setAllBrightness_(self, sender):
        level = sender.tag()
        threading.Thread(
            target=self._set_brightness_all, args=(level,), daemon=True
        ).start()

    @objc.python_method
    def _set_brightness_all(self, level):
        for d in self._controllable_devices():
            if BRIGHTNESS_CAP in d["capabilities"]:
                self._send_control(
                    d["sku"],
                    d["device"],
                    {
                        "type": "devices.capabilities.range",
                        "instance": "brightness",
                        "value": level,
                    },
                )

    def deviceBrightness_(self, sender):
        obj = sender.representedObject()
        dev = obj["device"]
        level = obj["brightness"]
        threading.Thread(
            target=self._send_control,
            args=(
                dev["sku"],
                dev["device"],
                {
                    "type": "devices.capabilities.range",
                    "instance": "brightness",
                    "value": level,
                },
            ),
            daemon=True,
        ).start()

    # ── Actions: Individual Device On/Off ──────────────────────────

    def deviceOn_(self, sender):
        dev = sender.representedObject()
        threading.Thread(
            target=self._send_control,
            args=(
                dev["sku"],
                dev["device"],
                {
                    "type": "devices.capabilities.on_off",
                    "instance": "powerSwitch",
                    "value": 1,
                },
            ),
            daemon=True,
        ).start()

    def deviceOff_(self, sender):
        dev = sender.representedObject()
        threading.Thread(
            target=self._send_control,
            args=(
                dev["sku"],
                dev["device"],
                {
                    "type": "devices.capabilities.on_off",
                    "instance": "powerSwitch",
                    "value": 0,
                },
            ),
            daemon=True,
        ).start()

    # ── Actions: Refresh ───────────────────────────────────────────

    def refreshDevices_(self, sender):
        threading.Thread(target=self._init_data, daemon=True).start()


if __name__ == "__main__":
    app = NSApplication.sharedApplication()
    controller = GoveeLightsApp.alloc().init()
    AppHelper.runEventLoop()
