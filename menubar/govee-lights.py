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
# The lamp with broken color rendering — white-only, excluded from scenes/colors.
# Formerly named "Busted"; re-paired as "White Lamp" (colors show wrong, white LEDs fine).
# Accept either name: it re-joined the account as "Busted" on 2026-10-03.
BUSTED_NAMES = {"White Lamp", "Busted"}
WHITE_LAMP_KELVIN = 2200  # dedicated white LEDs, the "white that works"
ICON_PATH = Path(__file__).parent / "icon.png"
DREAMVIEW_CAP = "devices.capabilities.toggle:dreamViewToggle"
COLOR_CAP = "devices.capabilities.color_setting:colorRgb"
COLOR_TEMP_CAP = "devices.capabilities.color_setting:colorTemperatureK"
BRIGHTNESS_CAP = "devices.capabilities.range:brightness"

# "Chill" DIY scene on the H6095: nebula only, green laser off (verified 2026-07-31)
PROJECTOR_SKU = "H6095"
PROJECTOR_NEBULA_DIY_ID = 22555274

# H1771 wall lights (added 2026-10-12): controlled together as one group
WALL_LIGHT_NAMES = ["Wall Light", "Wall Light 2"]

# H60B2 tree floor lamps (second added 2026-10-24): same SKU, so a scene
# subset only widens when both are left out
TREE_LAMP_NAMES = ["Tree Floor Lamp", "Tree Floor Lamp 2"]

# "Scenes (minus X)" menus: label -> device names left out of the scene
EXCLUDE_GROUPS = {
    "Table Lamp": ["Table Lamp"],
    "Star Light Projector": ["Star Light Projector"],
    "Wall Lights": WALL_LIGHT_NAMES,
    "Tree Floor Lamps": TREE_LAMP_NAMES,
}

# When a model has duplicate scene names, which id gets the plain name
# (picked by eye 2026-10-12). Unlisted duplicates default to the first one,
# which is right for H1771 (its second Halloween is pink/blue).
PREFERRED_SCENE_IDS = {
    "H607C": {"Halloween": 9659},
}

PRESET_COLORS = [
    ("Red", 255, 0, 0),
    ("Orange", 255, 140, 0),
    ("Warm Orange", 255, 220, 180),
    ("Yellow", 255, 255, 0),
    ("Green", 0, 255, 0),
    ("Cyan", 0, 255, 255),
    ("Blue", 0, 0, 255),
    ("Purple", 139, 0, 255),
    ("Pink", 255, 105, 180),
    ("Warm White", 255, 244, 229),
    ("Pure White", 255, 255, 255),
]

