import { chromium } from 'playwright'

async function takeScreenshot() {
  console.log('Launching browser...')
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

  console.log('Loading page...')
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle', timeout: 30000 })

  // Wait for content to load
  await page.waitForSelector('.app', { timeout: 10000 })
  await page.waitForTimeout(2000) // Extra time for API data

  const filename = `screenshot-${Date.now()}.png`
  await page.screenshot({ path: filename })
  console.log(`Screenshot saved: ${filename}`)

  await browser.close()
  return filename
}

takeScreenshot().catch(console.error)
