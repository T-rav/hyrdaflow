import React, { useState, useCallback, useMemo, lazy, Suspense } from 'react'
import { theme } from '../theme'
import { BACKGROUND_WORKERS, WORKER_GROUPS, INTERVAL_PRESETS, WORKER_PRESETS, EDITABLE_INTERVAL_WORKERS, SYSTEM_WORKER_INTERVALS, UNSTICK_BATCH_OPTIONS } from '../constants'
import { useHydraFlow } from '../context/HydraFlowContext'
import { Livestream } from './Livestream'
import { PipelineControlPanel } from './PipelineControlPanel'
import { WorkerLogStream } from './WorkerLogStream'
import { MetricsPanel } from './MetricsPanel'
import { InsightsPanel } from './InsightsPanel'
import { MemoryExplorer } from './memory/MemoryExplorer'

const DiagnosticsTab = lazy(() =>
  import('./diagnostics/DiagnosticsTab').then(m => ({ default: m.DiagnosticsTab }))
)

const SUB_TABS = [
  { key: 'workers', label: 'Workers' },
  { key: 'pipeline', label: 'Pipeline' },
  { key: 'metrics', label: 'Metrics' },
  { key: 'insights', label: 'Insights' },
  { key: 'memory', label: 'Memory' },
  { key: 'diagnostics', label: 'Diagnostics' },
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

function BackgroundWorkerCard({ def, state, pipelinePollerLastRun, pipelineIssues, orchestratorStatus, onToggleBgWorker, onTriggerBgWorker, onUpdateInterval, events, extraContent }) {
  const [showIntervalEditor, setShowIntervalEditor] = useState(false)
  const [triggerLoading, setTriggerLoading] = useState(false)
  const isPipelinePoller = def.key === 'pipeline_poller'
  const isSystem = def.system === true
  const orchRunning = orchestratorStatus === 'running'
  const isEditable = EDITABLE_INTERVAL_WORKERS.has(def.key)
  const presets = WORKER_PRESETS[def.key] ?? INTERVAL_PRESETS

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
        <span style={styles.status}>{statusText}</span>
        {def.tags && def.tags.map(tag => (
          <span key={tag} style={styles.tagPill}>{tag}</span>
        ))}
        {def.system && (
          <span style={styles.systemBadge}>system</span>
        )}
        {showToggle && (
          <button
            style={enabled ? styles.toggleOn : styles.toggleOff}
            onClick={() => onToggleBgWorker(def.key, !enabled)}
          >
            {enabled ? 'On' : 'Off'}
          </button>
        )}
        {onTriggerBgWorker && orchRunning && !isPipelinePoller && (
          <button
            style={triggerLoading ? styles.runNowLoading : styles.runNow}
            disabled={triggerLoading}
            data-testid={`run-now-${def.key}`}
            onClick={async () => {
              setTriggerLoading(true)
              try {
                await onTriggerBgWorker(def.key)
              } finally {
                setTriggerLoading(false)
              }
            }}
          >
            {triggerLoading ? 'Running\u2026' : 'Run Now'}
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

/** Workers organized by group key for the grouped layout. */
const WORKERS_BY_GROUP = WORKER_GROUPS.map(group => ({
  ...group,
  workers: BACKGROUND_WORKERS.filter(w => w.group === group.key),
}))

function UnstickWorkersDropdown() {
  const { config, selectedRepoSlug } = useHydraFlow()
  const [localValue, setLocalValue] = useState(null)

  const currentValue = localValue !== null ? localValue : (config?.pr_unstick_batch_size ?? 3)

  const handleChange = useCallback(async (e) => {
    const newValue = parseInt(e.target.value, 10)
    setLocalValue(newValue)
    try {
      const url = selectedRepoSlug
        ? `/api/control/config?repo=${encodeURIComponent(selectedRepoSlug)}`
        : '/api/control/config'
      const resp = await fetch(url, {
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
  }, [currentValue, selectedRepoSlug])

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


const KNOWN_BOTS = [
  { username: 'dependabot[bot]', label: 'Dependabot' },
  { username: 'renovate[bot]', label: 'Renovate' },
  { username: 'snyk-bot', label: 'Snyk' },
]

const FAILURE_STRATEGIES = [
  { value: 'skip', label: 'Skip' },
  { value: 'hitl', label: 'Escalate to HITL' },
  { value: 'close', label: 'Close PR' },
]

const REVIEW_MODES = [
  { value: 'ci_only', label: 'CI Only' },
  { value: 'llm_review', label: 'LLM Review' },
]

function DependabotMergeSettingsPanel() {
  const [settings, setSettings] = useState(null)
  const [customBot, setCustomBot] = useState('')

  const fetchSettings = useCallback(async () => {
    try {
      const resp = await fetch('/api/dependabot-merge/settings')
      if (resp.ok) {
        const data = await resp.json()
        setSettings(data)
      }
    } catch { /* ignore */ }
  }, [])

  React.useEffect(() => { fetchSettings() }, [fetchSettings])

  const saveSettings = useCallback(async (updated) => {
    setSettings(updated)
    try {
      await fetch('/api/dependabot-merge/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updated),
      })
    } catch { /* ignore */ }
  }, [])

  const toggleBot = useCallback((username) => {
    if (!settings) return
    const bots = settings.authors || []
    const next = bots.includes(username)
      ? bots.filter(b => b !== username)
      : [...bots, username]
    saveSettings({ ...settings, authors: next })
  }, [settings, saveSettings])

  const addCustomBot = useCallback(() => {
    const trimmed = customBot.trim()
    if (!trimmed || !settings) return
    const bots = settings.authors || []
    if (!bots.includes(trimmed)) {
      saveSettings({ ...settings, authors: [...bots, trimmed] })
    }
    setCustomBot('')
  }, [customBot, settings, saveSettings])

  if (!settings) return null

  const allowedBots = settings.authors || []

  return (
    <div style={styles.depMergePanel} data-testid="dependabot-merge-settings">
      <div style={styles.depMergeSection}>
        <div style={styles.depMergeSectionLabel}>Allowed Bots</div>
        {KNOWN_BOTS.map(bot => (
          <label key={bot.username} style={styles.depMergeCheckbox}>
            <input
              type="checkbox"
              checked={allowedBots.includes(bot.username)}
              onChange={() => toggleBot(bot.username)}
              data-testid={`bot-checkbox-${bot.username}`}
            />
            <span style={styles.depMergeCheckboxLabel}>{bot.label}</span>
          </label>
        ))}
        <div style={styles.depMergeAddRow}>
          <input
            type="text"
            value={customBot}
            onChange={e => setCustomBot(e.target.value)}
            placeholder="Custom bot username"
            style={styles.depMergeInput}
            data-testid="dependabot-merge-custom-input"
            onKeyDown={e => { if (e.key === 'Enter') addCustomBot() }}
          />
          <button
            onClick={addCustomBot}
            style={styles.depMergeAddBtn}
            data-testid="dependabot-merge-add-btn"
          >
            Add
          </button>
        </div>
      </div>
      <div style={styles.depMergeSection}>
        <div style={styles.depMergeSectionLabel}>Failure Strategy</div>
        {FAILURE_STRATEGIES.map(opt => (
          <label key={opt.value} style={styles.depMergeRadio}>
            <input
              type="radio"
              name="dependabot-merge-failure-strategy"
              value={opt.value}
              checked={settings.failure_strategy === opt.value}
              onChange={() => saveSettings({ ...settings, failure_strategy: opt.value })}
              data-testid={`failure-strategy-${opt.value}`}
            />
            <span style={styles.depMergeRadioLabel}>{opt.label}</span>
          </label>
        ))}
      </div>
      <div style={styles.depMergeSection}>
        <div style={styles.depMergeSectionLabel}>Review Mode</div>
        {REVIEW_MODES.map(opt => (
          <label key={opt.value} style={styles.depMergeRadio}>
            <input
              type="radio"
              name="dependabot-merge-review-mode"
              value={opt.value}
              checked={settings.review_mode === opt.value}
              onChange={() => saveSettings({ ...settings, review_mode: opt.value })}
              data-testid={`review-mode-${opt.value}`}
            />
            <span style={styles.depMergeRadioLabel}>{opt.label}</span>
          </label>
        ))}
      </div>
    </div>
  )
}


function WorkerGroupSection({ group, backgroundWorkers, pipelinePollerLastRun, pipelineIssues, orchestratorStatus, onToggleBgWorker, onTriggerBgWorker, onUpdateInterval, events }) {
  const [collapsed, setCollapsed] = useState(false)
  const workerCount = group.workers.length
  const activeCount = group.workers.filter(w => {
    const state = backgroundWorkers.find(s => s.name === w.key)
    return state && state.enabled !== false && state.status === 'ok'
  }).length

  return (
    <div style={styles.groupContainer}>
      <div
        style={styles.groupHeader}
        onClick={() => setCollapsed(!collapsed)}
        role="button"
        tabIndex={0}
        data-testid={`group-header-${group.key}`}
      >
        <span style={{ ...styles.groupDot, background: group.color }} />
        <span style={styles.groupLabel}>{group.label}</span>
        <span style={styles.groupCount}>{activeCount}/{workerCount}</span>
        <span style={styles.groupChevron}>{collapsed ? '\u25B6' : '\u25BC'}</span>
      </div>
      {!collapsed && (
        <div style={styles.grid}>
          {group.workers.map((def) => {
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
                onTriggerBgWorker={onTriggerBgWorker}
                onUpdateInterval={onUpdateInterval}
                events={events}
                extraContent={
                  def.key === 'dependabot_merge' ? <DependabotMergeSettingsPanel /> :
                  def.key === 'pr_unsticker' ? <UnstickWorkersDropdown /> :
                  undefined
                }
              />
            )
          })}
        </div>
      )}
    </div>
  )
}

export function SystemPanel({ backgroundWorkers, onToggleBgWorker, onTriggerBgWorker, onUpdateInterval }) {
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
            {WORKERS_BY_GROUP.map((group) => (
              <WorkerGroupSection
                key={group.key}
                group={group}
                backgroundWorkers={backgroundWorkers}
                pipelinePollerLastRun={pipelinePollerLastRun}
                pipelineIssues={pipelineIssues}
                orchestratorStatus={orchestratorStatus}
                onToggleBgWorker={onToggleBgWorker}
                onTriggerBgWorker={onTriggerBgWorker}
                onUpdateInterval={onUpdateInterval}
                events={events}
              />
            ))}
          </div>
        )}
        {activeSubTab === 'pipeline' && (
          <PipelineControlPanel onToggleBgWorker={onToggleBgWorker} />
        )}
        {activeSubTab === 'metrics' && (
          <MetricsPanel />
        )}
        {activeSubTab === 'insights' && <InsightsPanel />}
        {activeSubTab === 'memory' && <MemoryExplorer />}
        {activeSubTab === 'diagnostics' && (
          <Suspense fallback={<div style={styles.diagnosticsLoading}>Loading diagnostics…</div>}>
            <DiagnosticsTab />
          </Suspense>
        )}
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
  diagnosticsLoading: {
    padding: 32,
    textAlign: 'center',
    color: theme.dimText,
    fontSize: 13,
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
  runNow: {
    padding: '2px 10px',
    fontSize: 10,
    fontWeight: 600,
    border: `1px solid ${theme.accent}`,
    borderRadius: 10,
    background: theme.surface,
    color: theme.accent,
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  runNowLoading: {
    padding: '2px 10px',
    fontSize: 10,
    fontWeight: 600,
    border: `1px solid ${theme.border}`,
    borderRadius: 10,
    background: theme.surface,
    color: theme.textMuted,
    cursor: 'not-allowed',
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
  depMergePanel: {
    borderTop: `1px solid ${theme.border}`,
    paddingTop: 8,
    marginTop: 8,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  depMergeSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  depMergeSectionLabel: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.3px',
    marginBottom: 2,
  },
  depMergeCheckbox: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    cursor: 'pointer',
  },
  depMergeCheckboxLabel: {
    fontSize: 12,
    color: theme.text,
  },
  depMergeRadio: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    cursor: 'pointer',
  },
  depMergeRadioLabel: {
    fontSize: 12,
    color: theme.text,
  },
  depMergeAddRow: {
    display: 'flex',
    gap: 4,
    marginTop: 4,
  },
  depMergeInput: {
    flex: 1,
    padding: '4px 8px',
    fontSize: 12,
    border: `1px solid ${theme.border}`,
    borderRadius: 4,
    background: theme.surface,
    color: theme.text,
    outline: 'none',
  },
  depMergeAddBtn: {
    padding: '4px 12px',
    fontSize: 11,
    fontWeight: 600,
    border: `1px solid ${theme.accent}`,
    borderRadius: 4,
    background: theme.surface,
    color: theme.accent,
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  groupContainer: {
    marginBottom: 24,
  },
  groupHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '8px 0',
    cursor: 'pointer',
    userSelect: 'none',
    borderBottom: `1px solid ${theme.border}`,
    marginBottom: 12,
  },
  groupDot: {
    width: 10,
    height: 10,
    borderRadius: '50%',
    flexShrink: 0,
  },
  groupLabel: {
    fontSize: 14,
    fontWeight: 600,
    color: theme.textBright,
    flex: 1,
  },
  groupCount: {
    fontSize: 11,
    color: theme.textMuted,
    fontWeight: 600,
  },
  groupChevron: {
    fontSize: 10,
    color: theme.textMuted,
    width: 16,
    textAlign: 'center',
  },
  tagPill: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.textMuted,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: '1px 6px',
    textTransform: 'uppercase',
    letterSpacing: '0.3px',
  },
  systemBadge: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.accent,
    background: theme.accentSubtle,
    border: `1px solid ${theme.accent}`,
    borderRadius: 8,
    padding: '1px 6px',
    textTransform: 'uppercase',
    letterSpacing: '0.3px',
  },
}

// Pre-computed sub-tab style variants (avoids object spread in .map())
const subTabInactiveStyle = styles.subTab
const subTabActiveStyle = { ...styles.subTab, ...styles.subTabActive }