# Whites via dedicated white LEDs (much brighter than RGB-mixed white)
PRESET_COLOR_TEMPS = [
    ("BRIGHTEST WHITE", 2200),
]


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
            if d["name"] in BUSTED_NAMES:
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
                            # Some models list two scenes with the same name (H1771 and
                            # H607C both have two "Halloween"s). Keep the first under the
                            # plain name and suffix later ones "(2)" instead of replacing
                            # it; PREFERRED_SCENE_IDS overrides per model.
                            name = opt["name"]
                            n = 2
                            while name in scenes:
                                name = f"{opt['name']} ({n})"
                                n += 1
                            scenes[name] = {
                                "id": opt["value"]["id"],
                                "paramId": opt["value"].get("paramId"),
                            }
                # Swap a preferred duplicate into the plain name
                for base, pref_id in PREFERRED_SCENE_IDS.get(sku, {}).items():
                    for name, val in list(scenes.items()):
                        if val["id"] == pref_id and name != base and base in scenes:
                            scenes[name], scenes[base] = scenes[base], val
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

        # Store per-SKU scene data for individual device menus
        self.sku_scenes = sku_scenes
        self._build_subset_scenes()

    @objc.python_method
    def _build_subset_scenes(self):
        """Build scene maps for subsets that exclude one device type."""
        # Map device names to SKUs
        self.device_sku_map = {}
        for d in self.devices:
            if d["name"] not in BUSTED_NAMES:
                self.device_sku_map[d["name"]] = d["sku"]

        # For each excludable device, find scenes common to all OTHER SKUs
        self.subset_scenes = {}  # {exclude_name: {scene_name: {sku: {id, paramId}}}}
        for exclude_name, excluded in EXCLUDE_GROUPS.items():
            if not any(n in self.device_sku_map for n in excluded):
                continue
            # SKUs remaining after exclusion (might still have the same SKU from other devices)
            remaining_skus = set()
            for d in self.devices:
                if d["name"] not in BUSTED_NAMES and d["name"] not in excluded:
                    remaining_skus.add(d["sku"])
            # Find scenes common to remaining SKUs
            remaining_scene_sets = [
                set(self.sku_scenes[sku].keys())
                for sku in remaining_skus
                if sku in self.sku_scenes
            ]
            if remaining_scene_sets:
                subset_common = set.intersection(*remaining_scene_sets)
            else:
                subset_common = set()
            # Only include scenes NOT already in the universal set (extras only)
            extras = subset_common - set(self.scene_map.keys())
            scene_data = {}
            for name in sorted(extras):
                scene_data[name] = {}
                for sku in remaining_skus:
                    if sku in self.sku_scenes and name in self.sku_scenes[sku]:
                        scene_data[name][sku] = self.sku_scenes[sku][name]
            self.subset_scenes[exclude_name] = scene_data

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

        # Star projector nebula-only mode (green laser off)
        nebula_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Projector: Nebula (No Lasers)", "projectorNebula:", ""
        )
        nebula_item.setTarget_(self)
        menu.addItem_(nebula_item)
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
        # Subset scenes (minus one device)
        for exclude_name, extra_scenes in self.subset_scenes.items():
            if not extra_scenes:
                continue
            sub = NSMenu.alloc().init()
            for scene_name in sorted(extra_scenes.keys()):
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    scene_name, "applySubsetScene:", ""
                )
                item.setTarget_(self)
                item.setRepresentedObject_(
                    {"scene": scene_name, "exclude": exclude_name}
                )
                sub.addItem_(item)
            label = f"Scenes (minus {exclude_name})"
            sub_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                label, None, ""
            )
            sub_item.setSubmenu_(sub)
            menu.addItem_(sub_item)

        menu.addItem_(NSMenuItem.separatorItem())

        # Set All Color
        color_sub = NSMenu.alloc().init()
        for name, r, g, b in PRESET_COLORS:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                name, "setAllPresetColor:", ""
            )
            item.setTarget_(self)
            item.setRepresentedObject_((r << 16) | (g << 8) | b)
            color_sub.addItem_(item)
        color_sub.addItem_(NSMenuItem.separatorItem())
        for name, kelvin in PRESET_COLOR_TEMPS:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                name, "setAllPresetColorTemp:", ""
            )
            item.setTarget_(self)
            item.setRepresentedObject_(kelvin)
            color_sub.addItem_(item)
        color_sub.addItem_(NSMenuItem.separatorItem())
        picker_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Color Picker...", "setAllColor:", ""
        )
        picker_item.setTarget_(self)
        color_sub.addItem_(picker_item)
        color_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Set All Color", None, ""
        )
        color_item.setSubmenu_(color_sub)
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

        # Wall Lights (both H1771s at once)
        wall_devs = [d for d in self.devices if d["name"] in WALL_LIGHT_NAMES]
        if wall_devs:
            menu.addItem_(self._build_wall_menu(wall_devs))
            menu.addItem_(NSMenuItem.separatorItem())

        # Individual Devices
        controllable = [d for d in self.devices if d["name"] not in BUSTED_NAMES]
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

            for name, r, g, b in PRESET_COLORS:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    name, "devicePresetColor:", ""
                )
                item.setTarget_(self)
                item.setRepresentedObject_(
                    {"device": dev, "color": (r << 16) | (g << 8) | b}
                )
                dev_sub.addItem_(item)
            dev_sub.addItem_(NSMenuItem.separatorItem())
            for name, kelvin in PRESET_COLOR_TEMPS:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    name, "devicePresetColorTemp:", ""
                )
                item.setTarget_(self)
                item.setRepresentedObject_({"device": dev, "kelvin": kelvin})
                dev_sub.addItem_(item)
            dev_sub.addItem_(NSMenuItem.separatorItem())

            color = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Color Picker...", "deviceColor:", ""
            )
            color.setTarget_(self)
            color.setRepresentedObject_(dev)
            dev_sub.addItem_(color)

            # Per-device scenes
            dev_scenes = self.sku_scenes.get(dev["sku"], {})
            if dev_scenes:
                dev_sub.addItem_(NSMenuItem.separatorItem())
                scenes_sub = NSMenu.alloc().init()
                for scene_name in sorted(dev_scenes.keys()):
                    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        scene_name, "deviceScene:", ""
                    )
                    item.setTarget_(self)
                    item.setRepresentedObject_(
                        {"device": dev, "scene": dev_scenes[scene_name]}
                    )
                    scenes_sub.addItem_(item)
                scenes_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    "Scenes", None, ""
                )
                scenes_item.setSubmenu_(scenes_sub)
                dev_sub.addItem_(scenes_item)

            dev_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                dev["name"], None, ""
            )
            dev_item.setSubmenu_(dev_sub)
            menu.addItem_(dev_item)

        menu.addItem_(NSMenuItem.separatorItem())

        # White Lamp — broken color rendering, white-only, excluded from scenes/colors
        white_lamp = next(
            (d for d in self.devices if d["name"] in BUSTED_NAMES), None
        )
        if white_lamp:
            wl_sub = NSMenu.alloc().init()
            wl_on = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "On — White", "whiteLampOn:", ""
            )
            wl_on.setTarget_(self)
            wl_sub.addItem_(wl_on)
            wl_off = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Off", "whiteLampOff:", ""
            )
            wl_off.setTarget_(self)
            wl_sub.addItem_(wl_off)
            wl_sub.addItem_(NSMenuItem.separatorItem())
            for level in [10, 25, 50, 75, 100]:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    f"Brightness {level}%", "whiteLampBrightness:", ""
                )
                item.setTarget_(self)
                item.setTag_(level)
                wl_sub.addItem_(item)
            wl_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "White Lamp (white-only, colors busted)", None, ""
            )
            wl_item.setSubmenu_(wl_sub)
            menu.addItem_(wl_item)
        else:
            wl_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "White Lamp (not paired — add in Govee app)", None, ""
            )
            wl_item.setEnabled_(False)
            menu.addItem_(wl_item)
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

    @objc.python_method
    def _build_wall_menu(self, wall_devs):
        sub = NSMenu.alloc().init()

        def add(title, caps, menu=sub):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, "groupControl:", ""
            )
            item.setTarget_(self)
            item.setRepresentedObject_({"devices": wall_devs, "caps": caps})
            menu.addItem_(item)

        def cap(type_, instance, value):
            return {
                "type": f"devices.capabilities.{type_}",
                "instance": instance,
                "value": value,
            }

        power_on = cap("on_off", "powerSwitch", 1)
        add("Turn On", [power_on])
        add("Turn Off", [cap("on_off", "powerSwitch", 0)])
        sub.addItem_(NSMenuItem.separatorItem())
        add("Wall Wash On", [power_on, cap("toggle", "wallWashingLightToggle", 1)])
        add("Wall Wash Off", [cap("toggle", "wallWashingLightToggle", 0)])
        add("Night Light On", [power_on, cap("toggle", "nightlampToggle", 1)])
        add("Night Light Off", [cap("toggle", "nightlampToggle", 0)])
        sub.addItem_(NSMenuItem.separatorItem())
        for level in [10, 25, 50, 75, 100]:
            add(f"Brightness {level}%", [cap("range", "brightness", level)])
        sub.addItem_(NSMenuItem.separatorItem())
        for name, r, g, b in PRESET_COLORS:
            add(name, [power_on, cap("color_setting", "colorRgb", (r << 16) | (g << 8) | b)])
        for name, kelvin in PRESET_COLOR_TEMPS:
            add(name, [power_on, cap("color_setting", "colorTemperatureK", kelvin)])

        # Both lights are the same SKU, so one scene list covers both
        wall_scenes = self.sku_scenes.get(wall_devs[0]["sku"], {})
        if wall_scenes:
            sub.addItem_(NSMenuItem.separatorItem())
            scenes_sub = NSMenu.alloc().init()
            for scene_name in sorted(wall_scenes.keys()):
                add(
                    scene_name,
                    [power_on, cap("dynamic_scene", "lightScene", wall_scenes[scene_name])],
                    menu=scenes_sub,
                )
            scenes_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Scenes", None, ""
            )
            scenes_item.setSubmenu_(scenes_sub)
            sub.addItem_(scenes_item)

        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Wall Lights (both)", None, ""
        )
        item.setSubmenu_(sub)
        return item

    def groupControl_(self, sender):
        obj = sender.representedObject()
        threading.Thread(
            target=self._group_control,
            args=(list(obj["devices"]), list(obj["caps"])),
            daemon=True,
        ).start()

    @objc.python_method
    def _group_control(self, devices, caps):
        for c in caps:
            for d in devices:
                self._send_control(d["sku"], d["device"], dict(c))

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
        return [d for d in self.devices if d["name"] not in BUSTED_NAMES]

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

    # ── Actions: White Lamp (colors busted, white-only) ────────────

    def whiteLampOn_(self, sender):
        threading.Thread(target=self._white_lamp_on, daemon=True).start()

    def whiteLampOff_(self, sender):
        threading.Thread(target=self._white_lamp_power, args=(False,), daemon=True).start()

    def whiteLampBrightness_(self, sender):
        level = sender.tag()
        threading.Thread(
            target=self._white_lamp_brightness, args=(level,), daemon=True
        ).start()

    @objc.python_method
    def _white_lamp_device(self):
        return next((d for d in self.devices if d["name"] in BUSTED_NAMES), None)

    @objc.python_method
    def _white_lamp_power(self, on):
        d = self._white_lamp_device()
        if not d:
            return
        self._send_control(
            d["sku"],
            d["device"],
            {
                "type": "devices.capabilities.on_off",
                "instance": "powerSwitch",
                "value": 1 if on else 0,
            },
        )

    @objc.python_method
    def _white_lamp_on(self):
        d = self._white_lamp_device()
        if not d:
            return
        self._white_lamp_power(True)
        self._send_control(
            d["sku"],
            d["device"],
            {
                "type": "devices.capabilities.color_setting",
                "instance": "colorTemperatureK",
                "value": WHITE_LAMP_KELVIN,
            },
        )

    @objc.python_method
    def _white_lamp_brightness(self, level):
        d = self._white_lamp_device()
        if not d:
            return
        self._send_control(
            d["sku"],
            d["device"],
            {
                "type": "devices.capabilities.range",
                "instance": "brightness",
                "value": level,
            },
        )

    # ── Actions: Star Projector ────────────────────────────────────

    def projectorNebula_(self, sender):
        threading.Thread(target=self._projector_nebula, daemon=True).start()

    @objc.python_method
    def _projector_nebula(self):
        projector = next(
            (d for d in self._controllable_devices() if d["sku"] == PROJECTOR_SKU),
            None,
        )
        if not projector:
            print("Projector not found in device list")
            return
        self._send_control(
            projector["sku"],
            projector["device"],
            {
                "type": "devices.capabilities.on_off",
                "instance": "powerSwitch",
                "value": 1,
            },
        )
        self._send_control(
            projector["sku"],
            projector["device"],
            {
                "type": "devices.capabilities.dynamic_scene",
                "instance": "diyScene",
                "value": PROJECTOR_NEBULA_DIY_ID,
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

    def deviceScene_(self, sender):
        obj = sender.representedObject()
        dev = obj["device"]
        scene = obj["scene"]
        threading.Thread(
            target=self._apply_device_scene,
            args=(dev, scene),
            daemon=True,
        ).start()

    @objc.python_method
    def _apply_device_scene(self, dev, scene):
        self._send_control(
            dev["sku"],
            dev["device"],
            {
                "type": "devices.capabilities.on_off",
                "instance": "powerSwitch",
                "value": 1,
            },
        )
        self._send_control(
            dev["sku"],
            dev["device"],
            {
                "type": "devices.capabilities.dynamic_scene",
                "instance": "lightScene",
                "value": scene,
            },
        )

    def applySubsetScene_(self, sender):
        obj = sender.representedObject()
        scene_name = obj["scene"]
        exclude_name = obj["exclude"]
        threading.Thread(
            target=self._apply_subset_scene,
            args=(scene_name, exclude_name),
            daemon=True,
        ).start()

    @objc.python_method
    def _apply_subset_scene(self, scene_name, exclude_name):
        scene_data = self.subset_scenes.get(exclude_name, {}).get(scene_name)
        if not scene_data:
            return
        excluded = EXCLUDE_GROUPS.get(exclude_name, [exclude_name])
        for d in self._controllable_devices():
            if d["name"] in excluded:
                continue
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

    def setAllPresetColor_(self, sender):
        color_int = sender.representedObject()
        threading.Thread(
            target=self._apply_color, args=("all", color_int), daemon=True
        ).start()

    def devicePresetColor_(self, sender):
        obj = sender.representedObject()
        dev = obj["device"]
        color_int = obj["color"]
        threading.Thread(
            target=self._apply_color, args=(dev, color_int), daemon=True
        ).start()

    def setAllPresetColorTemp_(self, sender):
        kelvin = sender.representedObject()
        threading.Thread(
            target=self._apply_color_temp, args=("all", kelvin), daemon=True
        ).start()

    def devicePresetColorTemp_(self, sender):
        obj = sender.representedObject()
        threading.Thread(
            target=self._apply_color_temp, args=(obj["device"], obj["kelvin"]), daemon=True
        ).start()

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

    @objc.python_method
    def _apply_color_temp(self, target, kelvin):
        if target == "all":
            devices = self._controllable_devices()
        else:
            devices = [target]
        for d in devices:
            if COLOR_TEMP_CAP in d["capabilities"]:
                self._send_control(
                    d["sku"],
                    d["device"],
                    {
                        "type": "devices.capabilities.color_setting",
                        "instance": "colorTemperatureK",
                        "value": kelvin,
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
