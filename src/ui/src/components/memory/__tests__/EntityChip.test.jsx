import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { EntityChip } from '../EntityChip'

describe('EntityChip', () => {
  it('renders issue chip with # prefix', () => {
    render(<EntityChip type="issue" value={1234} onFocusEntity={() => {}} />)
    expect(screen.getByText('#1234')).toBeInTheDocument()
  })

  it('renders pr chip with "PR #" prefix', () => {
    render(<EntityChip type="pr" value={567} onFocusEntity={() => {}} />)
    expect(screen.getByText('PR #567')).toBeInTheDocument()
  })

  it('renders category chip with provided label', () => {
    render(<EntityChip type="category" value="missing_tests" label="Missing Tests" onFocusEntity={() => {}} />)
    expect(screen.getByText('Missing Tests')).toBeInTheDocument()
  })

  it('emits focus event on issue click', () => {
    const onFocus = vi.fn()
    render(<EntityChip type="issue" value={42} onFocusEntity={onFocus} />)
    fireEvent.click(screen.getByText('#42'))
    expect(onFocus).toHaveBeenCalledWith({ type: 'issue', value: 42 })
  })

  it('bank chip does NOT call onFocusEntity', () => {
    const onFocus = vi.fn()
    const onToggleBank = vi.fn()
    render(
      <EntityChip
        type="bank"
        value="hydraflow-tribal"
        label="TRIBAL"
        onFocusEntity={onFocus}
        onToggleBankSection={onToggleBank}
      />,
    )
    fireEvent.click(screen.getByText('TRIBAL'))
    expect(onFocus).not.toHaveBeenCalled()
    expect(onToggleBank).toHaveBeenCalledWith('hydraflow-tribal')
  })
})
