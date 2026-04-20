import { test, expect } from '@playwright/test'
import { seedState } from './fixtures/seed-state.js'

/**
 * Playwright interaction tests — exercises user-visible UI flows using the
 * same seed-state injection pattern as screenshots.spec.js.
 *
 * No live backend required: all API/WebSocket routes are stubbed and state
 * is injected via window.__HYDRAFLOW_SEED_STATE__ before React mounts.
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

/**
 * Stub API routes and inject seed state — mirrors setupPage() from
 * screenshots.spec.js so both suites behave identically.
 */
async function setup(page, stateOverrides = {}) {
  await page.clock.install({ time: new Date('2026-01-01T00:00:00.000Z') })

  await page.route('**/api/**', (route) => {
    const url = route.request().url()
    if (url.includes('/api/control/status')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'running' }) })
    }
    if (url.includes('/api/hitl')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    if (url.includes('/api/memory/banks')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          banks: [
            { id: 'hydraflow-retrospectives', name: 'Retrospectives' },
            { id: 'hydraflow-review-insights', name: 'Review Insights' },
            { id: 'hydraflow-troubleshooting', name: 'Troubleshooting' },
            { id: 'hydraflow-tribal', name: 'Tribal Learnings' },
          ],
        }),
      })
    }
    // Stub issue/pr memory endpoints used by MemoryRelatedPanel
    if (url.includes('/api/memory/issue/') || url.includes('/api/memory/pr/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [{ bank: 'hydraflow-tribal', content: 'Related learning for this issue.' }] }),
      })
    }
    if (url.includes('/api/pipeline/stats')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
    if (url.includes('/api/pipeline')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ stages: {} }) })
    }
    if (url.includes('/api/sessions')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    if (url.includes('/api/repos')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ repos: [] }) })
    }
    if (url.includes('/api/system/workers')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ workers: [] }) })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  // Block WebSocket upgrade — seed state replaces live data
  await page.route('**/ws', (route) => route.abort())

  await page.addInitScript((seedData) => {
    window.__HYDRAFLOW_SEED_STATE__ = seedData
  }, { ...seedState, ...stateOverrides })

  await page.addInitScript((css) => {
    const style = document.createElement('style')
    style.textContent = css
    ;(document.head || document.documentElement).appendChild(style)
  }, DISABLE_ANIMATIONS_CSS)

  await page.goto('/')
  await page.waitForSelector('[data-testid="main-tabs"]', { timeout: 10_000 })
}

/** Click a top-level tab (same helper as screenshots.spec.js). */
async function switchTab(page, tabLabel) {
  const tabBar = page.locator('[data-testid="main-tabs"]')
  const tab = tabBar.locator('[role="tab"]').filter({ hasText: tabLabel })
  await tab.click()
  await expect(tab).toHaveAttribute('aria-selected', 'true')
}

// ---------------------------------------------------------------------------
// UI-1: HITL row expand — click a row, assert detail panel appears
// ---------------------------------------------------------------------------

test('UI-1: expanding an HITL row reveals the detail panel', async ({ page }) => {
  // Seed includes two hitlItems (issues 208 and 209) and orchestratorStatus running
  await setup(page)
  await switchTab(page, 'HITL')

  // The first seeded HITL item is issue 208 — click its row
  const row = page.locator('[data-testid="hitl-row-208"]')
  await expect(row).toBeVisible({ timeout: 5_000 })
  await row.click()

  // Detail panel for issue 208 should now be visible
  const detail = page.locator('[data-testid="hitl-detail-208"]')
  await expect(detail).toBeVisible({ timeout: 5_000 })

  // The textarea for correction guidance should also be present
  const textarea = page.locator('[data-testid="hitl-textarea-208"]')
  await expect(textarea).toBeVisible()
})

// ---------------------------------------------------------------------------
// UI-2: System → Memory subtab becomes active
// ---------------------------------------------------------------------------

