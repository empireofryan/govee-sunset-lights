const GOVEE_API = 'https://openapi.api.govee.com/router/api/v1';
const DENVER_LAT = 39.7392;
const DENVER_LNG = -104.9903;

// White-only H607C (named "Busted" in Govee): on 7 AM to 2 AM daily, skipped by the 1 AM all-off
const BUSTED_NAMES = ['Busted', 'White Lamp'];

const PRESETS = {
  'bright-evening': {
    description: 'Bright Evening - floor lamps full, uplighter red, table off',
    settings: [
      { name: 'Floor Lamp 2', power: true, brightness: 100 },
      { name: 'Uplighter Floor Lamp', power: true, brightness: 100, colorRgb: { r: 255, g: 0, b: 0 } },
      { name: 'Table Lamp', power: false },
      { name: 'Floor Lamp 3', power: true, brightness: 100 },
    ]
  },
  'white': {
    description: 'White - all lamps full white, table lamp dim purple',
    settings: [
      { name: 'Floor Lamp 2', power: true, brightness: 100, colorRgb: { r: 255, g: 255, b: 255 } },
      { name: 'Uplighter Floor Lamp', power: true, brightness: 100, colorRgb: { r: 255, g: 255, b: 255 } },
      { name: 'Table Lamp', power: true, brightness: 1, colorRgb: { r: 139, g: 0, b: 255 } },
      { name: 'Floor Lamp 3', power: true, brightness: 100, colorRgb: { r: 255, g: 255, b: 255 } },
    ]
  },
  'orange': {
    description: 'Orange - warm orange glow, all lamps full brightness',
    settings: [
      { name: 'Floor Lamp 2', power: true, brightness: 100, colorRgb: { r: 255, g: 220, b: 180 } },
      { name: 'Uplighter Floor Lamp', power: true, brightness: 100, colorRgb: { r: 255, g: 220, b: 180 } },
      { name: 'Table Lamp', power: true, brightness: 100, colorRgb: { r: 255, g: 220, b: 180 } },
      { name: 'Floor Lamp 3', power: true, brightness: 100, colorRgb: { r: 255, g: 220, b: 180 } },
    ]
  },
  'blue': {
    description: 'Blue - uplighter milky way, floor lamps glacier, table lamp milky way',
    settings: [
      { name: 'Floor Lamp 2', power: true, brightness: 100, scene: { H607C: { id: 9641, paramId: 16516 } } },
      { name: 'Uplighter Floor Lamp', power: true, brightness: 100, scene: { H60B0: { id: 17695, paramId: 27857 } } },
      { name: 'Table Lamp', power: true, brightness: 100, scene: { H6022: { id: 11339, paramId: 18659 } } },
      { name: 'Floor Lamp 3', power: true, brightness: 100, scene: { H607C: { id: 9641, paramId: 16516 } } },
    ]
  }
};

