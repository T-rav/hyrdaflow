import React, { useState } from 'react'
import { theme } from '../../../theme'

export function InsightBar({ label, count, maxCount, color }) {
  const pct = maxCount > 0 ? (count / maxCount) * 100 : 0
  return (
    <div style={styles.barRow}>
      <div style={styles.barLabel}>{label}</div>
      <div style={styles.barTrack}>
        <div style={{ ...styles.barFill, width: `${pct}%`, background: color || theme.accent }} />
      </div>
      <div style={styles.barCount}>{count}</div>
    </div>
  )
}

export function StatBox({ label, value }) {
  return (
    <div style={styles.statBox}>
      <div style={styles.statValue}>{value}</div>
      <div style={styles.statLabel}>{label}</div>
    </div>
  )
}

/** PatternCard. `title` accepts a ReactNode so consumers can embed badges. */
export function PatternCard({ title, count, color, children }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div style={styles.patternCard}>
      <div
        style={styles.patternHeader}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setExpanded(!expanded)
          }
        }}
      >
        <span style={{ ...styles.patternDot, background: color || theme.orange }} />
        <span style={styles.patternTitle}>{title}</span>
        <span style={{ ...styles.patternCount, color: color || theme.orange }}>{count}x</span>
        <span style={styles.expandIcon}>{expanded ? '\u25B4' : '\u25BE'}</span>
      </div>
      {expanded && children && (
        <div style={styles.patternBody}>{children}</div>
      )}
    </div>
  )
}

const styles = {
  barRow: { display: 'flex', alignItems: 'center', gap: 8 },
  barLabel: { fontSize: 12, color: theme.text, width: 140, flexShrink: 0 },
  barTrack: { flex: 1, height: 8, background: theme.surfaceInset, borderRadius: 4, overflow: 'hidden' },
  barFill: { height: '100%', borderRadius: 4, transition: 'width 0.3s' },
  barCount: { fontSize: 12, fontWeight: 600, color: theme.textBright, width: 32, textAlign: 'right', flexShrink: 0 },
  statBox: { background: theme.surfaceInset, border: `1px solid ${theme.border}`, borderRadius: 8, padding: '8px 16px', minWidth: 100 },
  statValue: { fontSize: 18, fontWeight: 700, color: theme.textBright },
  statLabel: { fontSize: 11, color: theme.textMuted, marginTop: 2 },
  patternCard: { border: `1px solid ${theme.border}`, borderRadius: 8, background: theme.surface, overflow: 'hidden' },
  patternHeader: { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', cursor: 'pointer', transition: 'background 0.15s' },
  patternDot: { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 },
  patternTitle: { fontSize: 13, color: theme.text, flex: 1 },
  patternCount: { fontSize: 11, fontWeight: 600, color: theme.orange },
  expandIcon: { fontSize: 10, color: theme.textMuted },
  patternBody: { padding: '8px 12px 12px', borderTop: `1px solid ${theme.border}`, display: 'flex', flexDirection: 'column', gap: 4 },
}