test('UI-2: clicking the Memory subtab in System renders the MemoryExplorer', async ({ page }) => {
  // Seed with retrospective data so the section list has content
  await setup(page, {
    retrospectives: {
      total_entries: 1,
      avg_plan_accuracy: 82,
      avg_quality_fix_rounds: 1.2,
      avg_ci_fix_rounds: 0.8,
      reviewer_fix_rate: 0.15,
      entries: [{ issue_number: 204, pr_number: 301, plan_accuracy_pct: 82, review_verdict: 'approved' }],
    },
  })

  await switchTab(page, 'System')

  // Click the Memory sub-tab in the System sidebar
  const memorySubTab = page.locator('[data-testid="system-subtab-memory"]')
  await expect(memorySubTab).toBeVisible({ timeout: 5_000 })
  await memorySubTab.click()
  await expect(memorySubTab).toHaveAttribute('aria-selected', 'true')

  // The MemoryExplorer root should now be visible
  const explorer = page.locator('[data-testid="memory-explorer"]')
  await expect(explorer).toBeVisible({ timeout: 5_000 })

  // The search input inside MemoryTopBar should be present
  const searchInput = page.locator('[data-testid="memory-search-input"]')
  await expect(searchInput).toBeVisible()
})

// ---------------------------------------------------------------------------
// UI-3: Memory search filters visible content
// ---------------------------------------------------------------------------

test('UI-3: typing in the memory search box updates the displayed sections', async ({ page }) => {
  const tribalLearning = 'always run quality gate before committing'
  await setup(page, {
    memories: {
      total_items: 2,
      items: [
        { issue_number: 204, learning: tribalLearning },
        { issue_number: 205, learning: 'prefer small focused commits' },
      ],
    },
  })

  await switchTab(page, 'System')

  const memorySubTab = page.locator('[data-testid="system-subtab-memory"]')
  await memorySubTab.click()
  await expect(memorySubTab).toHaveAttribute('aria-selected', 'true')

  const searchInput = page.locator('[data-testid="memory-search-input"]')
  await expect(searchInput).toBeVisible({ timeout: 5_000 })

  // Type a query that matches only the first tribal learning
  await searchInput.fill('quality gate')

  // The Tribal Learnings section should still be visible (it contains a match)
  // We verify the MemoryExplorer is still rendered (sections stay mounted but filter)
  const explorer = page.locator('[data-testid="memory-explorer"]')
  await expect(explorer).toBeVisible()

  // The text of the matching learning should appear in the DOM
  await expect(page.getByText(tribalLearning)).toBeVisible({ timeout: 5_000 })

  // After filtering, entries that don't match "quality gate" must be hidden.
  // "prefer small focused commits" is the second entry in the seeded memories
  // above (issue_number: 205) and does not contain "quality gate".
  await expect(page.getByText(/prefer small focused commits/i)).not.toBeVisible()
})

// ---------------------------------------------------------------------------
// UI-4: Worker group section collapses and re-expands on click
// ---------------------------------------------------------------------------

test('UI-4: clicking a worker group header toggles its collapsed state', async ({ page }) => {
  await setup(page)
  await switchTab(page, 'System')

  // Workers subtab is default; the first group header should be present.
  // data-testid="group-header-{group.key}" — find any one.
  const groupHeaders = page.locator('[data-testid^="group-header-"]')
  const firstHeader = groupHeaders.first()
  await expect(firstHeader).toBeVisible({ timeout: 5_000 })

  // A worker card inside the group should be visible before collapsing.
  const workerCards = page.locator('[data-testid^="worker-card-"]')
  const initialCount = await workerCards.count()
  expect(initialCount).toBeGreaterThan(0)

  // Click the header to collapse the group.
  await firstHeader.click()

  // After collapse the worker cards inside that group disappear; wait briefly for DOM update.
  await page.waitForTimeout(150)

  // There should now be fewer visible worker cards than before.
  const collapsedCount = await workerCards.count()
  expect(collapsedCount).toBeLessThan(initialCount)

  // Click again to re-expand.
  await firstHeader.click()
  await page.waitForTimeout(150)

  const reexpandedCount = await workerCards.count()
  expect(reexpandedCount).toBe(initialCount)
})