export default {
  async scheduled(event, env, ctx) {
    const denverHour = getDenverHour();

    // Midnight Denver time - bedroom table light off
    if (denverHour === 0) {
      await controlLightsByName(env, false, 'table');
      console.log('Bedroom table light OFF - Midnight Denver');
    }
    // 1:00 AM Denver time - all lights off except the busted lamp (retry every 30s until success)
    else if (denverHour === 1) {
      await retryAllLights(env, false, '1:00 AM', BUSTED_NAMES);
    }
    // 2:00 AM Denver time - busted lamp off (it stays on 7 AM to 2 AM)
    else if (denverHour === 2) {
      await retryAllLights(env, false, '2:00 AM', [], BUSTED_NAMES);
    }
    // 7:00 AM Denver time - busted lamp on
    else if (denverHour === 7) {
      await retryAllLights(env, true, '7:00 AM', [], BUSTED_NAMES);
    }
    // 3PM-8PM Denver time - turn on ~1hr before sunset (hour 20 needed for late-summer sunsets after 19:50)
    else if (denverHour >= 15 && denverHour <= 20) {
      await checkSunsetAndTurnOn(env);
    }
  },

  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/on') {
      await controlAllLights(env, true);
      return new Response('Lights ON');
    }
    if (url.pathname === '/off') {
      await controlAllLights(env, false);
      return new Response('Lights OFF');
    }
    if (url.pathname === '/sunset') {
      const result = await checkSunsetAndTurnOn(env);
      return new Response(JSON.stringify(result, null, 2));
    }
    if (url.pathname === '/status') {
      const result = await getDeviceStatus(env);
      return new Response(JSON.stringify(result, null, 2), {
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }
    if (url.pathname === '/modes') {
      const modes = Object.entries(PRESETS).map(([key, val]) => ({ name: key, description: val.description }));
      return new Response(JSON.stringify(modes, null, 2), {
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }
    if (url.pathname.startsWith('/mode/')) {
      const presetName = url.pathname.slice(6);
      const result = await applyPreset(env, presetName);
      const status = result.error ? 400 : 200;
      return new Response(JSON.stringify(result, null, 2), {
        status,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }
    if (url.pathname === '/scenes') {
      const sku = url.searchParams.get('sku') || 'H6095';
      const device = url.searchParams.get('device') || '7D:60:C1:9A:6A:63:3B:DC';
      const result = await getScenes(env, sku, device);
      return new Response(JSON.stringify(result, null, 2), {
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }
    if (url.pathname === '/devices/raw') {
      const result = await getRawDevices(env);
      return new Response(JSON.stringify(result, null, 2), {
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }
    if (url.pathname === '/control') {
      if (request.method !== 'POST') {
        return new Response('POST required with { sku, device, capability }', { status: 405 });
      }
      const body = await request.json();
      const result = await sendControl(env, body);
      return new Response(JSON.stringify(result, null, 2), {
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }
    if (url.pathname === '/snapshot') {
      const result = await captureSnapshot(env);
      return new Response(JSON.stringify(result, null, 2), {
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }

    return new Response('Endpoints: /on, /off, /sunset, /status, /modes, /mode/<name>, /snapshot');
  }
};

function getDenverDate() {
  // Get current date in Denver, accounting for MST/MDT automatically
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Denver' });
}

function getDenverHour() {
  // Get current hour in Denver, accounting for MST/MDT automatically
  return parseInt(new Date().toLocaleString('en-US', { timeZone: 'America/Denver', hour: 'numeric', hour12: false }));
}

async function checkSunsetAndTurnOn(env) {
  // Use Denver local date, not UTC date
  const today = getDenverDate();
  const sunsetRes = await fetch(
    `https://api.sunrise-sunset.org/json?lat=${DENVER_LAT}&lng=${DENVER_LNG}&date=${today}&formatted=0`
  );
  const sunsetData = await sunsetRes.json();

  if (sunsetData.status !== 'OK') {
    console.log('Failed to fetch sunset time');
    return { error: 'Failed to fetch sunset' };
  }

  const sunsetTime = new Date(sunsetData.results.sunset);
  const now = new Date();
  const diffMinutes = (now - sunsetTime) / 1000 / 60;

  console.log(`Denver date: ${today}, Sunset: ${sunsetTime.toISOString()}, Now: ${now.toISOString()}, Diff: ${diffMinutes} min`);

  // Turn on ~1 hour before sunset. Window is 20 min wide centered on -60 min
  // (cron runs every 15 min, so this reliably catches a pass before sunset).
  if (diffMinutes >= -70 && diffMinutes <= -50) {
    await controlAllLights(env, true);
    console.log('Lights ON ~1hr before sunset!');
    return { triggered: true, sunset: sunsetTime.toISOString(), diff: diffMinutes };
  }

  return { triggered: false, sunset: sunsetTime.toISOString(), diff: diffMinutes, denverDate: today, message: 'Not sunset time yet' };
}

async function getDeviceStatus(env) {
  const headers = {
    'Content-Type': 'application/json',
    'Govee-API-Key': env.GOVEE_API_KEY
  };

  try {
    // Get all devices
    const devicesRes = await fetch(`${GOVEE_API}/user/devices`, { headers });
    const devicesData = await devicesRes.json();
    const devices = devicesData.data || [];

    const statuses = await Promise.all(devices.map(async (device) => {
      try {
        // Try to get device state
        const stateRes = await fetch(`${GOVEE_API}/device/state`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            requestId: `status-${Date.now()}-${device.device}`,
            payload: {
              sku: device.sku,
              device: device.device
            }
          })
        });
        const stateData = await stateRes.json();
        const capabilities = stateData.payload?.capabilities || [];

        // Extract relevant state
        const powerState = capabilities.find(c => c.type === 'devices.capabilities.on_off');
        const brightnessState = capabilities.find(c => c.type === 'devices.capabilities.range' && c.instance === 'brightness');
        const colorState = capabilities.find(c => c.instance === 'colorRgb');
        const sceneState = capabilities.find(c => c.instance === 'lightScene');

        // Convert color int to RGB
        const colorInt = colorState?.state?.value;
        let rgb = null;
        if (colorInt !== null && colorInt !== undefined) {
          rgb = {
            r: (colorInt >> 16) & 255,
            g: (colorInt >> 8) & 255,
            b: colorInt & 255
          };
        }

        return {
          name: device.deviceName,
          sku: device.sku,
          power: powerState?.state?.value === 1 ? 'ON' : 'OFF',
          brightness: brightnessState?.state?.value ?? null,
          color: rgb,
          scene: sceneState?.state?.value || null
        };
      } catch (err) {
        return {
          name: device.deviceName,
          sku: device.sku,
          error: err.message
        };
      }
    }));

    return { devices: statuses, timestamp: new Date().toISOString() };
  } catch (err) {
    return { error: err.message, timestamp: new Date().toISOString() };
  }
}

async function controlLightsByName(env, turnOn, nameFilter) {
  const headers = {
    'Content-Type': 'application/json',
    'Govee-API-Key': env.GOVEE_API_KEY
  };

  const devicesRes = await fetch(`${GOVEE_API}/user/devices`, { headers });
  const devicesData = await devicesRes.json();
  const devices = devicesData.data || [];

  const matching = devices.filter(d =>
    d.deviceName.toLowerCase().includes(nameFilter.toLowerCase())
  );

  console.log(`Found ${matching.length} device(s) matching "${nameFilter}" out of ${devices.length} total`);

  for (const device of matching) {
    try {
      await fetch(`${GOVEE_API}/device/control`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          requestId: `cron-${Date.now()}-${device.device}`,
          payload: {
            sku: device.sku,
            device: device.device,
            capability: {
              type: 'devices.capabilities.on_off',
              instance: 'powerSwitch',
              value: turnOn ? 1 : 0
            }
          }
        })
      });
      console.log(`${turnOn ? 'ON' : 'OFF'}: ${device.deviceName}`);
    } catch (err) {
      console.error(`Failed to control ${device.deviceName}:`, err);
    }
  }

  return matching.map(d => d.deviceName);
}

async function applyPreset(env, presetName) {
  const preset = PRESETS[presetName];
  if (!preset) {
    return { error: `Unknown preset: ${presetName}`, available: Object.keys(PRESETS) };
  }

  const headers = {
    'Content-Type': 'application/json',
    'Govee-API-Key': env.GOVEE_API_KEY
  };

  const devicesRes = await fetch(`${GOVEE_API}/user/devices`, { headers });
  const devicesData = await devicesRes.json();
  const devices = devicesData.data || [];

  const results = [];

  for (const setting of preset.settings) {
    const matching = devices.filter(d =>
      d.deviceName.toLowerCase().includes(setting.name.toLowerCase())
    );

    for (const device of matching) {
      const actions = [];

      // Power
      try {
        await fetch(`${GOVEE_API}/device/control`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            requestId: `preset-${Date.now()}-${device.device}-power`,
            payload: {
              sku: device.sku,
              device: device.device,
              capability: {
                type: 'devices.capabilities.on_off',
                instance: 'powerSwitch',
                value: setting.power ? 1 : 0
              }
            }
          })
        });
        actions.push(`power ${setting.power ? 'ON' : 'OFF'}`);
      } catch (err) {
        actions.push(`power failed: ${err.message}`);
      }

      // Brightness (only if powered on and specified)
      if (setting.power && setting.brightness !== undefined) {
        try {
          await fetch(`${GOVEE_API}/device/control`, {
            method: 'POST',
            headers,
            body: JSON.stringify({
              requestId: `preset-${Date.now()}-${device.device}-brightness`,
              payload: {
                sku: device.sku,
                device: device.device,
                capability: {
                  type: 'devices.capabilities.range',
                  instance: 'brightness',
                  value: setting.brightness
                }
              }
            })
          });
          actions.push(`brightness ${setting.brightness}%`);
        } catch (err) {
          actions.push(`brightness failed: ${err.message}`);
        }
      }

      // Color (only if powered on and specified, and no scene)
      if (setting.power && setting.colorRgb && !setting.scene) {
        const colorInt = (setting.colorRgb.r << 16) | (setting.colorRgb.g << 8) | setting.colorRgb.b;
        try {
          await fetch(`${GOVEE_API}/device/control`, {
            method: 'POST',
            headers,
            body: JSON.stringify({
              requestId: `preset-${Date.now()}-${device.device}-color`,
              payload: {
                sku: device.sku,
                device: device.device,
                capability: {
                  type: 'devices.capabilities.color_setting',
                  instance: 'colorRgb',
                  value: colorInt
                }
              }
            })
          });
          actions.push(`color rgb(${setting.colorRgb.r},${setting.colorRgb.g},${setting.colorRgb.b})`);
        } catch (err) {
          actions.push(`color failed: ${err.message}`);
        }
      }

      // Scene (only if powered on and specified)
      if (setting.power && setting.scene) {
        const sceneValue = setting.scene[device.sku];
        if (sceneValue) {
          try {
            await fetch(`${GOVEE_API}/device/control`, {
              method: 'POST',
              headers,
              body: JSON.stringify({
                requestId: `preset-${Date.now()}-${device.device}-scene`,
                payload: {
                  sku: device.sku,
                  device: device.device,
                  capability: {
                    type: 'devices.capabilities.dynamic_scene',
                    instance: 'lightScene',
                    value: sceneValue
                  }
                }
              })
            });
            actions.push(`scene ${JSON.stringify(sceneValue)}`);
          } catch (err) {
            actions.push(`scene failed: ${err.message}`);
          }
        } else {
          actions.push(`scene skipped (no mapping for SKU ${device.sku})`);
        }
      }

      results.push({ device: device.deviceName, actions });
    }

    if (matching.length === 0) {
      results.push({ device: setting.name, actions: ['no matching device found'] });
    }
  }

  console.log(`Applied preset: ${presetName}`);
  return { preset: presetName, description: preset.description, results };
}

async function captureSnapshot(env) {
  const status = await getDeviceStatus(env);
  if (status.error) return status;

  const settings = status.devices.map(d => {
    const entry = { name: d.name, power: d.power === 'ON' };
    if (entry.power && d.brightness !== null) {
      entry.brightness = d.brightness;
    }
    if (entry.power && d.color && (d.color.r || d.color.g || d.color.b)) {
      entry.colorRgb = d.color;
    }
    return entry;
  });

  return {
    snapshot: { description: 'My Preset', settings },
    timestamp: status.timestamp
  };
}

async function getScenes(env, sku, device) {
  const headers = {
    'Content-Type': 'application/json',
    'Govee-API-Key': env.GOVEE_API_KEY
  };
  const payload = { sku, device };
  const body = JSON.stringify({ requestId: `scenes-${Date.now()}`, payload });
  const res = await fetch(`${GOVEE_API}/device/scenes`, { method: 'POST', headers, body });
  const data = await res.json();
  const diyBody = JSON.stringify({ requestId: `diy-${Date.now()}`, payload });
  const diyRes = await fetch(`${GOVEE_API}/device/diy-scenes`, { method: 'POST', headers, body: diyBody });
  const diyData = await diyRes.json();
  return { lightScenes: data, diyScenes: diyData };
}

async function getRawDevices(env) {
  const headers = {
    'Content-Type': 'application/json',
    'Govee-API-Key': env.GOVEE_API_KEY
  };
  const devicesRes = await fetch(`${GOVEE_API}/user/devices`, { headers });
  const devicesData = await devicesRes.json();
  return devicesData;
}

async function sendControl(env, body) {
  const headers = {
    'Content-Type': 'application/json',
    'Govee-API-Key': env.GOVEE_API_KEY
  };
  const res = await fetch(`${GOVEE_API}/device/control`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      requestId: `manual-${Date.now()}`,
      payload: body
    })
  });
  return await res.json();
}

