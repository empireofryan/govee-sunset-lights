const GOVEE_API = 'https://openapi.api.govee.com/router/api/v1';
const DENVER_LAT = 39.7392;
const DENVER_LNG = -104.9903;

// Auto-off hour in Denver local time (1 AM)
const OFF_HOUR_LOCAL = 1;

export default {
  async scheduled(event, env, ctx) {
    const denverHour = getDenverHour();

    // Turn off at 1:00 AM Denver time (works for both MST and MDT)
    if (denverHour === OFF_HOUR_LOCAL) {
      console.log(`Lights OFF - 1:00 AM Denver time (UTC hour: ${new Date().getUTCHours()})`);
      await controlAllLightsWithRetry(env, false);
    }
    // Sunset window: 3PM-7PM Denver time - check for sunset
    else if (denverHour >= 15 && denverHour <= 19) {
      await checkSunsetAndTurnOn(env);
    }
  },

  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/on') {
      await controlAllLightsWithRetry(env, true);
      return new Response('Lights ON');
    }
    if (url.pathname === '/off') {
      await controlAllLightsWithRetry(env, false);
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

    return new Response('Endpoints: /on, /off, /sunset, /status');
  }
};

function getDenverHour() {
  // Get current hour in Denver, correctly handling MST/MDT via Intl API
  const denverTime = new Date().toLocaleString('en-US', { timeZone: 'America/Denver', hour12: false });
  // Format: "M/D/YYYY, HH:MM:SS"
  const timePart = denverTime.split(', ')[1];
  return parseInt(timePart.split(':')[0], 10);
}

function getDenverDate() {
  // Get current date in Denver, correctly handling MST/MDT via Intl API
  const formatter = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Denver' }); // en-CA gives YYYY-MM-DD
  return formatter.format(new Date());
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

  // Turn on if within 20 min of sunset (cron runs every 15 min, so need margin)
  if (diffMinutes >= -5 && diffMinutes <= 20) {
    await controlAllLights(env, true);
    console.log('Lights ON at sunset!');
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

async function controlAllLightsWithRetry(env, turnOn, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const results = await controlAllLights(env, turnOn);
      const failedDevices = results.filter(r => !r.success);

      if (failedDevices.length === 0) {
        console.log(`All devices ${turnOn ? 'ON' : 'OFF'} (attempt ${attempt})`);
        return;
      }

      console.log(`Attempt ${attempt}: ${failedDevices.length} device(s) failed`);

      if (attempt < maxRetries) {
        // Exponential backoff: 2s, 4s
        await new Promise(r => setTimeout(r, 2000 * attempt));
      }
    } catch (err) {
      console.error(`Attempt ${attempt} error:`, err);
      if (attempt < maxRetries) {
        await new Promise(r => setTimeout(r, 2000 * attempt));
      }
    }
  }
  console.error(`Failed to turn ${turnOn ? 'on' : 'off'} all lights after ${maxRetries} attempts`);
}

async function controlAllLights(env, turnOn) {
  const headers = {
    'Content-Type': 'application/json',
    'Govee-API-Key': env.GOVEE_API_KEY
  };

  // Get all devices
  const devicesRes = await fetch(`${GOVEE_API}/user/devices`, { headers });
  const devicesData = await devicesRes.json();
  const devices = devicesData.data || [];

  console.log(`Found ${devices.length} devices`);

  // Control all devices in parallel
  const results = await Promise.all(devices.map(async (device) => {
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
      const data = await res.json();
      const success = data.code === 200;
      console.log(`${turnOn ? 'ON' : 'OFF'}: ${device.deviceName} - ${success ? 'OK' : 'FAILED'}`);
      return { device: device.deviceName, success };
    } catch (err) {
      console.error(`Failed to control ${device.deviceName}:`, err);
      return { device: device.deviceName, success: false };
    }
  }));

  return results;
}
