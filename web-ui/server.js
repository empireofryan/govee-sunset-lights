import express from 'express'
import cors from 'cors'

const app = express()
app.use(cors())
app.use(express.json())

const API_KEY = '00b0d8f5-c2cb-4b42-9522-bbcf94492b86'
const API_BASE = 'https://openapi.api.govee.com'

const headers = {
  'Content-Type': 'application/json',
  'Govee-API-Key': API_KEY
}

// Get devices and their scenes
app.get('/api/devices', async (req, res) => {
  try {
    const devicesRes = await fetch(`${API_BASE}/router/api/v1/user/devices`, { headers })
    const devicesData = await devicesRes.json()

    const devices = devicesData.data || []
    const scenes = {}

    // Fetch scenes for each device
    for (const device of devices) {
      try {
        const scenesRes = await fetch(`${API_BASE}/router/api/v1/device/scenes`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            requestId: `scenes-${device.device}`,
            payload: { sku: device.sku, device: device.device }
          })
        })
        const scenesData = await scenesRes.json()
        const lightScenes = scenesData.payload?.capabilities?.find(c => c.instance === 'lightScene')
        if (lightScenes) {
          scenes[device.device] = lightScenes.parameters.options
        }
      } catch (err) {
        console.error(`Failed to fetch scenes for ${device.deviceName}:`, err.message)
      }
    }

    res.json({ devices, scenes })
  } catch (err) {
    console.error('Failed to fetch devices:', err)
    res.status(500).json({ error: err.message })
  }
})

// Control a device
app.post('/api/control', async (req, res) => {
  try {
    const { sku, device, capability } = req.body
    const response = await fetch(`${API_BASE}/router/api/v1/device/control`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        requestId: `control-${Date.now()}`,
        payload: { sku, device, capability }
      })
    })
    const data = await response.json()
    res.json(data)
  } catch (err) {
    console.error('Control failed:', err)
    res.status(500).json({ error: err.message })
  }
})

const PORT = 3001
app.listen(PORT, () => {
  console.log(`🚀 Govee API server running at http://localhost:${PORT}`)
})