async function retryAllLights(env, turnOn, label, excludeNames = [], onlyNames = null) {
  const MAX_RETRIES = 10;
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    const success = await controlAllLights(env, turnOn, excludeNames, onlyNames);
    if (success) {
      console.log(`Lights ${turnOn ? 'ON' : 'OFF'} - ${label} Denver (attempt ${attempt})`);
      return true;
    }
    console.error(`Attempt ${attempt}/${MAX_RETRIES} failed (${label})`);
    if (attempt < MAX_RETRIES) {
      await new Promise(r => setTimeout(r, 30000));
    }
  }
  return false;
}

async function controlAllLights(env, turnOn, excludeNames = [], onlyNames = null) {
  const headers = {
    'Content-Type': 'application/json',
    'Govee-API-Key': env.GOVEE_API_KEY
  };

  // Get all devices
  const devicesRes = await fetch(`${GOVEE_API}/user/devices`, { headers });
  if (!devicesRes.ok) {
    console.error(`Failed to fetch devices: HTTP ${devicesRes.status}`);
    return false;
  }
  const devicesData = await devicesRes.json();
  const devices = (devicesData.data || []).filter(d =>
    !excludeNames.includes(d.deviceName) && (!onlyNames || onlyNames.includes(d.deviceName))
  );

  if (devices.length === 0) {
    console.error('No devices found');
    return false;
  }

  console.log(`Found ${devices.length} devices`);

  let allSucceeded = true;

  // Control each device
  for (const device of devices) {
    try {
      const res = await fetch(`${GOVEE_API}/device/control`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          requestId: `cron-${Date.now()}-${device.device}`,
          payload: {
            sku: device.sku,
            device: device.device,
            capability: {
              type: 'devices.capabilities.on_off',
              instance: 'powerSwitch',
              value: turnOn ? 1 : 0
            }
          }
        })
      });
      if (!res.ok) {
        console.error(`Failed to control ${device.deviceName}: HTTP ${res.status}`);
        allSucceeded = false;
      } else {
        console.log(`${turnOn ? 'ON' : 'OFF'}: ${device.deviceName}`);
      }
    } catch (err) {
      console.error(`Failed to control ${device.deviceName}:`, err);
      allSucceeded = false;
    }
  }

  return allSucceeded;
}
