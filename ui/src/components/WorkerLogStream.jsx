import React, { useState, useEffect, useRef } from 'react'
import { theme } from '../theme'

const MAX_COLLAPSED = 3
const MAX_EXPANDED = 15
// fontSize(10) * lineHeight(1.5) + padding-top(1) + padding-bottom(1) = 17px per line
const LINE_HEIGHT = 17
const COLLAPSED_MAX_HEIGHT = MAX_COLLAPSED * LINE_HEIGHT
const EXPANDED_MAX_HEIGHT = MAX_EXPANDED * LINE_HEIGHT

export function WorkerLogStream({ lines }) {
  const [expanded, setExpanded] = useState(false)
  const scrollRef = useRef(null)

  const displayLines = (lines || []).slice(-MAX_EXPANDED)
  const hasMore = (lines || []).length > MAX_COLLAPSED

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0
    }
  }, [expanded])

  if (!lines || lines.length === 0) return null

  return (
    <div style={styles.container} data-testid="worker-log-stream">
      <div
        ref={scrollRef}
        style={{
          ...styles.lines,
          maxHeight: expanded ? EXPANDED_MAX_HEIGHT : COLLAPSED_MAX_HEIGHT,
          overflowY: expanded ? 'auto' : 'hidden',
          transition: 'max-height 0.2s ease',
        }}
      >
        {[...displayLines].reverse().map((line, i) => (
          <div key={i} style={styles.line}>{line}</div>
        ))}
      </div>
      {hasMore && (
        <div
          style={styles.toggle}
          onClick={() => setExpanded(v => !v)}
          data-testid="worker-log-toggle"
        >
          {expanded ? 'Show less' : 'Show more'}
        </div>
      )}
    </div>
  )
}

const styles = {
  container: {
    borderTop: `1px solid ${theme.border}`,
    marginTop: 8,
    paddingTop: 8,
  },
  lines: {
    fontFamily: 'monospace',
    fontSize: 10,
    color: theme.textMuted,
    lineHeight: 1.5,
  },
  line: {
    padding: '1px 0',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
  },
  toggle: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.accent,
    cursor: 'pointer',
    paddingTop: 4,
    transition: 'color 0.15s',
  },
}
