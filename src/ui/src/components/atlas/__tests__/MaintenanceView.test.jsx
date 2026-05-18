import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MaintenanceView } from '../MaintenanceView'

const STATUS = {
  open_pr_url: 'https://github.com/acme/widget/pull/9012',
  open_pr_branch: 'wiki/foo',
  queue_depth: 3,
  queue_path: '/tmp/q',
  interval_seconds: 3600,
  auto_merge: false,
  coalesce: true,
}
const HEALTH = { store: 'populated', repos: 7, tribal: 'populated' }

beforeEach(() => {
  global.fetch = vi.fn((url, opts) => {
    if (url === '/api/wiki/maintenance/status')
      return Promise.resolve({ ok: true, json: () => Promise.resolve(STATUS) })
    if (url === '/api/wiki/health')
      return Promise.resolve({ ok: true, json: () => Promise.resolve(HEALTH) })
    if (url.startsWith('/api/wiki/admin/') && opts && opts.method === 'POST')
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: 'queued' }),
      })
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
  })
})

describe('MaintenanceView', () => {
  it('renders run-status card with queue depth and interval', async () => {
    render(<MaintenanceView />)
    await waitFor(() => expect(screen.getByText('3')).toBeInTheDocument())
    expect(screen.getByText(/3600s/)).toBeInTheDocument()
  })

  it('renders the open-PR link when present', async () => {
    render(<MaintenanceView />)
    await waitFor(() => screen.getByRole('link'))
    const link = screen.getByRole('link')
    expect(link.getAttribute('href')).toBe(STATUS.open_pr_url)
  })

  it('renders health card with store + tribal status', async () => {
    render(<MaintenanceView />)
    await waitFor(() => screen.getAllByText(/populated/i).length > 0)
    expect(screen.getByText(/7 repos/i)).toBeInTheDocument()
  })

  it('posts to /api/wiki/admin/run-now when Run now is clicked', async () => {
    render(<MaintenanceView />)
    await waitFor(() => screen.getByRole('button', { name: /run now/i }))
    fireEvent.click(screen.getByRole('button', { name: /run now/i }))
    await waitFor(() => {
      const calls = global.fetch.mock.calls.map((c) => c[0])
      expect(calls).toContain('/api/wiki/admin/run-now')
    })
  })
})
