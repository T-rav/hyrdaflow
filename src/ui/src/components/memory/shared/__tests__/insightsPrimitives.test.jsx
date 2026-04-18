import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { InsightBar, StatBox, PatternCard } from '../insightsPrimitives'

describe('insightsPrimitives', () => {
  describe('InsightBar', () => {
    it('renders label and count', () => {
      render(<InsightBar label="Approve" count={7} maxCount={10} />)
      expect(screen.getByText('Approve')).toBeInTheDocument()
      expect(screen.getByText('7')).toBeInTheDocument()
    })
  })

  describe('StatBox', () => {
    it('renders label and value', () => {
      render(<StatBox label="Plan Accuracy" value="85%" />)
      expect(screen.getByText('Plan Accuracy')).toBeInTheDocument()
      expect(screen.getByText('85%')).toBeInTheDocument()
    })
  })

  describe('PatternCard', () => {
    it('renders title and count', () => {
      render(<PatternCard title="Missing Tests" count={4}>body</PatternCard>)
      expect(screen.getByText('Missing Tests')).toBeInTheDocument()
      expect(screen.getByText('4x')).toBeInTheDocument()
    })

    it('toggles body on click', () => {
      render(<PatternCard title="Pattern" count={1}>hidden body</PatternCard>)
      expect(screen.queryByText('hidden body')).not.toBeInTheDocument()
      fireEvent.click(screen.getByText('Pattern'))
      expect(screen.getByText('hidden body')).toBeInTheDocument()
      fireEvent.click(screen.getByText('Pattern'))
      expect(screen.queryByText('hidden body')).not.toBeInTheDocument()
    })
  })
})
