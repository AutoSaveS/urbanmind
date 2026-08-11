/* Records the backend demo session with Playwright's native video capture.
   Requires: npm i playwright && npx playwright install chromium-headless-shell
   Start demo/serve_demo.py first, then: node demo/record_video.mjs */

import { chromium } from 'playwright';

const OUT_DIR = 'demo_recording';
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  recordVideo: { dir: OUT_DIR, size: { width: 1280, height: 800 } },
});
const page = await context.newPage();

await page.goto('http://127.0.0.1:8787/', { waitUntil: 'networkidle' });
await page.waitForTimeout(3000);

// Smoothly drag a range input, firing real input events step by step.
async function drag(id, from, to, steps, msPerStep) {
  for (let i = 1; i <= steps; i++) {
    const v = from + ((to - from) * i) / steps;
    await page.locator('#' + id).evaluate((el, val) => {
      el.value = val;
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }, v.toFixed(2));
    await page.waitForTimeout(msPerStep);
  }
}

// Scene 1: greening intervention (canopy up) — thermal & air fields cool down.
await drag('canopy', 0, 0.25, 10, 350);
await page.waitForTimeout(4000);

// Scene 2: cool roof (albedo up) — energy & thermal respond.
await drag('albedo', 0, 0.35, 10, 350);
await page.waitForTimeout(4000);

// Scene 3: dial canopy back down, showing reversibility + fresh log lines.
await drag('canopy', 0.25, 0.05, 8, 300);
await page.waitForTimeout(5000);

await context.close();  // flushes the video file
await browser.close();
console.log('video written to', OUT_DIR);
