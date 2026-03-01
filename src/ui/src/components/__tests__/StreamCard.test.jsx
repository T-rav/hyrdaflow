import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import {
  StreamCard,
  StatusDot,
  dotStyles,
  badgeStyleMap,
  cardActiveStyleMap,
  cardInactiveStyleMap,
  activeDotStyleMap,
} from '../StreamCard'
import { theme } from '../../theme'
import { STAGE_KEYS, STAGE_META } from '../../hooks/useTimeline'

function makeIssue(overrides = {}) {
  const stages = {}
  for (const key of STAGE_KEYS) {
    stages[key] = { status: 'pending', startTime: null, endTime: null, transcript: [] }
  }
  stages.review = { status: 'active', startTime: '2026-01-01T00:00:00Z', endTime: null, transcript: [] }
  return {
    issueNumber: 42,
    title: 'Fix the frobnicator',
    issueUrl: null,
    currentStage: 'review',
    overallStatus: 'active',
    startTime: '2026-01-01T00:00:00Z',
    endTime: null,
    pr: null,
    branch: 'agent/issue-42',
    stages,
    ...overrides,
  }
}

describe('StatusDot component', () => {
  it('renders a pulsing dot for active status', () => {
    const { container } = render(<StatusDot status="active" />)
    const el = container.firstChild
    expect(el.tagName).toBe('SPAN')
    expect(el.style.animation).toContain('stream-pulse')
    expect(el.style.background).toBe(theme.accent)
  })

  it('uses phase color for active status when stageKey is provided', () => {
    const { container } = render(<StatusDot status="active" stageKey="implement" />)
    const el = container.firstChild
    expect(el.style.background).toBe(STAGE_META.implement.color)
    expect(el.style.animation).toContain('stream-pulse')
  })

  it('renders a checkmark for done status', () => {
    const { container } = render(<StatusDot status="done" />)
    expect(container.textContent).toBe('\u2713')
  })

  it('renders an X mark for failed status', () => {
    const { container } = render(<StatusDot status="failed" />)
    expect(container.textContent).toBe('\u2717')
  })

  it('renders an exclamation for hitl status', () => {
    const { container } = render(<StatusDot status="hitl" />)
    expect(container.textContent).toBe('!')
  })

  it('uses the stage subtle color for queued status when stageKey is provided', () => {
    const { container } = render(<StatusDot status="queued" stageKey="plan" />)
    const el = container.firstChild
    expect(el.tagName).toBe('SPAN')
    expect(el.style.background).toBe(STAGE_META.plan.subtleColor)
    expect(el.style.border).toContain(STAGE_META.plan.color)
    expect(el.style.animation).toBe('')
  })

  it('falls back to the neutral queued style when no stageKey is provided', () => {
    const { container } = render(<StatusDot status="queued" />)
    const el = container.firstChild
    expect(el.tagName).toBe('SPAN')
    expect(el.style.background).toBe(theme.border)
    expect(el.style.animation).toBe('')
  })

  it('renders a static grey dot for pending status', () => {
    const { container } = render(<StatusDot status="pending" />)
    const el = container.firstChild
    expect(el.tagName).toBe('SPAN')
    expect(el.style.background).toBe(theme.border)
    expect(el.style.animation).toBe('')
  })
})

describe('StreamCard pulse animation — regression #1080', () => {
  it('does not inject an inline <style> tag (animation must live in index.html)', () => {
    const issue = makeIssue({ overallStatus: 'active' })
    const { container } = render(<StreamCard issue={issue} />)
    expect(container.querySelector('style')).toBeNull()
  })

  it('active stage node carries the stream-pulse animation when expanded', () => {
    const issue = makeIssue({ overallStatus: 'active' })
    const { container } = render(<StreamCard issue={issue} defaultExpanded />)
    const animatedNodes = Array.from(container.querySelectorAll('span, div')).filter(
      el => el.style.animation && el.style.animation.includes('stream-pulse')
    )
    expect(animatedNodes.length).toBeGreaterThan(0)
  })
})

