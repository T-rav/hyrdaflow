import React, { useState, useEffect, useRef } from 'react'
import { theme } from '../theme'

export function TranscriptPreview({ transcript, maxCollapsedLines = 3, maxHeight = 375 /* ~22 visible lines: 10px font × 1.5 line-height = 15px + 2px padding (styles.line) = 17px/line; 375 ÷ 17 ≈ 22 */ }) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)
  const scrollRef = useRef(null)
  const copyTimeoutRef = useRef(null)

  const handleCopy = async () => {
    try {
      const text = transcript.join('\n')
      await navigator.clipboard.writeText(text)
      setCopied(true)
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current)
      copyTimeoutRef.current = setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard API not available
    }
  }

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current)
    }
  }, [])

  useEffect(() => {
    if (expanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [expanded, transcript])

  if (!transcript || transcript.length === 0) return null

  const visibleLines = expanded
    ? transcript
    : transcript.slice(-maxCollapsedLines)

  const linesStyle = expanded ? { ...styles.lines, maxHeight, overflowY: 'auto' } : styles.lines

  return (
    <div style={styles.container} data-testid="transcript-preview" data-sensitive="true">
      <div
        ref={scrollRef}
        style={linesStyle}
      >
        {visibleLines.map((line, i) => (
          <div key={transcript.length - visibleLines.length + i} style={styles.line}>
            {line}
          </div>
        ))}
      </div>
      <div style={styles.controls}>
        {(expanded || transcript.length > maxCollapsedLines) && (
          <div
            style={styles.toggle}
            onClick={() => setExpanded(v => !v)}
            data-testid="transcript-toggle"
          >
            {expanded ? 'Collapse' : `Show all (${transcript.length} lines)`}
          </div>
        )}
        <div
          style={styles.copyBtn}
          onClick={handleCopy}
          data-testid="transcript-copy"
          title="Copy transcript"
        >
          {copied ? 'Copied!' : 'Copy'}
        </div>
      </div>
    </div>
  )
}

const styles = {
  container: {
    borderTop: `1px solid ${theme.border}`,
    marginTop: 4,
    paddingTop: 4,
  },
  lines: {
    fontFamily: 'monospace',
    fontSize: 10,
    color: theme.textMuted,
    lineHeight: 1.5,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
  },
  line: {
    padding: '1px 0',
  },
  controls: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingTop: 4,
  },
  toggle: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.accent,
    cursor: 'pointer',
    transition: 'opacity 0.15s',
  },
  copyBtn: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.accent,
    cursor: 'pointer',
    marginLeft: 'auto',
    transition: 'opacity 0.15s',
  },
}
