import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemorySectionList } from '../MemorySectionList'

const SAMPLE_CONTEXT = {
  memories: {
    total_items: 1,
    items: [{ issue_number: 1234, learning: 'Dolt must use embedded mode' }],
  },
  retrospectives: {
    total_entries: 1,
    avg_plan_accuracy: 92,
    avg_quality_fix_rounds: 1,
    avg_ci_fix_rounds: 0,
    avg_duration_seconds: 120,
    reviewer_fix_rate: 0.4,
    verdict_counts: { approve: 1 },
    entries: [{
      issue_number: 1234, pr_number: 5678,
      plan_accuracy_pct: 92, quality_fix_rounds: 1, ci_fix_rounds: 0,
      review_verdict: 'approve',
    }],
  },
  reviewInsights: { total_reviews: 1, verdict_counts: {}, category_counts: {}, patterns: [] },
  troubleshooting: { total_patterns: 0, patterns: [] },
  harnessInsights: null,
}

describe('MemorySectionList', () => {
  it('renders all five section headers', () => {
    render(
      <MemorySectionList
        data={SAMPLE_CONTEXT}
        searchQuery=""
        bankFilter=""
        onFocusEntity={() => {}}
      />,
    )
    expect(screen.getByText('Retrospectives')).toBeInTheDocument()
    expect(screen.getByText('Review Feedback')).toBeInTheDocument()
    expect(screen.getByText('Troubleshooting Patterns')).toBeInTheDocument()
    expect(screen.getByText('Failure Patterns')).toBeInTheDocument()
    expect(screen.getByText('Tribal Learnings')).toBeInTheDocument()
  })

  it('emits focus event when issue chip clicked', () => {
    const onFocusEntity = vi.fn()
    render(
      <MemorySectionList
        data={SAMPLE_CONTEXT}
        searchQuery=""
        bankFilter=""
        onFocusEntity={onFocusEntity}
      />,
    )
    fireEvent.click(screen.getByText('Tribal Learnings'))
    fireEvent.click(screen.getByTestId('entity-chip-issue-1234'))
    expect(onFocusEntity).toHaveBeenCalledWith({ type: 'issue', value: 1234 })
  })

  it('hides non-matching items when search query is set', () => {
    render(
      <MemorySectionList
        data={SAMPLE_CONTEXT}
        searchQuery="unrelated-xyz"
        bankFilter=""
        onFocusEntity={() => {}}
      />,
    )
    fireEvent.click(screen.getByText('Tribal Learnings'))
    expect(screen.queryByText(/Dolt must use/)).not.toBeInTheDocument()
  })

  it('hides sections not matching bankFilter', () => {
    render(
      <MemorySectionList
        data={SAMPLE_CONTEXT}
        searchQuery=""
        bankFilter="hydraflow-tribal"
        onFocusEntity={() => {}}
      />,
    )
    expect(screen.getByText('Tribal Learnings')).toBeInTheDocument()
    expect(screen.queryByText('Retrospectives')).not.toBeInTheDocument()
  })

  it.each([
    ['hydraflow-retrospectives', 'Retrospectives'],
    ['hydraflow-review-insights', 'Review Feedback'],
    ['hydraflow-troubleshooting', 'Troubleshooting Patterns'],
    ['hydraflow-harness-insights', 'Failure Patterns'],
    ['hydraflow-tribal', 'Tribal Learnings'],
  ])('bankFilter=%s keeps the "%s" section visible', (bankId, label) => {
    render(
      <MemorySectionList
        data={SAMPLE_CONTEXT}
        searchQuery=""
        bankFilter={bankId}
        onFocusEntity={() => {}}
      />,
    )
    expect(screen.getByText(label)).toBeInTheDocument()
  })
})
