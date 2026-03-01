import { test, expect } from '@playwright/test'
import { seedState, seedStateEmpty } from './fixtures/seed-state.js'

/**
 * Deterministic screenshot capture harness.
 *
 * Injects seed state via `window.__HYDRAFLOW_SEED_STATE__` so the app renders
 * without a live backend.  All API/WebSocket requests are intercepted and
 * returned with empty/stubbed responses to prevent flaky network errors.
 *
 * Animations and transitions are disabled via a global stylesheet injected on
 * every page load.
 */

const DISABLE_ANIMATIONS_CSS = `
  *, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    caret-color: transparent !important;
  }
`

const TAB_KEYS = ['issues', 'outcomes', 'hitl', 'worklog', 'system']
const SYSTEM_SUBTABS = ['workers', 'pipeline', 'metrics', 'insights', 'livestream']

/**
 * Stub all API routes so the app can render with seed state only.
 */
async function stubApiRoutes(page) {
  await page.route('**/api/**', (route) => {
    const url = route.request().url()
    if (url.includes('/api/control/status')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'running' }) })
    }
    if (url.includes('/api/prs')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    if (url.includes('/api/hitl')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    if (url.includes('/api/pipeline/stats')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
    if (url.includes('/api/pipeline')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ stages: {} }) })
    }
    if (url.includes('/api/human-input')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
    if (url.includes('/api/sessions')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    if (url.includes('/api/repos')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ repos: [] }) })
    }
    if (url.includes('/api/runtimes')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ runtimes: [] }) })
    }
    if (url.includes('/api/metrics')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
    if (url.includes('/api/epics')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    if (url.includes('/api/stats')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
    if (url.includes('/api/system/workers')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ workers: [] }) })
    }
    if (url.includes('/api/queue')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  // Block WebSocket upgrade — seed state replaces live data
  await page.route('**/ws', (route) => route.abort())
}

/**
 * Inject seed state and disable animations before navigating.
 *
 * Animation-suppression CSS is injected via `addInitScript` so it takes
 * effect before React's first paint, eliminating any animation frames that
 * could produce non-deterministic pixels.
 */
async function setupPage(page, state) {
  await stubApiRoutes(page)

  await page.addInitScript((seedData) => {
    window.__HYDRAFLOW_SEED_STATE__ = seedData
  }, state)

  await page.addInitScript((css) => {
    const style = document.createElement('style')
    style.textContent = css
    ;(document.head || document.documentElement).appendChild(style)
  }, DISABLE_ANIMATIONS_CSS)

  await page.goto('/')
  await page.waitForSelector('[data-testid="main-tabs"]', { timeout: 10_000 })
}

/**
 * Click a top-level tab by its key and wait for the tab to become active.
 */
async function switchTab(page, tabKey) {
  const tabBar = page.locator('[data-testid="main-tabs"]')
  const tab = tabBar.locator(`[role="tab"]`).filter({ hasText: getTabLabel(tabKey) })
  await tab.click()
  await expect(tab).toHaveAttribute('aria-selected', 'true')
}

function getTabLabel(key) {
  const labels = {
    issues: 'Work Stream',
    outcomes: 'Outcomes',
    hitl: 'HITL',
    worklog: 'Work Log',
    system: 'System',
  }
  return labels[key] || key
}

// ---------------------------------------------------------------------------
// Populated pipeline screenshots
// ---------------------------------------------------------------------------

test.describe('populated pipeline', () => {
  test.beforeEach(async ({ page }) => {
    await setupPage(page, seedState)
  })

  for (const tab of TAB_KEYS) {
    test(`tab: ${tab}`, async ({ page }) => {
      await switchTab(page, tab)
      // Allow content to settle
      await page.waitForTimeout(300)
      await expect(page).toHaveScreenshot(`populated-${tab}.png`, {
        fullPage: false,
        animations: 'disabled',
      })
    })
  }

  test.describe('system sub-tabs', () => {
    for (const subtab of SYSTEM_SUBTABS) {
      test(`subtab: ${subtab}`, async ({ page }) => {
        await switchTab(page, 'system')
        // Click the system sub-tab
        const subtabButton = page.locator(`[data-testid="system-subtab-${subtab}"]`)
        await subtabButton.click()
        await expect(subtabButton).toHaveAttribute('aria-selected', 'true')
        await page.waitForTimeout(300)
        await expect(page).toHaveScreenshot(`populated-system-${subtab}.png`, {
          fullPage: false,
          animations: 'disabled',
        })
      })
    }
  })
})

// ---------------------------------------------------------------------------
// Empty / idle state screenshots
// ---------------------------------------------------------------------------

test.describe('empty pipeline', () => {
  test.beforeEach(async ({ page }) => {
    await setupPage(page, seedStateEmpty)
  })

  for (const tab of TAB_KEYS) {
    test(`tab: ${tab}`, async ({ page }) => {
      await switchTab(page, tab)
      await page.waitForTimeout(300)
      await expect(page).toHaveScreenshot(`empty-${tab}.png`, {
        fullPage: false,
        animations: 'disabled',
      })
    })
  }
})
