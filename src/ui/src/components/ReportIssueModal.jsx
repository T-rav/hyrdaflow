import React, { useState, useRef, useEffect, useCallback } from 'react'
import { theme } from '../theme'
import { ANNOTATION_COLORS, ANNOTATION_PENCIL_CURSOR } from '../constants'

/** Resolve a CSS variable reference like `var(--yellow)` to its computed value. */
function resolveColor(cssVar) {
  if (!cssVar || !cssVar.startsWith('var(')) return cssVar
  const prop = cssVar.slice(4, -1).trim()
  return getComputedStyle(document.documentElement).getPropertyValue(prop).trim() || cssVar
}

const PencilIcon = ({ color, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
    <path d="m15 5 4 4" />
  </svg>
)

export function ReportIssueModal({ isOpen, screenshotDataUrl, onSubmit, onClose }) {
  const canvasRef = useRef(null)
  const [description, setDescription] = useState('')
  const [selectedColor, setSelectedColor] = useState(ANNOTATION_COLORS[0].color)
  const [isDrawing, setIsDrawing] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const lastPoint = useRef(null)

  // Load screenshot into canvas when expanded
  useEffect(() => {
    if (!isOpen || !screenshotDataUrl || !expanded || !canvasRef.current) return
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    const img = new Image()
    img.onload = () => {
      canvas.width = img.width
      canvas.height = img.height
      ctx.drawImage(img, 0, 0)
    }
    img.src = screenshotDataUrl
  }, [isOpen, screenshotDataUrl, expanded])

  // Reset state when modal closes
  useEffect(() => {
    if (!isOpen) {
      setDescription('')
      setSelectedColor(ANNOTATION_COLORS[0].color)
      setSubmitting(false)
      setExpanded(false)
      lastPoint.current = null
    }
  }, [isOpen])

  const getCanvasPoint = useCallback((e) => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const clientX = e.touches ? e.touches[0].clientX : e.clientX
    const clientY = e.touches ? e.touches[0].clientY : e.clientY
    return {
      x: (clientX - rect.left) * (canvas.width / rect.width),
      y: (clientY - rect.top) * (canvas.height / rect.height),
    }
  }, [])

  const startDrawing = useCallback((e) => {
    e.preventDefault()
    setIsDrawing(true)
    lastPoint.current = getCanvasPoint(e)
  }, [getCanvasPoint])

  const draw = useCallback((e) => {
    if (!isDrawing || !canvasRef.current) return
    e.preventDefault()
    const ctx = canvasRef.current.getContext('2d')
    const point = getCanvasPoint(e)
    if (!point || !lastPoint.current) return

    ctx.beginPath()
    ctx.moveTo(lastPoint.current.x, lastPoint.current.y)
    ctx.lineTo(point.x, point.y)
    ctx.strokeStyle = resolveColor(selectedColor)
    ctx.lineWidth = 6
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.stroke()
    lastPoint.current = point
  }, [isDrawing, selectedColor, getCanvasPoint])

  const stopDrawing = useCallback(() => {
    setIsDrawing(false)
    lastPoint.current = null
  }, [])

  const handleSubmit = useCallback(async () => {
    if (!description.trim() || submitting) return
    setSubmitting(true)
    const screenshot_base64 = canvasRef.current
      ? canvasRef.current.toDataURL('image/png')
      : screenshotDataUrl || ''
    await onSubmit({ description: description.trim(), screenshot_base64 })
    setSubmitting(false)
    onClose()
  }, [description, submitting, screenshotDataUrl, onSubmit, onClose])

  const handleBackdropClick = useCallback((e) => {
    if (e.target === e.currentTarget) onClose()
  }, [onClose])

  if (!isOpen) return null

  return (
    <div style={styles.overlay} onClick={handleBackdropClick} data-testid="report-modal-overlay">
      <div style={expanded ? styles.cardExpanded : styles.card} data-testid="report-modal-card">
        <div style={styles.titleRow}>
          <span style={styles.title}>Report Issue</span>
          {expanded && (
            <button style={styles.collapseBtn} onClick={() => setExpanded(false)} data-testid="collapse-canvas">
              Collapse
            </button>
          )}
        </div>

        {screenshotDataUrl && !expanded && (
          <button
            style={styles.thumbnailBtn}
            onClick={() => setExpanded(true)}
            data-testid="screenshot-thumbnail"
          >
            <img src={screenshotDataUrl} alt="Screenshot preview" style={styles.thumbnailImg} />
            <div style={styles.thumbnailOverlay}>
              <PencilIcon color={theme.white} size={20} />
              <span style={styles.thumbnailLabel}>Click to annotate</span>
            </div>
          </button>
        )}

        {screenshotDataUrl && expanded && (
          <>
            <div style={styles.toolRow}>
              <div style={styles.penIndicator}>
                <PencilIcon color={selectedColor} />
                <span style={styles.toolLabel}>Draw to annotate</span>
              </div>
              <div style={styles.colorRow} data-testid="color-picker">
                {ANNOTATION_COLORS.map((c) => (
                  <button
                    key={c.key}
                    title={c.label}
                    style={selectedColor === c.color ? { ...styles.colorSwatch, background: c.color, ...styles.colorSwatchSelected } : { ...styles.colorSwatch, background: c.color }}
                    onClick={() => setSelectedColor(c.color)}
                    data-testid={`color-swatch-${c.key}`}
                  />
                ))}
              </div>
            </div>

            <div style={styles.canvasWrapper}>
              <canvas
                ref={canvasRef}
                style={styles.canvas}
                onMouseDown={startDrawing}
                onMouseMove={draw}
                onMouseUp={stopDrawing}
                onMouseLeave={stopDrawing}
                onTouchStart={startDrawing}
                onTouchMove={draw}
                onTouchEnd={stopDrawing}
                data-testid="report-canvas"
              />
            </div>
          </>
        )}

        <textarea
          style={styles.textarea}
          placeholder="Describe the issue…"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          data-testid="report-description"
        />

        <div style={styles.actions}>
          <button style={styles.cancelBtn} onClick={onClose} data-testid="report-cancel">
            Cancel
          </button>
          <button
            style={!description.trim() || submitting ? submitBtnDisabled : styles.submitBtn}
            disabled={!description.trim() || submitting}
            onClick={handleSubmit}
            data-testid="report-submit"
          >
            {submitting ? 'Submitting…' : 'Submit Report'}
          </button>
        </div>
      </div>
    </div>
  )
}

