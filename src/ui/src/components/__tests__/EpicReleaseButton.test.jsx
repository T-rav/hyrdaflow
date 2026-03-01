import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { EpicReleaseButton } from '../EpicReleaseButton'

const readyEpic = {
  epic_number: 100,
  merge_strategy: 'bundled_hitl',
  total_children: 3,
  children: [],
  readiness: {
    all_implemented: true,
    all_approved: true,
    ci_passing: true,
    no_conflicts: true,
    changelog_generated: true,
    version_determined: true,
    approved_count: 3,
    total_count: 3,
    version: '1.2.0',
  },
}

const notReadyEpic = {
  epic_number: 101,
  merge_strategy: 'bundled',
  total_children: 3,
  children: [],
  readiness: {
    all_implemented: false,
    all_approved: false,
    ci_passing: false,
    no_conflicts: true,
    changelog_generated: false,
    version_determined: false,
  },
}

describe('EpicReleaseButton', () => {
  it('renders the release button', () => {
    render(<EpicReleaseButton epic={readyEpic} onRelease={vi.fn()} releasing={null} />)
    expect(screen.getByTestId('release-button')).toBeInTheDocument()
  })

  it('shows "Merge & Release" for bundled_hitl strategy', () => {
    render(<EpicReleaseButton epic={readyEpic} onRelease={vi.fn()} releasing={null} />)
    expect(screen.getByText('Merge & Release')).toBeInTheDocument()
  })

  it('shows "Auto Merge & Release" for bundled strategy', () => {
    const epic = { ...readyEpic, merge_strategy: 'bundled' }
    render(<EpicReleaseButton epic={epic} onRelease={vi.fn()} releasing={null} />)
    expect(screen.getByText('Auto Merge & Release')).toBeInTheDocument()
  })

  it('button is enabled when all checks pass', () => {
    render(<EpicReleaseButton epic={readyEpic} onRelease={vi.fn()} releasing={null} />)
    const btn = screen.getByTestId('release-trigger')
    expect(btn).toHaveAttribute('tabIndex', '0')
  })

  it('button is disabled when checks are not passing', () => {
    render(<EpicReleaseButton epic={notReadyEpic} onRelease={vi.fn()} releasing={null} />)
    const btn = screen.getByTestId('release-trigger')
    expect(btn).toHaveAttribute('tabIndex', '-1')
  })

  it('clicking enabled button shows confirmation dialog', () => {
    render(<EpicReleaseButton epic={readyEpic} onRelease={vi.fn()} releasing={null} />)
    fireEvent.click(screen.getByTestId('release-trigger'))
    expect(screen.getByTestId('release-confirm')).toBeInTheDocument()
    expect(screen.getByText(/Merge 3 PRs and create release/)).toBeInTheDocument()
  })

  it('confirmation dialog shows version', () => {
    render(<EpicReleaseButton epic={readyEpic} onRelease={vi.fn()} releasing={null} />)
    fireEvent.click(screen.getByTestId('release-trigger'))
    expect(screen.getByText(/v1\.2\.0/)).toBeInTheDocument()
  })

  it('cancel button hides confirmation dialog', () => {
    render(<EpicReleaseButton epic={readyEpic} onRelease={vi.fn()} releasing={null} />)
    fireEvent.click(screen.getByTestId('release-trigger'))
    fireEvent.click(screen.getByTestId('release-confirm-no'))
    expect(screen.queryByTestId('release-confirm')).not.toBeInTheDocument()
  })

  it('confirm button calls onRelease', async () => {
    const onRelease = vi.fn().mockResolvedValue({ ok: true, version: '1.2.0' })
    render(<EpicReleaseButton epic={readyEpic} onRelease={onRelease} releasing={null} />)
    fireEvent.click(screen.getByTestId('release-trigger'))
    fireEvent.click(screen.getByTestId('release-confirm-yes'))
    await waitFor(() => expect(onRelease).toHaveBeenCalledWith(100))
  })

  it('shows error message on release failure', async () => {
    const onRelease = vi.fn().mockResolvedValue({ ok: false, error: 'Merge conflict' })
    render(<EpicReleaseButton epic={readyEpic} onRelease={onRelease} releasing={null} />)
    fireEvent.click(screen.getByTestId('release-trigger'))
    fireEvent.click(screen.getByTestId('release-confirm-yes'))
    await waitFor(() => expect(screen.getByTestId('release-error')).toBeInTheDocument())
    expect(screen.getByText('Merge conflict')).toBeInTheDocument()
  })

  it('shows releasing state with progress', () => {
    const releasing = { epicNumber: 100, progress: 2, total: 5 }
    render(<EpicReleaseButton epic={readyEpic} onRelease={vi.fn()} releasing={releasing} />)
    expect(screen.getByText('Releasing...')).toBeInTheDocument()
    expect(screen.getByText('2/5')).toBeInTheDocument()
  })

  it('does not show releasing state for different epic', () => {
    const releasing = { epicNumber: 999, progress: 1, total: 3 }
    render(<EpicReleaseButton epic={readyEpic} onRelease={vi.fn()} releasing={releasing} />)
    expect(screen.queryByText('Releasing...')).not.toBeInTheDocument()
  })

  it('disabled button does not open confirm on click', () => {
    render(<EpicReleaseButton epic={notReadyEpic} onRelease={vi.fn()} releasing={null} />)
    fireEvent.click(screen.getByTestId('release-trigger'))
    expect(screen.queryByTestId('release-confirm')).not.toBeInTheDocument()
  })
})
