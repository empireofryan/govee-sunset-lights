# Govee Lights Menu Bar Controller — Design Spec

## Overview

A macOS menu bar app to control Govee smart lights via dropdown. Python + pyobjc, matching the existing Claude usage monitor pattern. Colorful lightbulb icon (icons8 3D-fluency).

## Devices

| App Name | Govee Name | SKU | Device ID | Notes |
|----------|-----------|-----|-----------|-------|
| Left Corner Light | Left Corner Light | H607C | `27:65:DA:20:97:5B:C1:B2` | DreamView member |
| Right Corner Light | Right Corner Light | H607C | `26:AB:CB:24:89:C0:EB:03` | DreamView lead |
| Side Light | Side Light | H607C | `27:3A:CA:15:C2:E6:31:A8` | DreamView member |
| Uplighter Floor Lamp | Uplighter Floor Lamp | H60B0 | `1D:2D:DA:48:46:06:7F:52` | DreamView member |
| Star Light Projector | Star Light Projector | H6095 | `7D:60:C1:9A:6A:63:3B:DC` | DreamView member |
| Table Lamp | Table Lamp | H6022 | `1E:97:DB:48:43:86:5A:79` | DreamView member |
| Busted | Busted | H607C | TBD (fetch at runtime) | NEVER control — hardcoded exclusion |

Note: Device IDs above are from the worker code and may be stale. The app fetches the device list from the Govee API on launch and matches by `deviceName`. "Busted" is identified by name and excluded from all group operations.

## Menu Structure

```
[lightbulb icon]
├── All Lights On
├── All Lights Off
├── ──────────────
├── Music Mode (DreamView)
│   ├── ON  (power on 5 DreamView devices)
│   └── OFF (power off 5 DreamView devices)
├── ──────────────
├── Scenes
│   ├── Bright Evening
│   ├── White
│   ├── Orange
│   └── Blue
├── ──────────────
├── Set All Color...          (opens macOS color picker)
├── ──────────────
├── Left Corner Light         ▸
│   ├── Turn On / Turn Off
│   ├── Brightness...         (slider submenu)
│   └── Set Color...          (opens color picker)
├── Right Corner Light        ▸  (same submenu)
├── Side Light                ▸  (same submenu)
├── Uplighter Floor Lamp      ▸  (same submenu)
├── Star Light Projector      ▸  (same submenu)
├── Table Lamp                ▸  (same submenu)
├── ──────────────
├── Busted (skipped)          [greyed out]
├── ──────────────
└── Quit
```

## Behavior

### Group Operations (All Lights On/Off, Scenes, Set All Color)
- Apply to every device EXCEPT "Busted"
- "All Lights On/Off" sends power toggle to each device in parallel
- Scenes use the existing preset definitions from the Cloudflare worker (bright-evening, white, orange, blue) — replicated locally in the app so we don't depend on the worker for manual control

### Music Mode
- **ON**: Power on all devices except Busted and Table Lamp (the 5 DreamView group members). They auto-resume the user's custom DreamView music sync config.
- **OFF**: Power off the same 5 devices.
- No `music_setting` API calls — DreamView groups can't be controlled via REST API. Power toggle is the safe approach that preserves the user's carefully dialed-in DreamView settings.

### Individual Device Control
- **On/Off**: Toggle power for that specific device
- **Brightness**: Submenu with preset levels (10%, 25%, 50%, 75%, 100%) — uses `devices.capabilities.range` with `brightness` instance
- **Color**: Opens macOS native `NSColorPanel`. Selected color is sent as RGB via `devices.capabilities.color_setting`

### Busted Device
- Identified by `deviceName == "Busted"` from the API response
- Shown in menu as greyed-out informational item
- Excluded from ALL operations: group on/off, scenes, color changes, music mode
- No submenu — clicking it does nothing

## Technical Architecture

### Single Python File
`govee-menubar.py` in the project root. Pattern matches `claude-usage-monitor.py`.

### Dependencies
- `pyobjc` (AppKit, Foundation) — menu bar, color picker, icon rendering
- `requests` — Govee API calls

### API Communication
- Direct to Govee OpenAPI v1 (`https://openapi.api.govee.com/router/api/v1`)
- API key: loaded from env var `GOVEE_API_KEY`, fallback to hardcoded key
- All API calls run on background threads to avoid blocking the UI
- Device list fetched once on launch, cached in memory

### Scenes (Local Definitions)
Replicated from the Cloudflare worker to avoid network dependency:

```python
SCENES = {
    'bright-evening': {
        'Left Corner Light': {'power': True, 'brightness': 100},
        'Right Corner Light': {'power': True, 'brightness': 100},
        'Side Light': {'power': True, 'brightness': 100},
        'Uplighter Floor Lamp': {'power': True, 'brightness': 100, 'color': (255, 0, 0)},
        'Table Lamp': {'power': False},
        'Star Light Projector': {'power': False},
    },
    'white': {
        'Left Corner Light': {'power': True, 'brightness': 100, 'color': (255, 255, 255)},
        # ... etc
    },
    # ... orange, blue
}
```

### Icon
- Download colorful lightbulb from icons8 3D-fluency
- Resize to 22x22 for menu bar
- Bundle as base64-encoded PNG in the script (no external file dependency)

### Startup
- Launch via `python3 govee-menubar.py` or create a macOS Launch Agent for auto-start
- Single-instance guard using `fcntl.LOCK_EX` (same pattern as usage monitor)

## Preset Definitions (from worker.js, updated with correct device names)

### Bright Evening
- Left Corner Light: on, 100% brightness
- Right Corner Light: on, 100% brightness
- Side Light: on, 100% brightness
- Uplighter Floor Lamp: on, 100%, red (255, 0, 0)
- Table Lamp: off
- Star Light Projector: off

### White
- Left Corner Light: on, 100%, white (255, 255, 255)
- Right Corner Light: on, 100%, white (255, 255, 255)
- Side Light: on, 100%, white (255, 255, 255)
- Uplighter Floor Lamp: on, 100%, white (255, 255, 255)
- Table Lamp: on, 1%, purple (139, 0, 255)
- Star Light Projector: off

### Orange
- All controllable lights: on, 100%, warm orange (255, 220, 180)

### Blue
- Left Corner Light: on, 100%, scene: Glacier (H607C id:9641 paramId:16516)
- Right Corner Light: on, 100%, scene: Glacier (H607C id:9641 paramId:16516)
- Side Light: on, 100%, scene: Glacier (H607C id:9641 paramId:16516)
- Uplighter Floor Lamp: on, 100%, scene: Milky Way (H60B0 id:17695 paramId:27857)
- Table Lamp: on, 100%, scene: Milky Way (H6022 id:11339 paramId:18659)
- Star Light Projector: off

## DreamView Music Group Members
Based on Govee app screenshot (5 devices, Right Corner Light as lead):
1. Right Corner Light (lead)
2. Left Corner Light
3. Side Light
4. Uplighter Floor Lamp
5. Star Light Projector

Table Lamp is excluded from the music group (6 controllable devices - 5 in group = Table Lamp not in group). Confirm with user if needed.
