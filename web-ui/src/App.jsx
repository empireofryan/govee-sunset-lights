import { useState, useEffect, useRef, useCallback } from 'react'

const API_BASE = '/api'

function Panel({ label, children, className = '' }) {
  return (
    <div className={`panel ${className}`}>
      <span className="panel-label">{label}</span>
      <div className="panel-content">{children}</div>
    </div>
  )
}

function MiniColorWheel({ size = 60, onColorSelect }) {
  const canvasRef = useRef(null)
  const [isDragging, setIsDragging] = useState(false)

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    const center = size / 2, radius = size / 2 - 2
    for (let angle = 0; angle < 360; angle += 1) {
      const rad = (angle - 90) * Math.PI / 180
      ctx.beginPath()
      ctx.moveTo(center, center)
      ctx.arc(center, center, radius, rad, rad + 0.02)
      ctx.closePath()
      const gradient = ctx.createRadialGradient(center, center, 0, center, center, radius)
      gradient.addColorStop(0, '#fff')
      gradient.addColorStop(0.5, `hsl(${angle}, 100%, 50%)`)
      gradient.addColorStop(1, `hsl(${angle}, 100%, 20%)`)
      ctx.fillStyle = gradient
      ctx.fill()
    }
  }, [size])

  const pickColor = useCallback((e) => {
    const canvas = canvasRef.current
    const rect = canvas.getBoundingClientRect()
    const x = (e.clientX || e.touches?.[0]?.clientX) - rect.left
    const y = (e.clientY || e.touches?.[0]?.clientY) - rect.top
    const pixel = canvas.getContext('2d').getImageData(x, y, 1, 1).data
    if (pixel[3] > 0) onColorSelect([pixel[0], pixel[1], pixel[2]])
  }, [onColorSelect])

  return (
    <canvas ref={canvasRef} width={size} height={size}
      style={{ borderRadius: '50%', cursor: 'crosshair', flexShrink: 0 }}
      onMouseDown={(e) => { setIsDragging(true); pickColor(e) }}
      onMouseMove={(e) => isDragging && pickColor(e)}
      onMouseUp={() => setIsDragging(false)}
      onMouseLeave={() => setIsDragging(false)}
    />
  )
}

