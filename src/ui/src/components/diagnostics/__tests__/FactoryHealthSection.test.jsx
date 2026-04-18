import { render } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { FactoryHealthSection } from '../FactoryHealthSection'

describe('FactoryHealthSection', () => {
  let originalFetch
  beforeEach(() => {
    originalFetch = global.fetch
  })
  afterEach(() => {
    global.fetch = originalFetch
  })

  it('renders nothing (does not throw) when API returns a truthy response without rolling_averages', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    })
    const { container } = render(<FactoryHealthSection />)
    // Wait one microtask for the fetch promise + setData re-render to settle.
    await new Promise(resolve => setTimeout(resolve, 0))
    // Component must not throw. It should render nothing (loading disappears, no data shape → null).
    // A narrow behavioural assertion: no "Factory Health Trends" heading, no crash.
    expect(container.textContent).not.toMatch(/Factory Health Trends/)
  })
})
