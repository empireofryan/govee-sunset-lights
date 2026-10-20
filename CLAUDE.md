# Govee Sunset Lights

Cloudflare Worker + macOS menu bar app for controlling Govee smart lights.

## Stack
- Cloudflare Workers (JavaScript) — cron automation
- Python + pyobjc — menu bar controller
- Govee OpenAPI v1
- sunrise-sunset.org API for sunset times

## Key Files
- `cloudflare-cron/worker.js` — main worker: cron handler, HTTP endpoints, Govee API calls
- `cloudflare-cron/wrangler.toml` — worker config + cron triggers
- `menubar/govee-lights.py` — macOS menu bar controller (single file)
- `menubar/icon.png` — menu bar icon (purple/yellow lamp)
- `menubar/com.ryan.govee-lights.plist` — launchd auto-start agent
- `sunset_lights.py` — legacy Python version (not actively used)

## Endpoints
`https://govee-lights-cron.rjohnson2001.workers.dev/`
- `/on`, `/off` — manual all-lights control
- `/sunset` — check sunset logic
- `/status` — all device states
- `/modes`, `/mode/<name>` — preset lighting modes (bright-evening, white, orange, blue)
- `/snapshot` — capture current state as preset format

## Schedule (Denver time, DST-aware)
- **Midnight** — table lamp off
- **1:00 AM** — all lights off except the Busted lamp (10 retries, 30s apart)
- **2:00 AM** — Busted lamp off; **7:00 AM** — Busted lamp on (on 7 AM-2 AM daily, `BUSTED_NAMES` in worker.js)
- **3-8 PM** — check sunset every 15 min, turn lights on ~1 hour before sunset (window: diff -70 to -50 min)

## Deploy
```bash
cd cloudflare-cron && wrangler deploy
```

## Devices (10 in account as of 2026-10-20)
- Left Corner Light (H607C), Right Corner Light (H607C), Side Light (H607C) — floor lamps
- Uplighter Floor Lamp (H60B0), Table Lamp (H6022), Star Light Projector (H6095)
- **Wall Light + Wall Light 2** (H1771, added 2026-10-12): 79 scenes, DreamView, `wallWashingLightToggle` + `nightlampToggle`. Menu bar has a combined "Wall Lights (both)" menu (power, wall wash, night light, brightness, colors, scenes) and a "Scenes (minus Wall Lights)" menu, because H1771 cut the all-lights shared scenes from 20 to 13.
- **Tree Floor Lamp** (H60B2 `20:69:CC:55:05:86:40:48`, added 2026-10-20): standard caps (power, brightness, color, colorTemp, scenes, DreamView, light1-3 toggles). No code changes needed: worker + menu bar enumerate all account devices. It cut the all-lights shared scenes from 13 to 11 (lost Starry Sky, Thanksgiving); "Scenes (minus Tree Floor Lamp)" menu restores them.
- Considering a ceiling light: H60A1 (12", 2400lm) or H60A6 (15" Pro, 4300lm). Cloud-API support unconfirmed until one is on the account; both have LAN API, H60A6 also Matter.
- **White-only lamp** (H607C `26:AB:CB:24:89:C0:EB:03`, currently named "Busted" in Govee; "White Lamp" also accepted): colors render wrong, white LEDs fine. Excluded from scenes/colors; own white-only submenu (2200K).
- DreamView music group: all except White Lamp + Table Lamp (Right Corner Light as lead)
- H607C extras: `pillarLightToggle` + `baseLightToggle` segments exist outside master brightness (both turned ON 2026-07-31 for max output; state not readable via API)

## Menu Bar App
Run: `python3 menubar/govee-lights.py`

Auto-start: `cp menubar/com.ryan.govee-lights.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.ryan.govee-lights.plist`

Features: all on/off, music mode (DreamView) on/off, universal scenes (11), "minus X" scene menus driven by `EXCLUDE_GROUPS`, set all color/brightness, Wall Lights group menu, individual device control. White-only lamp matched by `BUSTED_NAMES` = {"White Lamp","Busted"}.
New device added in the Govee app? Restart the app (devices load only at startup). Restart after edits: `launchctl kickstart -k gui/$(id -u)/com.ryan.govee-lights` (log: /tmp/govee-lights.log).

## Current Status
- Cloudflare worker: last deployed 2026-10-20 (Busted lamp 7 AM-2 AM schedule; crons merged into one hourly trigger)
- Menu bar app: built 2026-04-15
- Fixed DST bug: uses `Intl` timezone API (`America/Denver`) for automatic MST/MDT handling

## Important Decisions
- Duplicate scene names (H1771 + H607C each list two "Halloween"s): the plain name gets the first one unless `PREFERRED_SCENE_IDS` overrides it; the others become "Name (2)". Ryan's picks: H1771 Halloween = 32183 (first; the second is pink/blue), H607C Halloween = 9659 (second, set as an override).
- Cron triggers use wide UTC windows (`0 6-9,13-14 * * *`, one trigger so no hour fires twice) to cover both MST and MDT; the worker checks Denver hour to decide what action to take.
- API key stored as Cloudflare secret (`GOVEE_API_KEY`).

## H6095 Star Projector — Laser Control (SOLVED 2026-07-31)
- No direct API capability to toggle the green laser independently (re-verified against live API).
- **"Chill" DIY scene (id `22555274`) = nebula only, laser off** — visually confirmed by Ryan.
- Apply: `{ type: "devices.capabilities.dynamic_scene", instance: "diyScene", value: 22555274 }` (diyScene value is the bare int; lightScene uses `{id, paramId}`).
- Menu bar app has "Projector: Nebula (No Lasers)" item (powers on + applies the scene).
- Device: `7D:60:C1:9A:6A:63:3B:DC`. New nebula-only scenes: make in app with laser slider 0, list ids via POST `/device/diy-scenes`.
