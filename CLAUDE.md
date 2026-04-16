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
- **1:00 AM** — all lights off (10 retries, 30s apart)
- **3-7 PM** — check for sunset every 15 min, turn on if within window

## Deploy
```bash
cd cloudflare-cron && wrangler deploy
```

## Devices (7 total)
- Left Corner Light (H607C), Right Corner Light (H607C), Side Light (H607C) — floor lamps
- Uplighter Floor Lamp (H60B0), Table Lamp (H6022), Star Light Projector (H6095)
- **Busted** (H607C) — broken, NEVER control (excluded from all group operations)
- DreamView music group: all except Busted + Table Lamp (5 devices, Right Corner Light as lead)

## Menu Bar App
Run: `python3 menubar/govee-lights.py`

Auto-start: `cp menubar/com.ryan.govee-lights.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.ryan.govee-lights.plist`

Features: all on/off, music mode (DreamView) on/off, 10 universal scenes, set all color/brightness, individual device control. "Busted" always excluded.

## Current Status
- Cloudflare worker: deployed 2026-04-06
- Menu bar app: built 2026-04-15
- Fixed DST bug: uses `Intl` timezone API (`America/Denver`) for automatic MST/MDT handling

## Important Decisions
- Cron triggers use wide UTC windows (e.g. `0 6-7 * * *`) to cover both MST and MDT; the worker checks Denver hour to decide what action to take.
- API key stored as Cloudflare secret (`GOVEE_API_KEY`).

## H6095 Star Projector — Laser Control
- No direct API capability to toggle the green laser independently.
- Workaround: Create a "nebula only" DIY scene in Govee Home app (laser slider = 0), then query its ID via Get Dynamic Scene API and apply via `diyScene` capability.
- Scene control uses: `{ type: "devices.capabilities.dynamic_scene", instance: "diyScene", value: { id, paramId } }`