describe('dotStyles', () => {
  it('has entries for all supported statuses', () => {
    const expectedStatuses = ['active', 'done', 'failed', 'hitl', 'queued', 'pending']
    for (const status of expectedStatuses) {
      expect(dotStyles).toHaveProperty(status)
    }
  })

  it('active style has pulse animation', () => {
    expect(dotStyles.active.animation).toContain('stream-pulse')
  })

  it('queued style falls back to neutral background and has no animation', () => {
    expect(dotStyles.queued.background).toBe(theme.border)
    expect(dotStyles.queued).not.toHaveProperty('animation')
  })

  it('pending style has border color background and no animation', () => {
    expect(dotStyles.pending.background).toBe(theme.border)
    expect(dotStyles.pending).not.toHaveProperty('animation')
  })
})

describe('badgeStyleMap', () => {
  it('has entries for all non-queued statuses', () => {
    const expectedStatuses = ['active', 'done', 'failed', 'hitl', 'pending']
    for (const status of expectedStatuses) {
      expect(badgeStyleMap).toHaveProperty(status)
    }
  })

  it('does not have a queued entry (stage-specific colors are applied inline in StageRow)', () => {
    expect(badgeStyleMap).not.toHaveProperty('queued')
  })
})

describe('StageRow queued presentation', () => {
  it('uses stage-specific subtle colors for queued nodes and badges', () => {
    const issue = makeIssue({ overallStatus: 'queued', currentStage: 'plan' })
    issue.stages.plan = { ...issue.stages.plan, status: 'queued' }

    const { getByTestId } = render(<StreamCard issue={issue} defaultExpanded />)
    const node = getByTestId('stage-node-plan')
    const badge = getByTestId('stage-badge-plan')

    expect(node.style.background).toBe(STAGE_META.plan.subtleColor)
    expect(node.style.borderColor).toBe(STAGE_META.plan.color)
    expect(badge.style.background).toBe(STAGE_META.plan.subtleColor)
    expect(badge.style.color).toBe(STAGE_META.plan.color)
  })
})

describe('StreamCard phase-aware styling', () => {
  it('aligns border and accent to stage color when collapsed', () => {
    const issue = makeIssue({ overallStatus: 'active', currentStage: 'review' })
    const { container } = render(<StreamCard issue={issue} />)
    const card = container.firstChild
    expect(card.style.margin).toBe('0px 8px 8px')
    expect(card.getAttribute('style') || '').toContain(`border-left: 3px solid ${STAGE_META.review.color}`)
  })

  it('falls back to subtle border for inactive cards', () => {
    const issue = makeIssue({ overallStatus: 'queued', currentStage: 'plan' })
    issue.stages.plan = { ...issue.stages.plan, status: 'queued' }
    const { container } = render(<StreamCard issue={issue} />)
    const card = container.firstChild
    expect(card.getAttribute('style') || '').toContain(`border-left: 3px solid ${STAGE_META.plan.color}`)
  })

  it('uses cardInactiveStyleMap for done status', () => {
    const issue = makeIssue({ overallStatus: 'done', currentStage: 'implement' })
    const { container } = render(<StreamCard issue={issue} />)
    const card = container.firstChild
    expect(card.getAttribute('style') || '').toContain(`border-left: 3px solid ${STAGE_META.implement.color}`)
  })

  it('uses cardInactiveStyleMap for failed status', () => {
    const issue = makeIssue({ overallStatus: 'failed', currentStage: 'review' })
    const { container } = render(<StreamCard issue={issue} />)
    const card = container.firstChild
    expect(card.getAttribute('style') || '').toContain(`border-left: 3px solid ${STAGE_META.review.color}`)
  })

  it('uses cardInactiveStyleMap for hitl status', () => {
    const issue = makeIssue({ overallStatus: 'hitl', currentStage: 'review' })
    const { container } = render(<StreamCard issue={issue} />)
    const card = container.firstChild
    expect(card.getAttribute('style') || '').toContain(`border-left: 3px solid ${STAGE_META.review.color}`)
  })

  it('falls back to neutral border when currentStage is null', () => {
    const issue = makeIssue({ overallStatus: 'queued', currentStage: null })
    const { container } = render(<StreamCard issue={issue} />)
    const card = container.firstChild
    // No phase-specific left border — base styles.card border only
    expect(card.getAttribute('style') || '').not.toContain('border-left')
  })
})

