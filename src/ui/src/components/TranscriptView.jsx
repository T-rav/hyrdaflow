import React, { useEffect, useRef, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { theme } from '../theme'
import { ACTIVE_STATUSES, BACKGROUND_WORKERS } from '../constants'
import { useHydraFlow } from '../context/HydraFlowContext'

function formatTimestamp(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function BackgroundWorkerDetail({ workerKey, backgroundWorkers, events }) {
  const def = BACKGROUND_WORKERS.find(w => w.key === workerKey)
  const state = (backgroundWorkers || []).find(w => w.name === workerKey)

  const recentEvents = useMemo(() => {
    return (events || [])
      .filter(e => e.type === 'background_worker_status' && e.data?.worker === workerKey)
      .slice(0, 50)
  }, [events, workerKey])

  const label = def?.label || workerKey
  const status = state?.status || 'unknown'
  const lastRun = state?.last_run
  const details = state?.details || {}
  const hasDetails = Object.keys(details).length > 0
  const hasData = state || recentEvents.length > 0

  if (!hasData) {
    return (
      <div style={styles.container}>
        <div style={styles.header}>
          <span style={styles.label}>{label}</span>
        </div>
        <div style={styles.empty}>No log data available</div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.label}>{label}</span>
        <span style={styles.bgStatusBadge}>{status}</span>
      </div>

      <div style={styles.bgSection}>
        <div style={styles.bgSectionLabel}>Last Run</div>
        <div style={styles.bgDetailValue}>{lastRun ? new Date(lastRun).toLocaleString() : 'never'}</div>
      </div>

      {hasDetails && (
        <div style={styles.bgSection}>
          <div style={styles.bgSectionLabel}>Details</div>
          {Object.entries(details).map(([k, v]) => (
            <div key={k} style={styles.bgDetailRow}>
              <span style={styles.bgDetailKey}>{k.replace(/_/g, ' ')}</span>
              <span style={styles.bgDetailValue}>{String(v)}</span>
            </div>
          ))}
        </div>
      )}

      {recentEvents.length > 0 && (
        <div style={styles.bgSection}>
          <div style={styles.bgSectionLabel}>Recent Events</div>
          {recentEvents.map((evt, i) => (
            <div key={i} style={styles.bgEventRow}>
              <span style={styles.bgEventTime}>{formatTimestamp(evt.timestamp)}</span>
              <span style={styles.bgEventStatus}>{evt.data?.status || ''}</span>
              <span style={styles.bgEventDetails}>
                {evt.data?.details ? Object.entries(evt.data.details).map(([k, v]) => `${k}: ${v}`).join(', ') : ''}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function TranscriptView({ workers, selectedWorker }) {
  const { backgroundWorkers, events } = useHydraFlow()
  const containerRef = useRef(null)

  // Auto-scroll to bottom when new lines arrive
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [workers, selectedWorker])

  // Background worker selected — show detail view
  if (typeof selectedWorker === 'string' && selectedWorker.startsWith('bg-')) {
    const workerKey = selectedWorker.slice(3)
    return <BackgroundWorkerDetail workerKey={workerKey} backgroundWorkers={backgroundWorkers} events={events} />
  }

  // Single worker selected — show its transcript
  if (selectedWorker !== null && workers[selectedWorker]) {
    const w = workers[selectedWorker]
    return (
      <div ref={containerRef} style={styles.container}>
        <div style={styles.header}>
          <span style={styles.label}>#{selectedWorker}</span>
          <span style={styles.role}>{w.role}</span>
          <span style={styles.branch}>{w.branch}</span>
          <span style={styles.lines}>{w.transcript.length} lines</span>
        </div>
        {w.transcript.length === 0 ? (
          <div style={styles.waiting}>Waiting for output...</div>
        ) : (
          w.transcript.map((line, i) => (
            <div key={`${selectedWorker}-${i}`} style={styles.line}>
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{line}</ReactMarkdown>
            </div>
          ))
        )}
      </div>
    )
  }

  // No worker selected — show combined feed from all active workers
  const allLines = []
  for (const [key, w] of Object.entries(workers)) {
    if (!ACTIVE_STATUSES.includes(w.status)) continue
    for (const line of w.transcript) {
      allLines.push({ key, role: w.role, line })
    }
  }

  if (allLines.length === 0) {
    return (
      <div style={styles.container}>
        <div style={styles.empty}>Waiting for transcript output...</div>
      </div>
    )
  }

  return (
    <div ref={containerRef} style={styles.container}>
      <div style={styles.header}>
        <span style={styles.label}>All Workers</span>
        <span style={styles.lines}>{allLines.length} lines</span>
      </div>
      {allLines.map((item, i) => (
        <div key={`${item.key}-${i}`} style={styles.line}>
          <span style={styles.linePrefix}>[{item.role} #{item.key}]</span>
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{item.line}</ReactMarkdown>
        </div>
      ))}
    </div>
  )
}

const mdStyles = {
  h1: { fontSize: 16, fontWeight: 700, color: theme.textBright, margin: '8px 0 4px' },
  h2: { fontSize: 14, fontWeight: 700, color: theme.textBright, margin: '6px 0 3px' },
  h3: { fontSize: 13, fontWeight: 600, color: theme.textBright, margin: '4px 0 2px' },
  inlineCode: { background: theme.surface, padding: '2px 5px', borderRadius: 4, fontSize: 11, color: theme.codeText },
  pre: { background: theme.surface, padding: 8, borderRadius: 6, overflowX: 'auto', fontSize: 11, lineHeight: 1.5, margin: '4px 0' },
  codeBlock: { color: theme.textBright },
  ul: { margin: '2px 0', paddingLeft: 20 },
  ol: { margin: '2px 0', paddingLeft: 20 },
  li: { margin: '1px 0' },
  strong: { color: theme.textBright },
  p: { margin: '2px 0' },
}

const mdComponents = {
  h1: ({ children }) => <h1 style={mdStyles.h1}>{children}</h1>,
  h2: ({ children }) => <h2 style={mdStyles.h2}>{children}</h2>,
  h3: ({ children }) => <h3 style={mdStyles.h3}>{children}</h3>,
  code: ({ inline, children }) =>
    inline
      ? <code style={mdStyles.inlineCode}>{children}</code>
      : <pre style={mdStyles.pre}><code style={mdStyles.codeBlock}>{children}</code></pre>,
  ul: ({ children }) => <ul style={mdStyles.ul}>{children}</ul>,
  ol: ({ children }) => <ol style={mdStyles.ol}>{children}</ol>,
  li: ({ children }) => <li style={mdStyles.li}>{children}</li>,
  strong: ({ children }) => <strong style={mdStyles.strong}>{children}</strong>,
  p: ({ children }) => <p style={mdStyles.p}>{children}</p>,
}

const styles = {
  container: {
    flex: 1,
    overflowY: 'auto',
    padding: '12px 16px',
    fontSize: 12,
    lineHeight: 1.6,
  },
  empty: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: theme.textMuted,
    fontSize: 14,
  },
  waiting: {
    color: theme.textMuted,
    padding: '20px 0',
    fontStyle: 'italic',
  },
  header: {
    display: 'flex',
    gap: 12,
    alignItems: 'center',
    padding: '8px 0',
    marginBottom: 8,
    borderBottom: `1px solid ${theme.border}`,
  },
  label: { fontWeight: 700, color: theme.accent, fontSize: 14 },
  role: { color: theme.purple, fontSize: 11, fontWeight: 600 },
  branch: { color: theme.textMuted, fontSize: 11 },
  lines: { color: theme.textMuted, fontSize: 11, marginLeft: 'auto' },
  line: {
    padding: '1px 0',
    wordBreak: 'break-word',
  },
  linePrefix: {
    color: theme.accent,
    fontWeight: 600,
    fontSize: 11,
  },
  bgStatusBadge: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.textMuted,
    textTransform: 'uppercase',
  },
  bgSection: {
    padding: '12px 0',
    borderBottom: `1px solid ${theme.border}`,
  },
  bgSectionLabel: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.accent,
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  bgDetailRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 12,
    padding: '2px 0',
  },
  bgDetailKey: {
    color: theme.textMuted,
    textTransform: 'capitalize',
  },
  bgDetailValue: {
    color: theme.text,
    fontWeight: 600,
    fontSize: 12,
  },
  bgEventRow: {
    display: 'flex',
    gap: 12,
    fontSize: 11,
    padding: '2px 0',
  },
  bgEventTime: {
    fontFamily: 'monospace',
    fontSize: 10,
    color: theme.textMuted,
    flexShrink: 0,
  },
  bgEventStatus: {
    fontWeight: 600,
    color: theme.text,
    flexShrink: 0,
  },
  bgEventDetails: {
    color: theme.textMuted,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
}
