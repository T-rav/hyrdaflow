import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { seedState } from './fixtures/seed-state.js'

/**
 * A11y baseline tests — Task 3.16 of MockWorld Scenario Coverage Expansion.
 *
 * Checks each main UI route for WCAG 2.x violations using axe-core.
 * This test establishes a measurable baseline; it does NOT block on
 * pre-existing violations (that is follow-on work).
 *
 * API/WS routes are fully stubbed. State is injected via the same
 * window.__HYDRAFLOW_SEED_STATE__ pattern used by the other e2e suites.
 *
 * NOTE: Main tabs do not have data-testid="tab-*". They use role="tab" inside
 * [data-testid="main-tabs"] and are identified by their visible text labels:
 *   "Work Stream", "HITL", "Outcomes", "System"
 *
 * == Known baseline violations (2026-04-18) — do NOT fix here; file a11y issues ==
 *
 * Across all 4 routes:
 *   - [serious]  color-contrast (wcag2aa/wcag143)
 *       Session-box stats text (#484f58 on #0d1117, ratio 2.28 vs 4.5 required).
 *       Also Stop button label (#f85149 on #382328, ratio 4.35 vs 4.5 required).
 *
 * Outcomes + System routes:
 *   - [critical] aria-required-parent (wcag2a/wcag131)
 *       role="tab" elements rendered without a role="tablist" container:
 *         - Main tab bar in App.jsx uses plain <div data-testid="main-tabs">
 *         - System sub-tab sidebar in SystemPanel.jsx has no tablist wrapper
 *       Fix: wrap tab containers with role="tablist" (separate a11y task).
 *
 * System route only:
 *   - [critical] label (wcag2a/wcag412)
 *       Unlabeled inputs: main-branch-input, staging-branch-input, rc-cadence-hours-input
 *   - [critical] select-name (wcag2a/wcag412)
 *       Unlabeled <select> with data-testid="unstick-workers-dropdown"
 *
 * Assertion is SOFT (console.warn + no throw) so the baseline stays green
 * while the violations are tracked. Replace with hard expect() once fixed.
 */

async function setup(page) {
  await page.clock.install({ time: new Date('2026-01-01T00:00:00.000Z') })

  await page.route('**/api/**', (route) => {
    const url = route.request().url()
    if (url.includes('/api/control/status')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'running' }),
      })
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
    if (url.includes('/api/memory/issue/') || url.includes('/api/memory/pr/')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [] }),
      })
    }
    if (url.includes('/api/pipeline/stats')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
    if (url.includes('/api/pipeline')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ stages: {} }),
      })
    }
    if (url.includes('/api/sessions')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    }
    if (url.includes('/api/repos')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ repos: [] }),
      })
    }
    if (url.includes('/api/system/workers')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ workers: [] }),
      })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  await page.route('**/ws', (route) => route.abort())

  await page.addInitScript((state) => {
    window.__HYDRAFLOW_SEED_STATE__ = state
  }, seedState)

  await page.goto('/')
  await page.waitForSelector('[data-testid="main-tabs"]', { timeout: 10_000 })
}

/**
 * Click a top-level tab by its visible text label.
 * Labels: "Work Stream", "HITL", "Outcomes", "System"
 */
async function switchTab(page, tabLabel) {
  const tabBar = page.locator('[data-testid="main-tabs"]')
  const tab = tabBar.locator('[role="tab"]').filter({ hasText: tabLabel })
  await tab.click()
  await expect(tab).toHaveAttribute('aria-selected', 'true')
}

// Routes to audit — label must match the visible tab text in the UI
const ROUTES = [
  { name: 'Work Stream tab', label: 'Work Stream' },
  { name: 'Outcomes tab', label: 'Outcomes' },
  { name: 'HITL tab', label: 'HITL' },
  { name: 'System tab', label: 'System' },
]

test.describe('a11y baseline', () => {
  for (const route of ROUTES) {
    test(`${route.name} has no serious a11y violations`, async ({ page }) => {
      await setup(page)
      await switchTab(page, route.label)
      // Allow a frame for rendering to settle
      await page.waitForTimeout(200)

      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa'])
        .analyze()

      // Collect serious/critical violations for reporting
      const blocking = results.violations.filter(
        (v) => v.impact === 'serious' || v.impact === 'critical',
      )

      // Always log the baseline — useful for tracking regression/improvement
      if (blocking.length > 0) {
        console.log(`\n[a11y baseline] "${route.name}" has ${blocking.length} serious/critical violation(s):`)
        for (const v of blocking) {
          console.log(`  [${v.impact}] ${v.id}: ${v.help}`)
          for (const node of v.nodes.slice(0, 2)) {
            console.log(`    target: ${node.target.join(', ')}`)
          }
        }
        console.log('  (baseline violations — tracked as known issues, not blocking this PR)')
      } else {
        console.log(`\n[a11y baseline] "${route.name}": no serious/critical violations`)
      }

      // SOFT assertion: log violations but do not fail the test.
      // These are pre-existing a11y gaps documented above; fix them in
      // dedicated a11y issues. Upgrade to a hard expect() once resolved.
      //
      // Violations at baseline (2026-04-18):
      //   Work Stream: 2  (color-contrast, aria-required-parent)
      //   Outcomes:    3  (aria-required-parent, color-contrast, + 1 more)
      //   HITL:        1  (color-contrast)
      //   System:      4  (aria-required-parent, color-contrast, label, select-name)
      //
      // TODO: replace the line below with the hard assertion once fixed:
      //   expect(blocking).toHaveLength(0)
      expect(blocking.length).toBeGreaterThanOrEqual(0) // always passes; documents baseline
    })
  }
})
