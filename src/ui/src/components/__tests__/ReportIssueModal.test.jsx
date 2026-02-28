import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ANNOTATION_COLORS } from '../../constants'

const { ReportIssueModal } = await import('../ReportIssueModal')

const defaultProps = {
  isOpen: true,
  screenshotDataUrl: null,
  onSubmit: vi.fn(),
  onClose: vi.fn(),
}

// Minimal valid data URL for tests that need a screenshot
const fakeScreenshot = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='

describe('ReportIssueModal', () => {
  it('renders nothing when isOpen is false', () => {
    render(<ReportIssueModal {...defaultProps} isOpen={false} />)
    expect(screen.queryByTestId('report-modal-overlay')).toBeNull()
  })

  it('renders overlay and card when isOpen is true', () => {
    render(<ReportIssueModal {...defaultProps} />)
    expect(screen.getByTestId('report-modal-overlay')).toBeInTheDocument()
    expect(screen.getByTestId('report-modal-card')).toBeInTheDocument()
  })

  it('hides thumbnail when no screenshot provided', () => {
    render(<ReportIssueModal {...defaultProps} screenshotDataUrl={null} />)
    expect(screen.queryByTestId('screenshot-thumbnail')).toBeNull()
    expect(screen.queryByTestId('color-picker')).toBeNull()
  })

  it('shows screenshot thumbnail when screenshot provided', () => {
    render(<ReportIssueModal {...defaultProps} screenshotDataUrl={fakeScreenshot} />)
    expect(screen.getByTestId('screenshot-thumbnail')).toBeInTheDocument()
    expect(screen.getByText('Click to annotate')).toBeInTheDocument()
  })

  it('clicking thumbnail expands to canvas with color picker', () => {
    render(<ReportIssueModal {...defaultProps} screenshotDataUrl={fakeScreenshot} />)
    fireEvent.click(screen.getByTestId('screenshot-thumbnail'))
    expect(screen.getByTestId('report-canvas')).toBeInTheDocument()
    expect(screen.getByTestId('color-picker')).toBeInTheDocument()
    expect(screen.getByText('Draw to annotate')).toBeInTheDocument()
    expect(screen.queryByTestId('screenshot-thumbnail')).toBeNull()
  })

  it('renders 6 color swatches when expanded', () => {
    render(<ReportIssueModal {...defaultProps} screenshotDataUrl={fakeScreenshot} />)
    fireEvent.click(screen.getByTestId('screenshot-thumbnail'))
    ANNOTATION_COLORS.forEach((c) => {
      expect(screen.getByTestId(`color-swatch-${c.key}`)).toBeInTheDocument()
    })
  })

  it('collapse button returns to thumbnail view', () => {
    render(<ReportIssueModal {...defaultProps} screenshotDataUrl={fakeScreenshot} />)
    fireEvent.click(screen.getByTestId('screenshot-thumbnail'))
    expect(screen.getByTestId('report-canvas')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('collapse-canvas'))
    expect(screen.getByTestId('screenshot-thumbnail')).toBeInTheDocument()
    expect(screen.queryByTestId('report-canvas')).toBeNull()
  })

  it('annotation canvas has pencil cursor with crosshair fallback', () => {
    render(<ReportIssueModal {...defaultProps} screenshotDataUrl={fakeScreenshot} />)
    fireEvent.click(screen.getByTestId('screenshot-thumbnail'))
    const canvas = screen.getByTestId('report-canvas')
    expect(canvas.style.cursor).toContain('data:image/svg+xml')
    expect(canvas.style.cursor).toContain('crosshair')
  })

  it('submit button is disabled with empty description', () => {
    render(<ReportIssueModal {...defaultProps} />)
    const submitBtn = screen.getByTestId('report-submit')
    expect(submitBtn).toBeDisabled()
  })

  it('submit calls onSubmit with description', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<ReportIssueModal {...defaultProps} onSubmit={onSubmit} />)
    const textarea = screen.getByTestId('report-description')
    fireEvent.change(textarea, { target: { value: 'Something is broken' } })
    const submitBtn = screen.getByTestId('report-submit')
    expect(submitBtn).not.toBeDisabled()
    fireEvent.click(submitBtn)
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ description: 'Something is broken' })
    )
  })

  it('cancel calls onClose', () => {
    const onClose = vi.fn()
    render(<ReportIssueModal {...defaultProps} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('report-cancel'))
    expect(onClose).toHaveBeenCalled()
  })

  it('backdrop click calls onClose', () => {
    const onClose = vi.fn()
    render(<ReportIssueModal {...defaultProps} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('report-modal-overlay'))
    expect(onClose).toHaveBeenCalled()
  })
})