describe('phase-specific style maps', () => {
  it('exports per-stage card and dot styles', () => {
    for (const key of STAGE_KEYS) {
      const meta = STAGE_META[key]
      expect(cardActiveStyleMap[key].border).toBe(`1px solid ${meta.color}`)
      expect(cardActiveStyleMap[key].borderLeft).toBe(`3px solid ${meta.color}`)
      expect(cardInactiveStyleMap[key].border).toBe(`1px solid color-mix(in srgb, ${meta.color} 20%, transparent)`)
      expect(cardInactiveStyleMap[key].borderLeft).toBe(`3px solid ${meta.color}`)
      expect(activeDotStyleMap[key].background).toBe(meta.color)
      expect(activeDotStyleMap[key].animation).toContain('stream-pulse')
    }
  })
})

describe('StreamCard auto-collapse on status change', () => {
  it('collapses when defaultExpanded transitions from true to false', async () => {
    const issue = makeIssue()
    const intent = { text: 'Tighten regression coverage' }
    const { rerender } = render(<StreamCard issue={issue} defaultExpanded intent={intent} />)
    expect(screen.getByText('Intent:')).toBeInTheDocument()

    rerender(<StreamCard issue={issue} defaultExpanded={false} intent={intent} />)

    await waitFor(() => {
      expect(screen.queryByText('Intent:')).toBeNull()
    })
  })

  it('does not auto-expand when defaultExpanded transitions from false to true', async () => {
    const issue = makeIssue()
    const intent = { text: 'Document auto-collapse behavior' }
    const { rerender } = render(<StreamCard issue={issue} defaultExpanded={false} intent={intent} />)
    expect(screen.queryByText('Intent:')).toBeNull()

    rerender(<StreamCard issue={issue} defaultExpanded intent={intent} />)

    await waitFor(() => {
      expect(screen.queryByText('Intent:')).toBeNull()
    })
  })

  it('allows manual toggle to expand after auto-collapse runs', async () => {
    const issue = makeIssue()
    const intent = { text: 'Keep UI clean' }
    const { rerender } = render(<StreamCard issue={issue} defaultExpanded intent={intent} />)
    expect(screen.getByText('Intent:')).toBeInTheDocument()

    rerender(<StreamCard issue={issue} defaultExpanded={false} intent={intent} />)

    await waitFor(() => {
      expect(screen.queryByText('Intent:')).toBeNull()
    })

    fireEvent.click(screen.getByText('Keep UI clean'))
    expect(screen.getByText('Intent:')).toBeInTheDocument()
  })
})

