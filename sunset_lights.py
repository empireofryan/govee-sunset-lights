#!/usr/bin/env python3
"""
Turn on Govee lights at sunset for Denver, CO.
Designed to run via GitHub Actions on a schedule.
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Denver coordinates
LATITUDE = 39.7392
LONGITUDE = -104.9903
TIMEZONE = ZoneInfo("America/Denver")

# How close to sunset (in minutes) to trigger
SUNSET_WINDOW_MINUTES = 10

GOVEE_API_BASE = "https://openapi.api.govee.com"


def get_sunset_time() -> datetime:
    """Get today's sunset time for Denver from sunrise-sunset.org API."""
    url = "https://api.sunrise-sunset.org/json"
    params = {
        "lat": LATITUDE,
        "lng": LONGITUDE,
        "formatted": 0,  # ISO 8601 format
        "date": "today"
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if data["status"] != "OK":
        raise Exception(f"Sunset API error: {data}")

    sunset_str = data["results"]["sunset"]
    sunset_utc = datetime.fromisoformat(sunset_str.replace("Z", "+00:00"))
    return sunset_utc


def is_sunset_time(sunset: datetime, window_minutes: int = SUNSET_WINDOW_MINUTES) -> bool:
    """Check if current time is within the sunset window."""
    now = datetime.now(timezone.utc)
    diff_seconds = abs((now - sunset).total_seconds())
    diff_minutes = diff_seconds / 60

    print(f"Current time (UTC): {now.isoformat()}")
    print(f"Sunset time (UTC): {sunset.isoformat()}")
    print(f"Sunset time (Denver): {sunset.astimezone(TIMEZONE).strftime('%I:%M %p')}")
    print(f"Difference: {diff_minutes:.1f} minutes")

    return diff_minutes <= window_minutes


def get_govee_devices(api_key: str) -> list:
    """Fetch all Govee devices from the API."""
    url = f"{GOVEE_API_BASE}/router/api/v1/user/devices"
    headers = {
        "Content-Type": "application/json",
        "Govee-API-Key": api_key
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()

    if data.get("code") != 200:
        raise Exception(f"Govee API error: {data}")

    return data.get("data", [])


def turn_on_device(api_key: str, device: dict) -> bool:
    """Turn on a single Govee device."""
    url = f"{GOVEE_API_BASE}/router/api/v1/device/control"
    headers = {
        "Content-Type": "application/json",
        "Govee-API-Key": api_key
    }

    # Check if device supports on/off
    capabilities = device.get("capabilities", [])
    has_power = any(
        cap.get("type") == "devices.capabilities.on_off"
        for cap in capabilities
    )

    if not has_power:
        print(f"  Device {device.get('deviceName')} doesn't support power control, skipping")
        return False

    payload = {
        "requestId": f"sunset-{datetime.now().timestamp()}",
        "payload": {
            "sku": device["sku"],
            "device": device["device"],
            "capability": {
                "type": "devices.capabilities.on_off",
                "instance": "powerSwitch",
                "value": 1  # 1 = on, 0 = off
            }
        }
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()

    success = data.get("code") == 200
    if success:
        print(f"  Turned on: {device.get('deviceName', device['device'])}")
    else:
        print(f"  Failed to turn on {device.get('deviceName')}: {data}")

    return success


def main():
    api_key = os.environ.get("GOVEE_API_KEY")
    if not api_key:
        print("Error: GOVEE_API_KEY environment variable not set")
        sys.exit(1)

    # Check for force flag (useful for testing)
    force = "--force" in sys.argv or os.environ.get("FORCE_RUN") == "true"

    try:
        sunset = get_sunset_time()

        if not force and not is_sunset_time(sunset):
            print("Not sunset time yet, exiting.")
            sys.exit(0)

        if force:
            print("Force flag set, running regardless of time.")
        else:
            print("It's sunset time! Turning on lights...")

        devices = get_govee_devices(api_key)
        print(f"Found {len(devices)} Govee device(s)")

        if not devices:
            print("No devices found. Make sure your devices are WiFi-enabled and linked to your Govee account.")
            sys.exit(0)

        success_count = 0
        for device in devices:
            print(f"\nProcessing: {device.get('deviceName', 'Unknown')} ({device['sku']})")
            if turn_on_device(api_key, device):
                success_count += 1

        print(f"\nDone! Turned on {success_count}/{len(devices)} device(s)")

    except requests.RequestException as e:
        print(f"API request failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
