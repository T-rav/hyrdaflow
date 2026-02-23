import React, { useRef, useEffect, useState, useCallback } from 'react'
import { theme } from '../theme'
import { eventSummary, typeSpanStyles, defaultTypeStyle } from './EventLog'

export function Livestream({ events }) {
  const containerRef = useRef(null)
  const [autoScroll, setAutoScroll] = useState(true)

  // Auto-scroll: track whether user has scrolled away from the top
  // Events are newest-first, so "latest" means scrollTop = 0
  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const atTop = el.scrollTop < 50
    setAutoScroll(atTop)
  }, [])

  // Scroll to top when new events arrive (events are newest-first)
  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = 0
    }
  }, [events.length, autoScroll])

  return (
    <div ref={containerRef} onScroll={handleScroll} style={styles.container}>
      {!autoScroll && (
        <div style={styles.resumeBtn} onClick={() => {
          setAutoScroll(true)
          if (containerRef.current) containerRef.current.scrollTop = 0
        }}>
          ↑ New events — click to resume auto-scroll
        </div>
      )}
      {events.length === 0 && (
        <div style={styles.empty}>Waiting for events...</div>
      )}
      {events.map((e, i) => (
        <div key={i} style={styles.item}>
          <span style={styles.time}>
            {new Date(e.timestamp).toLocaleTimeString()}
          </span>
          <span style={typeSpanStyles[e.type] || defaultTypeStyle}>
            {e.type.replace(/_/g, ' ')}
          </span>
          <span>{eventSummary(e.type, e.data)}</span>
        </div>
      ))}
    </div>
  )
}

const styles = {
  container: {
    flex: 1,
    overflowY: 'auto',
    padding: 8,
    position: 'relative',
  },
  empty: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: 200,
    color: theme.textMuted,
    fontSize: 13,
  },
  item: {
    padding: '6px 8px',
    borderBottom: `1px solid ${theme.border}`,
    fontSize: 11,
  },
  time: { color: theme.textMuted, marginRight: 8 },
  resumeBtn: {
    position: 'sticky',
    top: 0,
    background: theme.accent,
    color: theme.white,
    textAlign: 'center',
    padding: '6px 12px',
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
    borderRadius: 4,
    zIndex: 1,
  },
}
