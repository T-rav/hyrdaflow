import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { WorkerLogStream } from '../WorkerLogStream'

describe('WorkerLogStream', () => {
  describe('empty state', () => {
    it('renders nothing when lines is empty', () => {
      const { container } = render(<WorkerLogStream lines={[]} />)
      expect(container.firstChild).toBeNull()
    })

    it('renders nothing when lines is undefined', () => {
      const { container } = render(<WorkerLogStream />)
      expect(container.firstChild).toBeNull()
    })

    it('renders nothing when lines is null', () => {
      const { container } = render(<WorkerLogStream lines={null} />)
      expect(container.firstChild).toBeNull()
    })
  })

  describe('collapsed state (default)', () => {
    it('renders all lines in the DOM when collapsed', () => {
      const lines = ['10:00:00 ok · a: 1', '10:00:01 ok · b: 2', '10:00:02 ok · c: 3', '10:00:03 ok · d: 4', '10:00:04 ok · e: 5']
      render(<WorkerLogStream lines={lines} />)
      for (const line of lines) {
        expect(screen.getByText(line)).toBeInTheDocument()
      }
    })

    it('has collapsed maxHeight style by default', () => {
      const lines = ['line 1', 'line 2', 'line 3', 'line 4', 'line 5']
      render(<WorkerLogStream lines={lines} />)
      const stream = screen.getByTestId('worker-log-stream')
      const scrollContainer = stream.firstChild
      expect(scrollContainer.style.maxHeight).toBe('51px')
    })

    it('has overflow hidden when collapsed', () => {
      const lines = ['line 1', 'line 2', 'line 3', 'line 4', 'line 5']
      render(<WorkerLogStream lines={lines} />)
      const stream = screen.getByTestId('worker-log-stream')
      const scrollContainer = stream.firstChild
      expect(scrollContainer.style.overflowY).toBe('hidden')
    })

    it('has transition for smooth animation', () => {
      const lines = ['line 1', 'line 2', 'line 3', 'line 4']
      render(<WorkerLogStream lines={lines} />)
      const stream = screen.getByTestId('worker-log-stream')
      const scrollContainer = stream.firstChild
      expect(scrollContainer.style.transition).toBe('max-height 0.2s ease')
    })
  })

  describe('toggle', () => {
    it('shows "Show more" toggle when more than 3 lines', () => {
      const lines = ['a', 'b', 'c', 'd']
      render(<WorkerLogStream lines={lines} />)
      expect(screen.getByTestId('worker-log-toggle')).toHaveTextContent('Show more')
    })

    it('does not show toggle when 3 or fewer lines', () => {
      const lines = ['a', 'b', 'c']
      render(<WorkerLogStream lines={lines} />)
      expect(screen.queryByTestId('worker-log-toggle')).not.toBeInTheDocument()
    })

    it('does not show toggle when exactly 1 line', () => {
      render(<WorkerLogStream lines={['single line']} />)
      expect(screen.queryByTestId('worker-log-toggle')).not.toBeInTheDocument()
    })
  })

  describe('expanded state', () => {
    it('expands when toggle is clicked', () => {
      const lines = ['a', 'b', 'c', 'd', 'e']
      render(<WorkerLogStream lines={lines} />)
      fireEvent.click(screen.getByTestId('worker-log-toggle'))
      const stream = screen.getByTestId('worker-log-stream')
      const scrollContainer = stream.firstChild
      expect(scrollContainer.style.maxHeight).toBe('255px')
    })

    it('has overflow-y auto when expanded', () => {
      const lines = ['a', 'b', 'c', 'd', 'e']
      render(<WorkerLogStream lines={lines} />)
      fireEvent.click(screen.getByTestId('worker-log-toggle'))
      const stream = screen.getByTestId('worker-log-stream')
      const scrollContainer = stream.firstChild
      expect(scrollContainer.style.overflowY).toBe('auto')
    })

    it('shows "Show less" when expanded', () => {
      const lines = ['a', 'b', 'c', 'd']
      render(<WorkerLogStream lines={lines} />)
      fireEvent.click(screen.getByTestId('worker-log-toggle'))
      expect(screen.getByTestId('worker-log-toggle')).toHaveTextContent('Show less')
    })

    it('collapses back when toggle clicked twice', () => {
      const lines = ['a', 'b', 'c', 'd', 'e']
      render(<WorkerLogStream lines={lines} />)
      fireEvent.click(screen.getByTestId('worker-log-toggle'))
      fireEvent.click(screen.getByTestId('worker-log-toggle'))
      const stream = screen.getByTestId('worker-log-stream')
      const scrollContainer = stream.firstChild
      expect(scrollContainer.style.maxHeight).toBe('51px')
      expect(scrollContainer.style.overflowY).toBe('hidden')
      expect(screen.getByTestId('worker-log-toggle')).toHaveTextContent('Show more')
    })
  })

  describe('render order', () => {
    it('renders lines newest-first so collapsed view shows the 3 most recent', () => {
      // Lines are passed oldest-first (as SystemPanel sends them after its .reverse())
      const lines = ['old1', 'old2', 'old3', 'new1', 'new2']
      render(<WorkerLogStream lines={lines} />)
      const stream = screen.getByTestId('worker-log-stream')
      const lineEls = Array.from(stream.firstChild.children)
      // Newest entries must appear first in the DOM (CSS overflow clips the bottom)
      expect(lineEls[0].textContent).toBe('new2')
      expect(lineEls[1].textContent).toBe('new1')
      expect(lineEls[2].textContent).toBe('old3')
    })
  })

  describe('line limits', () => {
    it('limits to 15 lines when more are provided', () => {
      const lines = Array.from({ length: 20 }, (_, i) => `line ${i + 1}`)
      render(<WorkerLogStream lines={lines} />)
      // Only the last 15 lines should be rendered (most recent)
      expect(screen.queryByText('line 1')).not.toBeInTheDocument()
      expect(screen.queryByText('line 5')).not.toBeInTheDocument()
      expect(screen.getByText('line 6')).toBeInTheDocument()
      expect(screen.getByText('line 20')).toBeInTheDocument()
    })

    it('renders all lines when fewer than 15', () => {
      const lines = Array.from({ length: 10 }, (_, i) => `event ${i}`)
      render(<WorkerLogStream lines={lines} />)
      for (const line of lines) {
        expect(screen.getByText(line)).toBeInTheDocument()
      }
    })
  })

  describe('per-card independence', () => {
    it('each instance maintains independent expand/collapse state', () => {
      const lines1 = ['a1', 'b1', 'c1', 'd1']
      const lines2 = ['a2', 'b2', 'c2', 'd2']
      render(
        <div>
          <div data-testid="card-1">
            <WorkerLogStream lines={lines1} />
          </div>
          <div data-testid="card-2">
            <WorkerLogStream lines={lines2} />
          </div>
        </div>
      )
      const streams = screen.getAllByTestId('worker-log-stream')
      expect(streams).toHaveLength(2)

      // Expand only the first one
      const toggles = screen.getAllByTestId('worker-log-toggle')
      fireEvent.click(toggles[0])

      // First is expanded
      expect(streams[0].firstChild.style.maxHeight).toBe('255px')
      // Second stays collapsed
      expect(streams[1].firstChild.style.maxHeight).toBe('51px')
    })
  })

  describe('styling', () => {
    it('uses monospace font for lines', () => {
      render(<WorkerLogStream lines={['test line']} />)
      const stream = screen.getByTestId('worker-log-stream')
      const scrollContainer = stream.firstChild
      expect(scrollContainer.style.fontFamily).toBe('monospace')
    })

    it('has data-testid on the container', () => {
      render(<WorkerLogStream lines={['hello']} />)
      expect(screen.getByTestId('worker-log-stream')).toBeInTheDocument()
    })

    it('has border-top separator', () => {
      render(<WorkerLogStream lines={['hello']} />)
      const stream = screen.getByTestId('worker-log-stream')
      expect(stream.style.borderTop).toContain('1px solid')
    })
  })
})
