import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from '@testing-library/react'

const { WikiExplorer } = await import('../WikiExplorer')

function mockJsonResponse(data, { ok = true } = {}) {
  return { ok, json: async () => data }
}

function setupFetch({
  repos = [{ owner: 'acme', repo: 'widget' }],
  entries = [
    {
      id: '0001',
      issue: '10',
      topic: 'patterns',
      filename: '0001-issue-10-first-pattern.md',
      status: 'active',
      source_phase: 'plan',
      source_issue: '10',
      created_at: '2026-04-01T00:00:00Z',
    },
  ],
  entry = {
    id: '0001',
    topic: 'patterns',
    filename: '0001-issue-10-first-pattern.md',
    frontmatter: { id: '0001', topic: 'patterns', status: 'active' },
    body: '# First pattern\n\nBody content.',
  },
  status = {
    open_pr_url: 'https://github.com/x/y/pull/99',
    open_pr_branch: 'hydraflow/wiki-maint-abc',
    queue_depth: 2,
    interval_seconds: 3600,
    auto_merge: false,
    coalesce: true,
  },
  adminCapture,
} = {}) {
  global.fetch = vi.fn().mockImplementation((url, init) => {
    const u = String(url)
    const method = init?.method || 'GET'
    if (u === '/api/wiki/repos') {
      return Promise.resolve(mockJsonResponse(repos))
    }
    if (u.match(/\/api\/wiki\/repos\/[^/]+\/[^/]+\/entries\?/)) {
      return Promise.resolve(mockJsonResponse(entries))
    }
    if (u.match(/\/api\/wiki\/repos\/[^/]+\/[^/]+\/entries\/\d+$/)) {
      return Promise.resolve(mockJsonResponse(entry))
    }
    if (u === '/api/wiki/maintenance/status') {
      return Promise.resolve(mockJsonResponse(status))
    }
    if (u.startsWith('/api/wiki/admin/') && method === 'POST') {
      if (adminCapture) {
        adminCapture.push({ url: u, body: init?.body })
      }
      return Promise.resolve(mockJsonResponse({ status: 'queued' }))
    }
    return Promise.resolve(mockJsonResponse([]))
  })
}

beforeEach(() => {
  setupFetch()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('WikiExplorer', () => {
  it('auto-selects the first repo and renders its entries', async () => {
    render(<WikiExplorer />)
    await waitFor(() => {
      expect(
        screen.getByText('0001-issue-10-first-pattern.md'),
      ).toBeInTheDocument()
    })
  })

  it('selecting an entry loads and displays its body', async () => {
    render(<WikiExplorer />)
    const filename = await screen.findByText(
      '0001-issue-10-first-pattern.md',
    )
    fireEvent.click(filename)
    await waitFor(() => {
      expect(screen.getByText(/First pattern/)).toBeInTheDocument()
    })
  })

  it('topic filter requeries entries with the topic query param', async () => {
    render(<WikiExplorer />)
    await screen.findByText('0001-issue-10-first-pattern.md')

    global.fetch.mockClear()

    const topicSelect = screen.getByLabelText('Topic filter')
    fireEvent.change(topicSelect, { target: { value: 'gotchas' } })

    await waitFor(() => {
      const entriesCalls = global.fetch.mock.calls.filter(([u]) =>
        String(u).includes('/entries?'),
      )
      expect(entriesCalls.length).toBeGreaterThanOrEqual(1)
      const lastCall = entriesCalls[entriesCalls.length - 1]
      expect(String(lastCall[0])).toContain('topic=gotchas')
    })
  })

  it('mark-stale button fires the admin POST with the entry id', async () => {
    const captured = []
    setupFetch({ adminCapture: captured })

    render(<WikiExplorer />)
    fireEvent.click(
      await screen.findByText('0001-issue-10-first-pattern.md'),
    )
    await screen.findByText(/First pattern/)

    fireEvent.click(screen.getByRole('button', { name: /mark stale/i }))

    await waitFor(() => {
      expect(captured.length).toBeGreaterThanOrEqual(1)
    })
    const call = captured.find((c) => c.url.endsWith('/admin/mark-stale'))
    expect(call).toBeDefined()
    const body = JSON.parse(call.body)
    expect(body).toMatchObject({
      owner: 'acme',
      repo: 'widget',
      entry_id: '0001',
    })
  })

  it('maintenance panel renders the open PR link and queue depth', async () => {
    render(<WikiExplorer />)
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /pull\/99/ })
      expect(link.getAttribute('href')).toBe(
        'https://github.com/x/y/pull/99',
      )
    })
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('Run now button triggers the admin run-now POST', async () => {
    const captured = []
    setupFetch({ adminCapture: captured })

    render(<WikiExplorer />)
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /run now/i }),
      ).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /run now/i }))
    await waitFor(() => {
      expect(
        captured.some((c) => c.url.endsWith('/admin/run-now')),
      ).toBe(true)
    })
  })
})
