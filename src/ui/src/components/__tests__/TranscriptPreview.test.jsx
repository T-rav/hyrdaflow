import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { TranscriptPreview } from '../TranscriptPreview'

describe('TranscriptPreview', () => {
  it('renders nothing when transcript is empty', () => {
    const { container } = render(<TranscriptPreview transcript={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when transcript is null', () => {
    const { container } = render(<TranscriptPreview transcript={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when transcript is undefined', () => {
    const { container } = render(<TranscriptPreview />)
    expect(container.firstChild).toBeNull()
  })

  it('shows last 3 lines when collapsed with more than 3 lines', () => {
    const lines = ['line 1', 'line 2', 'line 3', 'line 4', 'line 5']
    render(<TranscriptPreview transcript={lines} />)
    expect(screen.queryByText('line 1')).not.toBeInTheDocument()
    expect(screen.queryByText('line 2')).not.toBeInTheDocument()
    expect(screen.getByText('line 3')).toBeInTheDocument()
    expect(screen.getByText('line 4')).toBeInTheDocument()
    expect(screen.getByText('line 5')).toBeInTheDocument()
  })

  it('shows all lines when there are 3 or fewer', () => {
    const lines = ['line A', 'line B']
    render(<TranscriptPreview transcript={lines} />)
    expect(screen.getByText('line A')).toBeInTheDocument()
    expect(screen.getByText('line B')).toBeInTheDocument()
  })

  it('shows "Show all (N lines)" toggle when collapsed', () => {
    const lines = ['a', 'b', 'c', 'd', 'e']
    render(<TranscriptPreview transcript={lines} />)
    expect(screen.getByTestId('transcript-toggle')).toHaveTextContent('Show all (5 lines)')
  })

  it('expands to show all lines when toggle is clicked', () => {
    const lines = ['line 1', 'line 2', 'line 3', 'line 4', 'line 5']
    render(<TranscriptPreview transcript={lines} />)
    fireEvent.click(screen.getByTestId('transcript-toggle'))
    expect(screen.getByText('line 1')).toBeInTheDocument()
    expect(screen.getByText('line 2')).toBeInTheDocument()
    expect(screen.getByText('line 3')).toBeInTheDocument()
    expect(screen.getByText('line 4')).toBeInTheDocument()
    expect(screen.getByText('line 5')).toBeInTheDocument()
  })

  it('shows "Collapse" toggle when expanded', () => {
    const lines = ['a', 'b', 'c', 'd']
    render(<TranscriptPreview transcript={lines} />)
    fireEvent.click(screen.getByTestId('transcript-toggle'))
    expect(screen.getByTestId('transcript-toggle')).toHaveTextContent('Collapse')
  })

  it('collapses back when toggle is clicked twice', () => {
    const lines = ['line 1', 'line 2', 'line 3', 'line 4', 'line 5']
    render(<TranscriptPreview transcript={lines} />)
    fireEvent.click(screen.getByTestId('transcript-toggle'))
    fireEvent.click(screen.getByTestId('transcript-toggle'))
    expect(screen.queryByText('line 1')).not.toBeInTheDocument()
    expect(screen.queryByText('line 2')).not.toBeInTheDocument()
    expect(screen.getByText('line 3')).toBeInTheDocument()
  })

  it('respects custom maxCollapsedLines', () => {
    const lines = ['a', 'b', 'c', 'd', 'e']
    render(<TranscriptPreview transcript={lines} maxCollapsedLines={2} />)
    expect(screen.queryByText('a')).not.toBeInTheDocument()
    expect(screen.queryByText('b')).not.toBeInTheDocument()
    expect(screen.queryByText('c')).not.toBeInTheDocument()
    expect(screen.getByText('d')).toBeInTheDocument()
    expect(screen.getByText('e')).toBeInTheDocument()
  })

  it('applies custom maxHeight when expanded', () => {
    const lines = Array.from({ length: 50 }, (_, i) => `line ${i}`)
    render(<TranscriptPreview transcript={lines} maxHeight={150} />)
    fireEvent.click(screen.getByTestId('transcript-toggle'))
    const preview = screen.getByTestId('transcript-preview')
    const linesContainer = preview.querySelector('[style*="max-height"]') || preview.firstChild
    // When expanded, the lines container should have maxHeight set
    expect(linesContainer.style.maxHeight).toBe('150px')
    expect(linesContainer.style.overflowY).toBe('auto')
  })

  it('uses default maxHeight of 375px when expanded', () => {
    const lines = Array.from({ length: 50 }, (_, i) => `line ${i}`)
    render(<TranscriptPreview transcript={lines} />)
    fireEvent.click(screen.getByTestId('transcript-toggle'))
    const preview = screen.getByTestId('transcript-preview')
    const linesContainer = preview.querySelector('[style*="max-height"]') || preview.firstChild
    expect(linesContainer.style.maxHeight).toBe('375px')
    expect(linesContainer.style.overflowY).toBe('auto')
  })

  it('has data-testid on the container', () => {
    render(<TranscriptPreview transcript={['hello']} />)
    expect(screen.getByTestId('transcript-preview')).toBeInTheDocument()
  })

  it('does not show toggle when transcript has fewer lines than maxCollapsedLines', () => {
    render(<TranscriptPreview transcript={['line A', 'line B']} />)
    expect(screen.queryByTestId('transcript-toggle')).not.toBeInTheDocument()
  })

  it('does not show toggle when transcript has exactly maxCollapsedLines lines', () => {
    render(<TranscriptPreview transcript={['line 1', 'line 2', 'line 3']} maxCollapsedLines={3} />)
    expect(screen.queryByTestId('transcript-toggle')).not.toBeInTheDocument()
  })

  describe('copy button', () => {
    let writeTextMock

    beforeEach(() => {
      writeTextMock = vi.fn().mockResolvedValue(undefined)
      Object.assign(navigator, {
        clipboard: { writeText: writeTextMock },
      })
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('renders the copy button when transcript exists', () => {
      render(<TranscriptPreview transcript={['hello']} />)
      expect(screen.getByTestId('transcript-copy')).toBeInTheDocument()
      expect(screen.getByTestId('transcript-copy')).toHaveTextContent('Copy')
    })

    it('does not render copy button when transcript is empty', () => {
      const { container } = render(<TranscriptPreview transcript={[]} />)
      expect(container.firstChild).toBeNull()
    })

    it('copies full transcript to clipboard on click', async () => {
      const lines = ['line 1', 'line 2', 'line 3']
      render(<TranscriptPreview transcript={lines} />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('transcript-copy'))
      })

      expect(writeTextMock).toHaveBeenCalledWith('line 1\nline 2\nline 3')
    })

    it('copies all lines even when collapsed', async () => {
      const lines = ['line 1', 'line 2', 'line 3', 'line 4', 'line 5']
      render(<TranscriptPreview transcript={lines} />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('transcript-copy'))
      })

      expect(writeTextMock).toHaveBeenCalledWith('line 1\nline 2\nline 3\nline 4\nline 5')
    })

    it('shows "Copied!" feedback after clicking', async () => {
      render(<TranscriptPreview transcript={['hello']} />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('transcript-copy'))
      })

      expect(screen.getByTestId('transcript-copy')).toHaveTextContent('Copied!')
    })

    it('resets "Copied!" text after 1.5 seconds', async () => {
      render(<TranscriptPreview transcript={['hello']} />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('transcript-copy'))
      })

      expect(screen.getByTestId('transcript-copy')).toHaveTextContent('Copied!')

      act(() => {
        vi.advanceTimersByTime(1500)
      })

      expect(screen.getByTestId('transcript-copy')).toHaveTextContent('Copy')
    })

    it('handles clipboard API failure gracefully', async () => {
      writeTextMock.mockRejectedValue(new Error('Clipboard blocked'))
      render(<TranscriptPreview transcript={['hello']} />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('transcript-copy'))
      })

      // Should not crash, button should still show "Copy"
      expect(screen.getByTestId('transcript-copy')).toHaveTextContent('Copy')
    })

    it('clears timeout on unmount to prevent stale state update', async () => {
      const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout')
      const { unmount } = render(<TranscriptPreview transcript={['hello']} />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('transcript-copy'))
      })

      unmount()
      expect(clearTimeoutSpy).toHaveBeenCalled()
      clearTimeoutSpy.mockRestore()
    })
  })

})