describe('StreamCard request changes feedback flow', () => {
  it('shows feedback textarea on Request Changes click', () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn()
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    expect(screen.getByTestId('request-changes-textarea-42')).toBeTruthy()
  })

  it('hides feedback textarea on Cancel click', () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn()
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    expect(screen.getByTestId('request-changes-textarea-42')).toBeTruthy()

    fireEvent.click(screen.getByTestId('request-changes-cancel-42'))
    expect(screen.queryByTestId('request-changes-textarea-42')).toBeNull()
  })

  it('disables submit when feedback is empty', () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn()
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    const submitBtn = screen.getByTestId('request-changes-submit-42')
    expect(submitBtn.disabled).toBe(true)
  })

  it('calls onRequestChanges with correct arguments on submit', async () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn(() => Promise.resolve())
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    const textarea = screen.getByTestId('request-changes-textarea-42')
    fireEvent.change(textarea, { target: { value: 'Fix the tests please' } })

    const submitBtn = screen.getByTestId('request-changes-submit-42')
    expect(submitBtn.disabled).toBe(false)
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(onRequestChanges).toHaveBeenCalledWith(42, 'Fix the tests please', 'review')
    })
  })

  it('shows placeholder text on textarea', () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn()
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    const textarea = screen.getByTestId('request-changes-textarea-42')
    expect(textarea.placeholder).toBe('What needs to change?')
  })

  it('does not show Request Changes button when onRequestChanges is not provided', () => {
    const issue = makeIssue()
    render(<StreamCard issue={issue} defaultExpanded />)

    expect(screen.queryByTestId('request-changes-btn-42')).toBeNull()
  })

  it('closes feedback panel after successful submit', async () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn().mockResolvedValue(true)
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    fireEvent.change(screen.getByTestId('request-changes-textarea-42'), {
      target: { value: 'Fix the tests' },
    })
    fireEvent.click(screen.getByTestId('request-changes-submit-42'))

    await waitFor(() => {
      expect(screen.queryByTestId('request-changes-textarea-42')).toBeNull()
    })
  })

  it('keeps feedback panel open after failed submit', async () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn().mockResolvedValue(false)
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    fireEvent.change(screen.getByTestId('request-changes-textarea-42'), {
      target: { value: 'Fix the tests' },
    })
    fireEvent.click(screen.getByTestId('request-changes-submit-42'))

    await waitFor(() => {
      expect(onRequestChanges).toHaveBeenCalled()
    })
    expect(screen.getByTestId('request-changes-textarea-42')).toBeTruthy()
  })

  it('shows error message after failed submit', async () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn().mockResolvedValue(false)
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    fireEvent.change(screen.getByTestId('request-changes-textarea-42'), {
      target: { value: 'Fix the tests' },
    })
    fireEvent.click(screen.getByTestId('request-changes-submit-42'))

    await waitFor(() => {
      expect(screen.getByTestId('request-changes-error-42')).toBeTruthy()
    })
    expect(screen.getByTestId('request-changes-error-42').textContent).toContain('Failed')
  })

  it('clears error message on Cancel', async () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn().mockResolvedValue(false)
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    fireEvent.change(screen.getByTestId('request-changes-textarea-42'), {
      target: { value: 'Fix the tests' },
    })
    fireEvent.click(screen.getByTestId('request-changes-submit-42'))

    await waitFor(() => {
      expect(screen.getByTestId('request-changes-error-42')).toBeTruthy()
    })

    fireEvent.click(screen.getByTestId('request-changes-cancel-42'))
    expect(screen.queryByTestId('request-changes-error-42')).toBeNull()
  })

  it('disables submit button and shows Submitting text while in-flight', async () => {
    const issue = makeIssue()
    let resolveRequest
    const onRequestChanges = vi.fn(() => new Promise(r => { resolveRequest = r }))
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    fireEvent.change(screen.getByTestId('request-changes-textarea-42'), {
      target: { value: 'Fix the tests' },
    })
    fireEvent.click(screen.getByTestId('request-changes-submit-42'))

    // During submission the button must be disabled and show "Submitting..."
    await waitFor(() => {
      expect(screen.getByTestId('request-changes-submit-42').disabled).toBe(true)
    })
    expect(screen.getByTestId('request-changes-submit-42').textContent).toBe('Submitting...')

    // Resolve and let the component settle
    resolveRequest(true)
    await waitFor(() => {
      expect(screen.queryByTestId('request-changes-textarea-42')).toBeNull()
    })
  })

  it('clears feedback text when panel is toggle-closed via Request Changes button', () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn()
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    // Open panel and type text
    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    fireEvent.change(screen.getByTestId('request-changes-textarea-42'), {
      target: { value: 'Some feedback' },
    })

    // Toggle-close via the button (not Cancel)
    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    expect(screen.queryByTestId('request-changes-textarea-42')).toBeNull()

    // Re-open — panel must start empty
    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    expect(screen.getByTestId('request-changes-textarea-42').value).toBe('')
  })

  it('clears feedback text so re-opened panel starts empty after success', async () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn().mockResolvedValue(true)
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    fireEvent.change(screen.getByTestId('request-changes-textarea-42'), {
      target: { value: 'Fix the tests' },
    })
    fireEvent.click(screen.getByTestId('request-changes-submit-42'))

    await waitFor(() => {
      expect(screen.queryByTestId('request-changes-textarea-42')).toBeNull()
    })

    // Re-open and verify text was reset
    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    expect(screen.getByTestId('request-changes-textarea-42').value).toBe('')
  })

  it('does not close panel when Request Changes toggle is clicked during submission', async () => {
    const issue = makeIssue()
    let resolveRequest
    const onRequestChanges = vi.fn(() => new Promise(r => { resolveRequest = r }))
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    fireEvent.change(screen.getByTestId('request-changes-textarea-42'), {
      target: { value: 'Fix the tests' },
    })
    fireEvent.click(screen.getByTestId('request-changes-submit-42'))

    // While in-flight, clicking the toggle must not close the panel
    await waitFor(() => {
      expect(screen.getByTestId('request-changes-submit-42').disabled).toBe(true)
    })
    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    expect(screen.getByTestId('request-changes-textarea-42')).toBeTruthy()

    resolveRequest(true)
    await waitFor(() => {
      expect(screen.queryByTestId('request-changes-textarea-42')).toBeNull()
    })
  })

  it('clears error message when panel is toggle-closed via Request Changes button', async () => {
    const issue = makeIssue()
    const onRequestChanges = vi.fn().mockResolvedValue(false)
    render(<StreamCard issue={issue} defaultExpanded onRequestChanges={onRequestChanges} />)

    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    fireEvent.change(screen.getByTestId('request-changes-textarea-42'), {
      target: { value: 'Fix the tests' },
    })
    fireEvent.click(screen.getByTestId('request-changes-submit-42'))

    await waitFor(() => {
      expect(screen.getByTestId('request-changes-error-42')).toBeTruthy()
    })

    // Close via toggle button (not Cancel)
    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    // Re-open — error must be gone
    fireEvent.click(screen.getByTestId('request-changes-btn-42'))
    expect(screen.queryByTestId('request-changes-error-42')).toBeNull()
  })
})