const styles = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: theme.overlay,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  },
  card: {
    maxWidth: 600,
    width: '90vw',
    maxHeight: '90vh',
    overflow: 'auto',
    background: theme.surface,
    borderRadius: 12,
    padding: 24,
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  cardExpanded: {
    maxWidth: 1000,
    width: '95vw',
    maxHeight: '95vh',
    overflow: 'auto',
    background: theme.surface,
    borderRadius: 12,
    padding: 24,
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  titleRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    fontSize: 16,
    fontWeight: 700,
    color: theme.textBright,
  },
  collapseBtn: {
    padding: '4px 12px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: 'transparent',
    color: theme.textMuted,
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
  },
  thumbnailBtn: {
    position: 'relative',
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    overflow: 'hidden',
    padding: 0,
    cursor: 'pointer',
    background: 'transparent',
    lineHeight: 0,
  },
  thumbnailImg: {
    width: '100%',
    maxHeight: 180,
    objectFit: 'cover',
    objectPosition: 'top left',
    display: 'block',
    opacity: 0.7,
  },
  thumbnailOverlay: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    background: 'rgba(0,0,0,0.4)',
  },
  thumbnailLabel: {
    fontSize: 12,
    fontWeight: 600,
    color: theme.white,
  },
  toolRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    padding: '8px 12px',
    background: theme.bg,
    borderRadius: 8,
    border: `1px solid ${theme.border}`,
  },
  penIndicator: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  toolLabel: {
    fontSize: 11,
    color: theme.textMuted,
    fontWeight: 500,
  },
  colorRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'center',
  },
  colorSwatch: {
    width: 24,
    height: 24,
    borderRadius: '50%',
    border: '2px solid transparent',
    cursor: 'pointer',
    padding: 0,
    transition: 'box-shadow 0.15s, border-color 0.15s',
  },
  colorSwatchSelected: {
    borderColor: theme.white,
    boxShadow: '0 0 0 2px rgba(255,255,255,0.3)',
  },
  canvasWrapper: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    overflow: 'hidden',
    lineHeight: 0,
  },
  canvas: {
    width: '100%',
    height: 'auto',
    cursor: ANNOTATION_PENCIL_CURSOR,
    display: 'block',
  },
  textarea: {
    width: '100%',
    minHeight: 80,
    padding: 8,
    background: theme.bg,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    color: theme.text,
    fontFamily: 'inherit',
    fontSize: 12,
    resize: 'vertical',
    boxSizing: 'border-box',
  },
  actions: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 8,
  },
  cancelBtn: {
    padding: '6px 16px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: theme.surface,
    color: theme.textMuted,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
  },
  submitBtn: {
    padding: '6px 16px',
    borderRadius: 6,
    border: 'none',
    background: theme.accent,
    color: theme.white,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
  },
}

const submitBtnDisabled = { ...styles.submitBtn, opacity: 0.4, cursor: 'not-allowed' }
