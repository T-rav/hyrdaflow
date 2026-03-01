import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EpicReleasedCard } from '../EpicReleasedCard'

const baseEpic = {
  epic_number: 100,
  title: 'Epic: Build dashboard',
  url: 'https://github.com/org/repo/issues/100',
  status: 'released',
  version: 'v1.2.0',
  released_at: new Date(Date.now() - 2 * 24 * 3600000).toISOString(), // 2 days ago
  merged_children: 4,
  total_children: 4,
  release_url: 'https://github.com/org/repo/releases/v1.2.0',
  changelog_url: 'https://github.com/org/repo/blob/main/CHANGELOG.md',
}

describe('EpicReleasedCard', () => {
  it('renders the released card with data-testid', () => {
    render(<EpicReleasedCard epic={baseEpic} />)
    expect(screen.getByTestId('released-card-100')).toBeInTheDocument()
  })

  it('shows the checkmark', () => {
    render(<EpicReleasedCard epic={baseEpic} />)
    expect(screen.getByText('✓')).toBeInTheDocument()
  })

  it('shows the epic title', () => {
    render(<EpicReleasedCard epic={baseEpic} />)
    expect(screen.getByText('Epic: Build dashboard')).toBeInTheDocument()
  })

  it('shows the epic number as a link', () => {
    render(<EpicReleasedCard epic={baseEpic} />)
    const link = screen.getByText('#100')
    expect(link.tagName).toBe('A')
    expect(link).toHaveAttribute('href', 'https://github.com/org/repo/issues/100')
  })

  it('shows the version', () => {
    render(<EpicReleasedCard epic={baseEpic} />)
    expect(screen.getByText(/Released v1\.2\.0/)).toBeInTheDocument()
  })

  it('shows relative time', () => {
    render(<EpicReleasedCard epic={baseEpic} />)
    expect(screen.getByText(/2 days ago/)).toBeInTheDocument()
  })

  it('shows PR count', () => {
    render(<EpicReleasedCard epic={baseEpic} />)
    expect(screen.getByText(/4 PRs merged/)).toBeInTheDocument()
  })

  it('shows singular PR for count 1', () => {
    const epic = { ...baseEpic, merged_children: 1 }
    render(<EpicReleasedCard epic={epic} />)
    expect(screen.getByText(/1 PR merged/)).toBeInTheDocument()
  })

  it('renders View Release link', () => {
    render(<EpicReleasedCard epic={baseEpic} />)
    const link = screen.getByTestId('view-release')
    expect(link).toHaveAttribute('href', 'https://github.com/org/repo/releases/v1.2.0')
  })

  it('renders View Changelog link', () => {
    render(<EpicReleasedCard epic={baseEpic} />)
    const link = screen.getByTestId('view-changelog')
    expect(link).toHaveAttribute('href', 'https://github.com/org/repo/blob/main/CHANGELOG.md')
  })

  it('hides View Release link when no release_url', () => {
    const epic = { ...baseEpic, release_url: null }
    render(<EpicReleasedCard epic={epic} />)
    expect(screen.queryByTestId('view-release')).not.toBeInTheDocument()
  })

  it('hides View Changelog link when no changelog_url', () => {
    const epic = { ...baseEpic, changelog_url: null }
    render(<EpicReleasedCard epic={epic} />)
    expect(screen.queryByTestId('view-changelog')).not.toBeInTheDocument()
  })

  it('handles missing version gracefully', () => {
    const epic = { ...baseEpic, version: '' }
    render(<EpicReleasedCard epic={epic} />)
    expect(screen.getByTestId('released-card-100')).toBeInTheDocument()
  })
})