describe('StreamCard issue link', () => {
  it('renders issue number as a link when issueUrl is provided', () => {
    const issue = makeIssue({ issueUrl: 'https://github.com/owner/repo/issues/42' })
    render(<StreamCard issue={issue} />)
    const link = screen.getByText('#42')
    expect(link.tagName).toBe('A')
    expect(link.getAttribute('href')).toBe('https://github.com/owner/repo/issues/42')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
  })

  it('renders issue number as plain text when issueUrl is absent', () => {
    const issue = makeIssue({ issueUrl: null })
    render(<StreamCard issue={issue} />)
    const text = screen.getByText('#42')
    expect(text.tagName).toBe('SPAN')
  })

  it('link click does not toggle card expansion', () => {
    const issue = makeIssue({ issueUrl: 'https://github.com/owner/repo/issues/42' })
    const { container } = render(<StreamCard issue={issue} defaultExpanded={false} />)
    const link = screen.getByText('#42')
    fireEvent.click(link)
    // Card body should not appear — the card should remain collapsed
    expect(container.querySelector('[style*="border-top"]')).toBeNull()
  })
})

describe('StreamCard transcript rendering', () => {
  it('renders TranscriptPreview when active and transcript is non-empty', () => {
    const issue = makeIssue({ overallStatus: 'active' })
    render(<StreamCard issue={issue} defaultExpanded={true} transcript={['line 1', 'line 2', 'line 3']} />)
    expect(screen.getByTestId('transcript-preview')).toBeInTheDocument()
    expect(screen.getByText('line 1')).toBeInTheDocument()
    expect(screen.getByText('line 2')).toBeInTheDocument()
    expect(screen.getByText('line 3')).toBeInTheDocument()
  })

  it('does not render TranscriptPreview when status is queued', () => {
    const issue = makeIssue({ overallStatus: 'queued' })
    render(<StreamCard issue={issue} defaultExpanded={true} transcript={['line 1']} />)
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
  })

  it('does not render TranscriptPreview when status is done', () => {
    const issue = makeIssue({ overallStatus: 'done' })
    render(<StreamCard issue={issue} defaultExpanded={true} transcript={['line 1']} />)
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
  })

  it('does not render TranscriptPreview when status is failed', () => {
    const issue = makeIssue({ overallStatus: 'failed' })
    render(<StreamCard issue={issue} defaultExpanded={true} transcript={['line 1']} />)
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
  })

  it('does not render TranscriptPreview when status is hitl', () => {
    const issue = makeIssue({ overallStatus: 'hitl' })
    render(<StreamCard issue={issue} defaultExpanded={true} transcript={['line 1']} />)
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
  })

  it('does not render TranscriptPreview when transcript is empty', () => {
    const issue = makeIssue({ overallStatus: 'active' })
    render(<StreamCard issue={issue} defaultExpanded={true} transcript={[]} />)
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
  })

  it('does not render TranscriptPreview when card is collapsed', () => {
    const issue = makeIssue({ overallStatus: 'active' })
    render(<StreamCard issue={issue} defaultExpanded={false} transcript={['line 1']} />)
    // No transcript should be visible when collapsed
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
  })

  it('defaults transcript to empty array when not provided', () => {
    const issue = makeIssue({ overallStatus: 'active' })
    render(<StreamCard issue={issue} defaultExpanded={true} />)
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
  })

  it('shows transcript after expanding a collapsed active card', () => {
    const issue = makeIssue({ overallStatus: 'active' })
    render(<StreamCard issue={issue} defaultExpanded={false} transcript={['line 1', 'line 2']} />)
    // Collapsed — no transcript
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
    // Expand by clicking the title
    fireEvent.click(screen.getByText('Fix the frobnicator'))
    // Transcript now visible
    expect(screen.getByTestId('transcript-preview')).toBeInTheDocument()
    expect(screen.getByText('line 2')).toBeInTheDocument()
  })

  it('hides transcript after collapsing an expanded active card', () => {
    const issue = makeIssue({ overallStatus: 'active' })
    render(<StreamCard issue={issue} defaultExpanded={true} transcript={['line 1', 'line 2']} />)
    // Expanded — transcript visible
    expect(screen.getByTestId('transcript-preview')).toBeInTheDocument()
    // Collapse by clicking the title
    fireEvent.click(screen.getByText('Fix the frobnicator'))
    // Transcript gone after collapse
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
  })

  it('does not render a View Transcript button for active issues with transcript', () => {
    const issue = makeIssue({ overallStatus: 'active' })
    render(<StreamCard issue={issue} defaultExpanded={true} transcript={['line 1', 'line 2']} onRequestChanges={() => {}} />)
    expect(screen.queryByText('View Transcript')).not.toBeInTheDocument()
  })

  it('does not render a View Transcript button for done issues with a PR URL', () => {
    const issue = makeIssue({ overallStatus: 'done', pr: { number: 10, url: 'https://github.com/pr/10' } })
    render(<StreamCard issue={issue} defaultExpanded={true} transcript={['line 1']} />)
    expect(screen.queryByText('View Transcript')).not.toBeInTheDocument()
  })
})
