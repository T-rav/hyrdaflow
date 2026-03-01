import React, { useState, useCallback, useMemo } from 'react'
import { theme } from '../theme'
import { BACKGROUND_WORKERS, INTERVAL_PRESETS, PIPELINE_POLLER_PRESETS, EDITABLE_INTERVAL_WORKERS, SYSTEM_WORKER_INTERVALS, UNSTICK_BATCH_OPTIONS } from '../constants'
import { useHydraFlow } from '../context/HydraFlowContext'
import { Livestream } from './Livestream'
import { PipelineControlPanel } from './PipelineControlPanel'
import { WorkerLogStream } from './WorkerLogStream'
import { MetricsPanel } from './MetricsPanel'
import { InsightsPanel } from './InsightsPanel'

const SUB_TABS = [
  { key: 'workers', label: 'Workers' },
  { key: 'pipeline', label: 'Pipeline' },
  { key: 'metrics', label: 'Metrics' },
  { key: 'insights', label: 'Insights' },
  { key: 'livestream', label: 'Livestream' },
]

function relativeTime(isoString) {
  if (!isoString) return 'never'
  const diff = Date.now() - new Date(isoString).getTime()
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ago`
}

export function formatInterval(seconds) {
  if (seconds == null) return null
  if (seconds < 60) return `every ${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `every ${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remainMinutes = minutes % 60
  if (remainMinutes === 0) return `every ${hours}h`
  return `every ${hours}h ${remainMinutes}m`
}

export function formatNextRun(lastRun, intervalSeconds) {
  if (!lastRun || !intervalSeconds) return null
  const nextTime = new Date(lastRun).getTime() + intervalSeconds * 1000
  const diff = nextTime - Date.now()
  if (diff <= 0) return 'now'
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `in ${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `in ${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remainMinutes = minutes % 60
  if (remainMinutes === 0) return `in ${hours}h`
  return `in ${hours}h ${remainMinutes}m`
}

function statusColor(status) {
  if (status === 'ok') return theme.green
  if (status === 'error') return theme.red
  return theme.textInactive
}

function formatTimestamp(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function BackgroundWorkerCard({ def, state, pipelinePollerLastRun, pipelineIssues, orchestratorStatus, onToggleBgWorker, onUpdateInterval, events, extraContent }) {
  const [showIntervalEditor, setShowIntervalEditor] = useState(false)
  const isPipelinePoller = def.key === 'pipeline_poller'
  const isSystem = def.system === true
  const orchRunning = orchestratorStatus === 'running'
  const isEditable = EDITABLE_INTERVAL_WORKERS.has(def.key)
  const presets = isPipelinePoller ? PIPELINE_POLLER_PRESETS : INTERVAL_PRESETS

  let dotColor, statusText, lastRun, details

  if (!orchRunning) {
    // Orchestrator not running — system workers stopped, non-system show toggle state
    lastRun = isPipelinePoller ? (pipelinePollerLastRun || null) : (state?.last_run || null)
    details = state?.details || {}
    if (isSystem) {
      dotColor = theme.red
      statusText = 'stopped'
    } else if (state?.enabled === false) {
      dotColor = theme.red
      statusText = 'off'
    } else {
      dotColor = theme.yellow
      statusText = 'idle'
    }
  } else if (isPipelinePoller) {
    // Pipeline poller is frontend-only — derive details from pipeline snapshot
    lastRun = pipelinePollerLastRun || null
    const pi = pipelineIssues || {}
    const triageCount = (pi.triage || []).length
    const planCount = (pi.plan || []).length
    const implementCount = (pi.implement || []).length
    const reviewCount = (pi.review || []).length
    const hitlCount = (pi.hitl || []).length
    const total = triageCount + planCount + implementCount + reviewCount
    details = { triage: triageCount, plan: planCount, implement: implementCount, review: reviewCount, hitl: hitlCount, total }
    dotColor = lastRun ? theme.green : theme.textInactive
    statusText = lastRun ? 'ok' : 'idle'
  } else if (isSystem) {
    // System workers: ok/error based on backend state
    if (!state || !state.status || state.status === 'disabled') {
      dotColor = theme.green
      statusText = 'ok'
    } else {
      dotColor = statusColor(state.status)
      statusText = state.status
    }
    lastRun = state?.last_run || null
    details = state?.details || {}
  } else if (!state) {
    dotColor = theme.yellow
    statusText = 'idle'
    lastRun = null
    details = {}
  } else if (state.enabled === false) {
    dotColor = theme.red
    statusText = 'off'
    lastRun = state.last_run || null
    details = state.details || {}
  } else {
    dotColor = statusColor(state.status || 'ok')
    statusText = state.status || 'ok'
    lastRun = state.last_run || null
    details = state.details || {}
  }

  const logLines = useMemo(() => {
    if (!events || events.length === 0) return []
    return events
      .filter(e => e.type === 'background_worker_status' && e.data?.worker === def.key)
      .slice(0, 15)
      .reverse()
      .map(e => {
        const time = formatTimestamp(e.timestamp)
        const status = e.data?.status || ''
        const det = e.data?.details
          ? Object.entries(e.data.details).map(([k, v]) => `${k}: ${v}`).join(', ')
          : ''
        return det ? `${time} ${status} \u00b7 ${det}` : `${time} ${status}`
      })
  }, [events, def.key])

  const effectiveInterval = state?.interval_seconds ?? SYSTEM_WORKER_INTERVALS[def.key] ?? null
  const enabled = !isSystem && (state ? state.enabled !== false : true)
  const showToggle = onToggleBgWorker && !isSystem
  const isError = statusText === 'error' || statusText === 'stopped'
  const hasDetails = Object.keys(details).length > 0
  const description = state?.description || def.description || ''
  return (
    <div style={styles.card} data-testid={`worker-card-${def.key}`}>
      <div style={styles.cardHeader}>
        <span
          style={{ ...styles.dot, background: dotColor }}
          data-testid={`dot-${def.key}`}
        />
        <span style={styles.label}>{def.label}</span>
        {isSystem ? (
          <span
            style={statusText === 'ok'
              ? styles.statusPillOk
              : styles.statusPillError}
            data-testid={`status-pill-${def.key}`}
          >
            {statusText}
          </span>
        ) : (
          <span style={styles.status}>{statusText}</span>
        )}
        {showToggle && (
          <button
            style={enabled ? styles.toggleOn : styles.toggleOff}
            onClick={() => onToggleBgWorker(def.key, !enabled)}
          >
            {enabled ? 'On' : 'Off'}
          </button>
        )}
      </div>
      {description && (
        <div style={styles.description} data-testid={`desc-${def.key}`}>
          {description}
        </div>
      )}
      <div style={styles.lastRun}>
        Last run: {relativeTime(lastRun)}
      </div>
      {effectiveInterval != null && (
        <div style={styles.scheduleRow} data-testid={`schedule-${def.key}`}>
          <span style={styles.scheduleText}>
            Runs {formatInterval(effectiveInterval)}
          </span>
          {lastRun && (
            <span style={styles.nextRunText}>
              {' \u00b7 Next '}{formatNextRun(lastRun, effectiveInterval)}
            </span>
          )}
          {isEditable && onUpdateInterval && (
            <span
              style={styles.editIntervalLink}
              onClick={() => setShowIntervalEditor(!showIntervalEditor)}
              data-testid={`edit-interval-${def.key}`}
            >
              {showIntervalEditor ? 'close' : 'edit'}
            </span>
          )}
        </div>
      )}
      {showIntervalEditor && isEditable && onUpdateInterval && (
        <div style={styles.intervalEditor} data-testid={`interval-editor-${def.key}`}>
          {presets.map((preset) => (
            <button
              key={preset.seconds}
              style={state?.interval_seconds === preset.seconds ? styles.presetActive : styles.presetButton}
              onClick={() => {
                onUpdateInterval(def.key, preset.seconds)
                setShowIntervalEditor(false)
              }}
              data-testid={`preset-${preset.label}`}
            >
              {preset.label}
            </button>
          ))}
        </div>
      )}
      {hasDetails && !isPipelinePoller && (
        <div style={isError ? (logLines.length > 0 ? styles.detailsErrorCompact : styles.detailsError) : styles.details}>
          {Object.entries(details).map(([k, v]) => (
            <div key={k} style={k === 'error' ? styles.errorRow : styles.detailRow}>
              <span style={isError ? styles.detailKeyError : styles.detailKey}>{k.replace(/_/g, ' ')}</span>
              <span style={isError ? styles.detailValueError : styles.detailValue}>{String(v)}</span>
            </div>
          ))}
        </div>
      )}
      {logLines.length > 0 && (
        <WorkerLogStream lines={logLines} />
      )}
      {extraContent}
    </div>
  )
}

const NON_SYSTEM_WORKERS = BACKGROUND_WORKERS.filter(w => !w.system)
const SYSTEM_WORKERS = BACKGROUND_WORKERS.filter(w => w.system)

function MemoryAutoApproveToggle() {
  const { config } = useHydraFlow()
  const [localEnabled, setLocalEnabled] = useState(null)

  const isEnabled = localEnabled !== null ? localEnabled : (config?.memory_auto_approve ?? false)

  const handleToggle = useCallback(async () => {
    const newValue = !isEnabled
    setLocalEnabled(newValue)
    try {
      const resp = await fetch('/api/control/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memory_auto_approve: newValue, persist: true }),
      })
      if (!resp.ok) {
        setLocalEnabled(isEnabled)
      }
    } catch {
      setLocalEnabled(isEnabled)
    }
  }, [isEnabled])

  return (
    <div style={styles.autoApproveRow}>
      <div style={styles.autoApproveLabel}>
        <span style={styles.autoApproveText}>Memory Auto-Approve</span>
        <span style={styles.autoApproveHint}>
          Skip HITL queue for memory suggestions
        </span>
      </div>
      <button
        style={isEnabled ? styles.toggleOn : styles.toggleOff}
        onClick={handleToggle}
        data-testid="memory-auto-approve-toggle"
      >
        {isEnabled ? 'On' : 'Off'}
      </button>
    </div>
  )
}

function ToggleRow({ label, hint, enabled, onToggle, testId }) {
  return (
    <div style={styles.autoApproveRow}>
      <div style={styles.autoApproveLabel}>
        <span style={styles.autoApproveText}>{label}</span>
        <span style={styles.autoApproveHint}>{hint}</span>
      </div>
      <button
        style={enabled ? styles.toggleOn : styles.toggleOff}
        onClick={onToggle}
        data-testid={testId}
      >
        {enabled ? 'On' : 'Off'}
      </button>
    </div>
  )
}

function ProcessToggles() {
  const { config } = useHydraFlow()
  const [localEpics, setLocalEpics] = useState(null)
  const [localBugs, setLocalBugs] = useState(null)

  const epicsOn = localEpics !== null ? localEpics : (config?.auto_process_epics ?? false)
  const bugsOn = localBugs !== null ? localBugs : (config?.auto_process_bug_reports ?? false)

  const toggle = useCallback(async (field, current, setLocal) => {
    const next = !current
    setLocal(next)
    try {
      const resp = await fetch('/api/control/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [field]: next, persist: true }),
      })
      if (!resp.ok) setLocal(current)
    } catch { setLocal(current) }
  }, [])

  return (
    <div style={styles.processTogglesSection}>
      <h3 style={styles.sectionHeading}>Process Toggles</h3>
      <ToggleRow
        label="Auto Process Epics"
        hint="When off, epics go to HITL for review"
        enabled={epicsOn}
        onToggle={() => toggle('auto_process_epics', epicsOn, setLocalEpics)}
        testId="auto-process-epics-toggle"
      />
      <ToggleRow
        label="Auto Process Bug Reports"
        hint="When off, bug reports go to HITL for review"
        enabled={bugsOn}
        onToggle={() => toggle('auto_process_bug_reports', bugsOn, setLocalBugs)}
        testId="auto-process-bugs-toggle"
      />
    </div>
  )
}

function UnstickWorkersDropdown() {
  const { config } = useHydraFlow()
  const [localValue, setLocalValue] = useState(null)

  const currentValue = localValue !== null ? localValue : (config?.pr_unstick_batch_size ?? 3)

  const handleChange = useCallback(async (e) => {
    const newValue = parseInt(e.target.value, 10)
    setLocalValue(newValue)
    try {
      const resp = await fetch('/api/control/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pr_unstick_batch_size: newValue, persist: true }),
      })
      if (!resp.ok) {
        setLocalValue(currentValue)
      }
    } catch {
      setLocalValue(currentValue)
    }
  }, [currentValue])

  return (
    <div style={styles.autoApproveRow}>
      <div style={styles.autoApproveLabel}>
        <span style={styles.autoApproveText}>Max PRs</span>
        <span style={styles.autoApproveHint}>
          PRs to unstick per cycle
        </span>
      </div>
      <select
        value={currentValue}
        onChange={handleChange}
        style={styles.workersSelect}
        data-testid="unstick-workers-dropdown"
      >
        {UNSTICK_BATCH_OPTIONS.map(n => (
          <option key={n} value={n}>{n}</option>
        ))}
      </select>
    </div>
  )
}

export function SystemPanel({ backgroundWorkers, onToggleBgWorker, onUpdateInterval }) {
  const { pipelinePollerLastRun, orchestratorStatus, events, pipelineIssues } = useHydraFlow()
  const [activeSubTab, setActiveSubTab] = useState('workers')

  return (
    <div style={styles.container}>
      <div style={styles.subTabSidebar}>
        {SUB_TABS.map(tab => (
          <div
            key={tab.key}
            role="tab"
            aria-selected={activeSubTab === tab.key}
            onClick={() => setActiveSubTab(tab.key)}
            data-testid={`system-subtab-${tab.key}`}
            style={activeSubTab === tab.key ? subTabActiveStyle : subTabInactiveStyle}
          >
            {tab.label}
          </div>
        ))}
      </div>
      <div style={styles.subTabContent} data-testid="system-subtab-content">
        {activeSubTab === 'workers' && (
          <div style={styles.workersContent}>
            <h3 style={styles.heading}>Background Workers</h3>
            <div style={styles.grid}>
              {NON_SYSTEM_WORKERS.map((def) => {
                const state = backgroundWorkers.find(w => w.name === def.key)
                return (
                  <BackgroundWorkerCard
                    key={def.key}
                    def={def}
                    state={state}
                    pipelinePollerLastRun={pipelinePollerLastRun}
                    orchestratorStatus={orchestratorStatus}
                    onToggleBgWorker={onToggleBgWorker}
                    onUpdateInterval={onUpdateInterval}
                    events={events}
                  />
                )
              })}
            </div>
            <h3 style={styles.sectionHeading}>System</h3>
            <div style={styles.grid}>
              {SYSTEM_WORKERS.map((def) => {
                const state = backgroundWorkers.find(w => w.name === def.key)
                return (
                  <BackgroundWorkerCard
                    key={def.key}
                    def={def}
                    state={state}
                    pipelinePollerLastRun={pipelinePollerLastRun}
                    pipelineIssues={pipelineIssues}
                    orchestratorStatus={orchestratorStatus}
                    onToggleBgWorker={onToggleBgWorker}
                    onUpdateInterval={onUpdateInterval}
                    events={events}
                    extraContent={
                      def.key === 'memory_sync' ? <MemoryAutoApproveToggle /> :
                      def.key === 'pr_unsticker' ? <UnstickWorkersDropdown /> :
                      undefined
                    }
                  />
                )
              })}
            </div>
            <ProcessToggles />
          </div>
        )}
        {activeSubTab === 'pipeline' && (
          <PipelineControlPanel onToggleBgWorker={onToggleBgWorker} />
        )}
        {activeSubTab === 'metrics' && (
          <MetricsPanel />
        )}
        {activeSubTab === 'insights' && <InsightsPanel />}
        {activeSubTab === 'livestream' && <Livestream events={events} />}
      </div>
    </div>
  )
}

const styles = {
  container: {
    flex: 1,
    display: 'flex',
    overflow: 'hidden',
  },
  subTabSidebar: {
    width: 100,
    flexShrink: 0,
    borderRight: `1px solid ${theme.border}`,
    background: theme.surface,
    paddingTop: 12,
  },
  subTab: {
    padding: '8px 16px',
    fontSize: 12,
    fontWeight: 600,
    color: theme.textMuted,
    cursor: 'pointer',
    transition: 'all 0.15s',
    borderLeftWidth: 2,
    borderLeftStyle: 'solid',
    borderLeftColor: 'transparent',
  },
  subTabActive: {
    color: theme.accent,
    borderLeftColor: theme.accent,
  },
  subTabContent: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  workersContent: {
    flex: 1,
    overflowY: 'auto',
    padding: 20,
  },
  heading: {
    fontSize: 16,
    fontWeight: 600,
    color: theme.textBright,
    marginBottom: 16,
    marginTop: 0,
  },
  sectionHeading: {
    fontSize: 13,
    fontWeight: 600,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    marginTop: 24,
    marginBottom: 12,
    borderTop: `1px solid ${theme.border}`,
    paddingTop: 16,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: 16,
  },
  card: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 16,
    background: theme.surface,
    overflow: 'hidden',
    minWidth: 0,
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    flexShrink: 0,
  },
  label: {
    fontSize: 14,
    fontWeight: 600,
    color: theme.text,
    flex: 1,
  },
  status: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.textMuted,
    textTransform: 'uppercase',
  },
  description: {
    fontSize: 12,
    color: theme.textMuted,
    lineHeight: 1.35,
    marginBottom: 6,
  },
  lastRun: {
    fontSize: 12,
    color: theme.textMuted,
    marginBottom: 8,
  },
  details: {
    borderTop: `1px solid ${theme.border}`,
    paddingTop: 8,
  },
  detailsError: {
    borderTop: `1px solid ${theme.red}`,
    paddingTop: 8,
    background: theme.redSubtle,
    margin: '0 -16px -16px',
    padding: '8px 16px 16px',
    borderRadius: '0 0 8px 8px',
  },
  detailsErrorCompact: {
    borderTop: `1px solid ${theme.red}`,
    background: theme.redSubtle,
    margin: '0 -16px 0',
    padding: '8px 16px',
  },
  detailRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 11,
    padding: '2px 0',
  },
  errorRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 11,
    padding: '2px 0',
  },
  detailKey: {
    color: theme.textMuted,
    textTransform: 'capitalize',
  },
  detailValue: {
    color: theme.text,
    fontWeight: 600,
  },
  detailKeyError: {
    color: theme.red,
    textTransform: 'capitalize',
  },
  detailValueError: {
    color: theme.red,
    fontWeight: 600,
  },
  toggleOn: {
    padding: '2px 10px',
    fontSize: 10,
    fontWeight: 600,
    border: `1px solid ${theme.green}`,
    borderRadius: 10,
    background: theme.greenSubtle,
    color: theme.green,
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  toggleOff: {
    padding: '2px 10px',
    fontSize: 10,
    fontWeight: 600,
    border: `1px solid ${theme.border}`,
    borderRadius: 10,
    background: theme.surface,
    color: theme.textMuted,
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  statusPillOk: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.green,
    background: theme.greenSubtle,
    border: `1px solid ${theme.green}`,
    borderRadius: 10,
    padding: '1px 8px',
    textTransform: 'uppercase',
  },
  statusPillError: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.red,
    background: theme.redSubtle,
    border: `1px solid ${theme.red}`,
    borderRadius: 10,
    padding: '1px 8px',
    textTransform: 'uppercase',
  },
  scheduleRow: {
    fontSize: 11,
    color: theme.textMuted,
    marginBottom: 8,
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    flexWrap: 'wrap',
  },
  scheduleText: {
    color: theme.textMuted,
  },
  nextRunText: {
    color: theme.textMuted,
  },
  editIntervalLink: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.accent,
    cursor: 'pointer',
    marginLeft: 4,
  },
  intervalEditor: {
    display: 'flex',
    gap: 4,
    marginBottom: 8,
    flexWrap: 'wrap',
  },
  presetButton: {
    padding: '2px 8px',
    fontSize: 10,
    fontWeight: 600,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    color: theme.textMuted,
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  presetActive: {
    padding: '2px 8px',
    fontSize: 10,
    fontWeight: 600,
    border: `1px solid ${theme.accent}`,
    borderRadius: 8,
    background: theme.accentSubtle,
    color: theme.accent,
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  processTogglesSection: {
    marginTop: 24,
    borderTop: `1px solid ${theme.border}`,
    paddingTop: 16,
  },
  autoApproveRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderTop: `1px solid ${theme.border}`,
    paddingTop: 8,
    marginTop: 8,
  },
  autoApproveLabel: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  },
  autoApproveText: {
    fontSize: 13,
    fontWeight: 600,
    color: theme.text,
  },
  autoApproveHint: {
    fontSize: 11,
    color: theme.textMuted,
  },
  workersSelect: {
    padding: '2px 8px',
    fontSize: 12,
    fontWeight: 600,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    color: theme.text,
    cursor: 'pointer',
    outline: 'none',
  },
}

// Pre-computed sub-tab style variants (avoids object spread in .map())
const subTabInactiveStyle = styles.subTab
const subTabActiveStyle = { ...styles.subTab, ...styles.subTabActive }
