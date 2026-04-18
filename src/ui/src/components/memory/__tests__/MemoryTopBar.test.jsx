import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryTopBar } from '../MemoryTopBar'

const BANKS = [
  { id: 'hydraflow-tribal', name: 'TRIBAL' },
  { id: 'hydraflow-retrospectives', name: 'RETROSPECTIVES' },
]

describe('MemoryTopBar', () => {
  it('calls onSearchChange when typing', () => {
    const onSearchChange = vi.fn()
    render(
      <MemoryTopBar
        banks={BANKS}
        searchQuery=""
        bankFilter=""
        focusedEntity={null}
        onSearchChange={onSearchChange}
        onBankFilterChange={() => {}}
        onClearFocus={() => {}}
      />,
    )
    fireEvent.change(screen.getByTestId('memory-search-input'), { target: { value: 'timeout' } })
    expect(onSearchChange).toHaveBeenCalledWith('timeout')
  })

  it('renders bank options from banks prop', () => {
    render(
      <MemoryTopBar
        banks={BANKS}
        searchQuery=""
        bankFilter=""
        focusedEntity={null}
        onSearchChange={() => {}}
        onBankFilterChange={() => {}}
        onClearFocus={() => {}}
      />,
    )
    expect(screen.getByRole('option', { name: 'TRIBAL' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'RETROSPECTIVES' })).toBeInTheDocument()
  })

  it('shows focus pill when entity is focused', () => {
    render(
      <MemoryTopBar
        banks={BANKS}
        searchQuery=""
        bankFilter=""
        focusedEntity={{ type: 'issue', value: 1234 }}
        onSearchChange={() => {}}
        onBankFilterChange={() => {}}
        onClearFocus={() => {}}
      />,
    )
    expect(screen.getByTestId('memory-focus-pill')).toHaveTextContent('#1234')
  })

  it('focus pill close calls onClearFocus', () => {
    const onClearFocus = vi.fn()
    render(
      <MemoryTopBar
        banks={BANKS}
        searchQuery=""
        bankFilter=""
        focusedEntity={{ type: 'issue', value: 1234 }}
        onSearchChange={() => {}}
        onBankFilterChange={() => {}}
        onClearFocus={onClearFocus}
      />,
    )
    fireEvent.click(screen.getByTestId('memory-focus-clear'))
    expect(onClearFocus).toHaveBeenCalled()
  })
})