export default function App() {
  const [devices, setDevices] = useState([])
  const [deviceStates, setDeviceStates] = useState({})
  const [scenes, setScenes] = useState({})
  const [loading, setLoading] = useState(true)
  const [activeScene, setActiveScene] = useState(null)
  const [brightness, setBrightness] = useState(100)
  const [color, setColor] = useState([120, 200, 180])
  const [power, setPower] = useState(true)

  useEffect(() => {
    fetch(`${API_BASE}/devices`).then(r => r.json()).then(data => {
      setDevices(data.devices || [])
      setScenes(data.scenes || {})
      const states = {}
      ;(data.devices || []).forEach(d => {
        states[d.device] = { power: true, color: [120, 200, 180], scene: null }
      })
      setDeviceStates(states)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  const control = (device, cap) => fetch(`${API_BASE}/control`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sku: device.sku, device: device.device, capability: cap })
  })

  const toggleDevicePower = (device, on) => {
    control(device, { type: 'devices.capabilities.on_off', instance: 'powerSwitch', value: on ? 1 : 0 })
    setDeviceStates(s => ({ ...s, [device.device]: { ...s[device.device], power: on } }))
  }

  const setPowerAll = (on) => {
    setPower(on)
    devices.forEach(d => {
      control(d, { type: 'devices.capabilities.on_off', instance: 'powerSwitch', value: on ? 1 : 0 })
      setDeviceStates(s => ({ ...s, [d.device]: { ...s[d.device], power: on } }))
    })
  }

  const setBrightnessAll = (v) => {
    setBrightness(v)
    devices.forEach(d => control(d, { type: 'devices.capabilities.range', instance: 'brightness', value: v }))
  }

  const setColorAll = (rgb) => {
    setColor(rgb)
    setActiveScene(null)
    devices.forEach(d => {
      if (!deviceStates[d.device]?.power) control(d, { type: 'devices.capabilities.on_off', instance: 'powerSwitch', value: 1 })
      setTimeout(() => control(d, { type: 'devices.capabilities.color_setting', instance: 'colorRgb', value: (rgb[0] << 16) + (rgb[1] << 8) + rgb[2] }), 100)
      setDeviceStates(s => ({ ...s, [d.device]: { ...s[d.device], power: true, color: rgb, scene: null } }))
    })
    setPower(true)
  }

  const setSceneForDevices = (name, targetDevices) => {
    setActiveScene(name)
    targetDevices.forEach(d => {
      const scene = (scenes[d.device] || []).find(s => s.name === name)
      if (scene) {
        if (!deviceStates[d.device]?.power) control(d, { type: 'devices.capabilities.on_off', instance: 'powerSwitch', value: 1 })
        setTimeout(() => control(d, { type: 'devices.capabilities.dynamic_scene', instance: 'lightScene', value: scene.value }), 100)
        setDeviceStates(s => ({ ...s, [d.device]: { ...s[d.device], power: true, scene: name } }))
      }
    })
    setPower(true)
  }

  // Group scenes by device compatibility
  const groupScenesByDevice = () => {
    const deviceSceneSets = {}
    const allSceneNames = new Set()

    devices.forEach(d => {
      const deviceSceneNames = new Set((scenes[d.device] || []).map(s => s.name))
      deviceSceneSets[d.device] = deviceSceneNames
      deviceSceneNames.forEach(name => allSceneNames.add(name))
    })

    // Find scenes common to ALL devices
    const commonScenes = []
    const deviceSpecificScenes = {}

    allSceneNames.forEach(sceneName => {
      const devicesWithScene = devices.filter(d => deviceSceneSets[d.device]?.has(sceneName))

      if (devicesWithScene.length === devices.length) {
        commonScenes.push({ name: sceneName, devices: devices })
      } else {
        // Group by device type
        devicesWithScene.forEach(d => {
          const key = getDeviceCategory(d.deviceName)
          if (!deviceSpecificScenes[key]) deviceSpecificScenes[key] = []
          if (!deviceSpecificScenes[key].find(s => s.name === sceneName)) {
            deviceSpecificScenes[key].push({
              name: sceneName,
              devices: devicesWithScene.filter(dev => getDeviceCategory(dev.deviceName) === key)
            })
          }
        })
      }
    })

    return { commonScenes: commonScenes.sort((a,b) => a.name.localeCompare(b.name)), deviceSpecificScenes }
  }

  const getDeviceCategory = (name) => {
    const lower = name.toLowerCase()
    if (lower.includes('table')) return 'TABLE LAMP'
    if (lower.includes('uplighter') || lower.includes('projector')) return 'CEILING PROJECTOR'
    if (lower.includes('floor')) return 'FLOOR LAMPS'
    return 'OTHER'
  }

  const { commonScenes, deviceSpecificScenes } = groupScenesByDevice()
  const accent = `rgb(${color.join(',')})`
  const totalScenes = commonScenes.length + Object.values(deviceSpecificScenes).flat().length

  if (loading) return (
    <div className="loader"><div className="loader-text">INITIALIZING...</div></div>
  )

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        :root {
          --bg: #08080a;
          --border: rgba(255,255,255,0.08);
          --text: rgba(255,255,255,0.85);
          --text-muted: rgba(255,255,255,0.4);
          --accent: ${accent};
        }
        html, body, #root { height: 100%; width: 100%; overflow: hidden; }
        body { font-family: 'JetBrains Mono', monospace; background: var(--bg); color: var(--text); }

        .app {
          height: 100vh;
          padding: 12px;
          display: grid;
          grid-template-columns: 1fr 220px;
          grid-template-rows: auto 1fr auto;
          gap: 10px;
        }

        .panel { position: relative; border: 1px solid var(--border); border-radius: 12px; }
        .panel-label {
          position: absolute; top: -1px; left: 16px;
          transform: translateY(-50%);
          background: var(--bg); padding: 0 8px;
          font-size: 8px; font-weight: 600; letter-spacing: 0.12em; color: var(--text-muted);
        }
        .panel-content { padding: 12px; height: 100%; }

        .header {
          grid-column: 1 / -1;
          display: flex; align-items: center; justify-content: space-between;
          padding: 8px 0;
          border-bottom: 1px solid var(--border);
          font-size: 10px; font-weight: 600; letter-spacing: 0.2em;
        }
        .header-left { display: flex; align-items: center; gap: 8px; }
        .header-dot { width: 6px; height: 6px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 6px var(--accent); }
        .header-controls { display: flex; align-items: center; gap: 16px; }
        .header-control { display: flex; align-items: center; gap: 8px; font-size: 8px; color: var(--text-muted); }
        .header-control span { color: var(--accent); }

        /* Scenes area */
        .scenes-area { overflow: hidden; display: flex; flex-direction: column; gap: 8px; }
        .scenes-area .panel-content { display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
        .scenes-area .panel-content::-webkit-scrollbar { width: 3px; }
        .scenes-area .panel-content::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

        .scene-section { }
        .scene-section-header {
          font-size: 7px; font-weight: 600; letter-spacing: 0.1em; color: var(--text-muted);
          margin-bottom: 6px; display: flex; align-items: center; gap: 8px;
        }
        .scene-section-header::after {
          content: ''; flex: 1; height: 1px; background: var(--border);
        }
        .scene-section-count { color: var(--accent); }

        .scene-grid { display: flex; flex-wrap: wrap; gap: 4px; }
        .scene-btn {
          padding: 4px 8px;
          font-family: inherit; font-size: 8px;
          background: rgba(255,255,255,0.02);
          border: 1px solid transparent; border-radius: 3px;
          color: var(--text-muted); cursor: pointer; transition: all 0.15s;
        }
        .scene-btn:hover { background: rgba(255,255,255,0.05); color: var(--text); }
        .scene-btn.active {
          background: rgba(${color.join(',')}, 0.2);
          border-color: var(--accent); color: var(--accent);
        }

        /* Sidebar */
        .sidebar { display: flex; flex-direction: column; gap: 8px; }

        .devices-list { display: flex; flex-direction: column; gap: 6px; }
        .device-row {
          display: flex; align-items: center; gap: 8px;
          padding: 8px 10px;
          background: rgba(255,255,255,0.02);
          border-radius: 6px; border: 1px solid var(--border);
        }
        .device-indicator { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
        .device-indicator.on { box-shadow: 0 0 4px currentColor; }
        .device-info { flex: 1; min-width: 0; }
        .device-name { font-size: 8px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .device-status { font-size: 7px; color: var(--text-muted); margin-top: 1px; }
        .device-toggle {
          padding: 3px 6px; font-family: inherit; font-size: 7px;
          background: transparent; border: 1px solid var(--border);
          border-radius: 3px; color: var(--text-muted); cursor: pointer;
        }
        .device-toggle.on {
          background: rgba(${color.join(',')}, 0.15);
          border-color: var(--accent); color: var(--accent);
        }

        .controls-row { display: flex; gap: 6px; }
        .power-btn {
          flex: 1; padding: 10px;
          font-family: inherit; font-size: 9px; font-weight: 600; letter-spacing: 0.08em;
          background: transparent; border: 1px solid var(--border);
          border-radius: 6px; color: var(--text-muted); cursor: pointer; transition: all 0.2s;
        }
        .power-btn:hover { border-color: var(--text-muted); }
        .power-btn.active { border-color: var(--accent); color: var(--accent); background: rgba(${color.join(',')}, 0.1); }

        .brightness-row { display: flex; align-items: center; gap: 10px; }
        .brightness-value { font-size: 16px; font-weight: 700; color: var(--accent); min-width: 45px; }
        .brightness-bar { flex: 1; height: 4px; background: rgba(255,255,255,0.06); border-radius: 2px; cursor: pointer; }
        .brightness-fill { height: 100%; background: var(--accent); border-radius: 2px; }

        .color-row { display: flex; align-items: center; gap: 10px; }
        .color-swatch { width: 20px; height: 20px; border-radius: 4px; border: 1px solid var(--border); }
        .color-text { font-size: 8px; color: var(--text-muted); }
        .color-text span { color: var(--accent); }

        .footer {
          grid-column: 1 / -1;
          display: flex; justify-content: space-between;
          padding: 6px 0; border-top: 1px solid var(--border);
          font-size: 7px; color: var(--text-muted); letter-spacing: 0.05em;
        }
        .footer span { color: var(--accent); margin-left: 4px; }

        .loader { height: 100vh; display: flex; align-items: center; justify-content: center; background: var(--bg); }
        .loader-text { font-size: 9px; letter-spacing: 0.2em; color: var(--text-muted); animation: blink 1s infinite; }
        @keyframes blink { 0%, 50% { opacity: 1; } 51%, 100% { opacity: 0.3; } }
      `}</style>

      <div className="app">
        <header className="header">
          <div className="header-left">
            <div className="header-dot" />
            GOVEE CONTROL
          </div>
          <div className="header-controls">
            <div className="header-control">BRIGHT <span>{brightness}%</span></div>
            <div className="header-control">RGB <span>{color.join(' ')}</span></div>
            <div className="header-control">ACTIVE <span>{activeScene || 'NONE'}</span></div>
          </div>
        </header>

        <Panel label="SCENES" className="scenes-area">
          {/* Common scenes */}
          {commonScenes.length > 0 && (
            <div className="scene-section">
              <div className="scene-section-header">
                ALL DEVICES <span className="scene-section-count">{commonScenes.length}</span>
              </div>
              <div className="scene-grid">
                {commonScenes.map(s => (
                  <button key={s.name}
                    className={`scene-btn ${activeScene === s.name ? 'active' : ''}`}
                    onClick={() => setSceneForDevices(s.name, s.devices)}
                  >{s.name}</button>
                ))}
              </div>
            </div>
          )}

          {/* Device-specific scenes */}
          {Object.entries(deviceSpecificScenes).map(([category, categoryScenes]) => (
            <div key={category} className="scene-section">
              <div className="scene-section-header">
                {category} <span className="scene-section-count">{categoryScenes.length}</span>
              </div>
              <div className="scene-grid">
                {categoryScenes.sort((a,b) => a.name.localeCompare(b.name)).map(s => (
                  <button key={s.name}
                    className={`scene-btn ${activeScene === s.name ? 'active' : ''}`}
                    onClick={() => setSceneForDevices(s.name, s.devices)}
                  >{s.name}</button>
                ))}
              </div>
            </div>
          ))}
        </Panel>

        <div className="sidebar">
          <Panel label="DEVICES">
            <div className="devices-list">
              {devices.map(d => {
                const state = deviceStates[d.device] || { power: false, color: [100,100,100], scene: null }
                const deviceColor = state.power ? `rgb(${state.color.join(',')})` : '#333'
                return (
                  <div key={d.device} className="device-row">
                    <div className={`device-indicator ${state.power ? 'on' : ''}`}
                      style={{ background: deviceColor, color: deviceColor }} />
                    <div className="device-info">
                      <div className="device-name">{d.deviceName}</div>
                      <div className="device-status">{state.power ? (state.scene || 'COLOR') : 'OFF'}</div>
                    </div>
                    <button className={`device-toggle ${state.power ? 'on' : ''}`}
                      onClick={() => toggleDevicePower(d, !state.power)}>
                      {state.power ? 'ON' : 'OFF'}
                    </button>
                  </div>
                )
              })}
            </div>
          </Panel>

          <Panel label="POWER">
            <div className="controls-row">
              <button className={`power-btn ${power ? 'active' : ''}`} onClick={() => setPowerAll(true)}>ON</button>
              <button className={`power-btn ${!power ? 'active' : ''}`} onClick={() => setPowerAll(false)}>OFF</button>
            </div>
          </Panel>

          <Panel label="BRIGHTNESS">
            <div className="brightness-row">
              <span className="brightness-value">{brightness}%</span>
              <div className="brightness-bar" onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect()
                setBrightnessAll(Math.max(1, Math.round((e.clientX - rect.left) / rect.width * 100)))
              }}>
                <div className="brightness-fill" style={{ width: `${brightness}%` }} />
              </div>
            </div>
          </Panel>

          <Panel label="COLOR">
            <div className="color-row">
              <MiniColorWheel size={50} onColorSelect={setColorAll} />
              <div className="color-swatch" style={{ background: accent }} />
              <div className="color-text"><span>{color[0]}</span> <span>{color[1]}</span> <span>{color[2]}</span></div>
            </div>
          </Panel>
        </div>

        <footer className="footer">
          <div>DEVICES<span>{devices.length}</span> · SCENES<span>{totalScenes}</span></div>
          <div>GOVEE API v1</div>
        </footer>
      </div>
    </>
  )
}
