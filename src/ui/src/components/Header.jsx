import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'
import { PIPELINE_STAGES, SENSITIVE_SELECTORS } from '../constants'
import { ReportIssueModal } from './ReportIssueModal'

function isCrossOriginImage(el) {
  if (!el || el.tagName !== 'IMG') return false
  const src = el.getAttribute('src') || ''
  if (!src || src.startsWith('data:') || src.startsWith('blob:')) return false
  try {
    const url = new URL(src, window.location.href)
    return url.origin !== window.location.origin
  } catch {
    return false
  }
}

function stripUnsupportedColorFunctions(value, fallback) {
  if (typeof value !== 'string') return value
  return value.includes('color(') ? fallback : value
}

/**
 * Redact elements marked with data-sensitive in a cloned DOM tree.
 * Replaces their innerHTML with a placeholder overlay so sensitive
 * content (transcripts, event logs) never appears in screenshots.
 */
function redactSensitiveElements(clonedRoot) {
  const selector = SENSITIVE_SELECTORS.join(',')
  clonedRoot.querySelectorAll(selector).forEach((el) => {
    el.innerHTML = ''
    el.style.setProperty('background', '#1a1a2e')
    el.style.setProperty('color', '#555')
    el.style.setProperty('display', 'flex')
    el.style.setProperty('align-items', 'center')
    el.style.setProperty('justify-content', 'center')
    el.style.setProperty('min-height', '40px')
    el.style.setProperty('font-size', '11px')
    el.style.setProperty('font-style', 'italic')
    el.textContent = '[Content redacted for security]'
  })
}

function sanitizeClonedDocumentForHtml2Canvas(clonedDoc) {
  // Drop stylesheet parsing in safe mode: this avoids unsupported CSS color() syntax.
  clonedDoc.querySelectorAll('style,link[rel="stylesheet"]').forEach((el) => el.remove())
  const fallbackColors = {
    color: '#c9d1d9',
    'background-color': '#0d1117',
    'border-color': '#30363d',
    'border-top-color': '#30363d',
    'border-right-color': '#30363d',
    'border-bottom-color': '#30363d',
    'border-left-color': '#30363d',
    'outline-color': '#30363d',
    'text-decoration-color': '#c9d1d9',
    fill: '#c9d1d9',
    stroke: '#c9d1d9',
  }

  clonedDoc.querySelectorAll('*').forEach((el) => {
    // Force safe baseline values so html2canvas parser does not encounter CSS Color 4
    // functions from computed styles (e.g. color(display-p3 ...)).
    el.style.setProperty('color', '#c9d1d9')
    el.style.setProperty('border-color', '#30363d')
    el.style.setProperty('box-shadow', 'none')

    Object.entries(fallbackColors).forEach(([prop, fallback]) => {
      const current = el.style.getPropertyValue(prop)
      if (!current) {
        // Ensure the parser sees deterministic values instead of inheriting
        // potentially unsupported color() values from user-agent/computed styles.
        el.style.setProperty(prop, fallback)
        return
      }
      el.style.setProperty(prop, stripUnsupportedColorFunctions(current, fallback))
    })
  })
}
async function captureDashboardScreenshot(root, html2canvas) {
  if (!root) return null
  const STYLE_PROPS = [
    'background-color', 'color', 'border-color', 'box-shadow',
    'border-bottom-color', 'border-top-color',
    'border-left-color', 'border-right-color',
  ]

  // Attempt 1: full fidelity capture with resolved CSS vars + cross-origin IMG filtering.
  try {
    const liveElements = root.querySelectorAll('*')
    const resolvedStyles = new Map()
    liveElements.forEach((el, i) => {
      const cs = getComputedStyle(el)
      const styles = {}
      STYLE_PROPS.forEach((prop) => {
        styles[prop] = cs.getPropertyValue(prop)
      })
      resolvedStyles.set(i, styles)
    })

    const first = await html2canvas(root, {
      useCORS: true,
      logging: false,
      backgroundColor: '#0d1117',
      scale: window.devicePixelRatio || 1,
      ignoreElements: isCrossOriginImage,
      onclone: (_doc, clonedEl) => {
        redactSensitiveElements(clonedEl)
        const clonedChildren = clonedEl.querySelectorAll('*')
        clonedChildren.forEach((el, i) => {
          const styles = resolvedStyles.get(i)
          if (!styles) return
          STYLE_PROPS.forEach((prop) => {
            if (styles[prop]) el.style.setProperty(prop, styles[prop])
          })
        })
      },
    })
    return first.toDataURL('image/png')
  } catch (firstErr) {
    console.warn('Primary screenshot capture failed, retrying with safe mode.', firstErr)
  }

  // Attempt 2: simpler safe-mode capture that skips style cloning complexity.
  try {
    const second = await html2canvas(root, {
      useCORS: true,
      logging: false,
      backgroundColor: '#0d1117',
      scale: 1,
      ignoreElements: isCrossOriginImage,
      onclone: (_doc, clonedEl) => {
        redactSensitiveElements(clonedEl)
      },
    })
    return second.toDataURL('image/png')
  } catch (secondErr) {
    console.warn('Safe-mode screenshot capture failed, retrying with sanitized clone.', secondErr)
  }

  // Attempt 3: aggressive sanitized clone fallback for browsers producing CSS color() values.
  try {
    const third = await html2canvas(root, {
      useCORS: true,
      logging: false,
      backgroundColor: '#0d1117',
      scale: 1,
      foreignObjectRendering: true,
      ignoreElements: isCrossOriginImage,
      onclone: (clonedDoc) => {
        redactSensitiveElements(clonedDoc)
        sanitizeClonedDocumentForHtml2Canvas(clonedDoc)
      },
    })
    return third.toDataURL('image/png')
  } catch (thirdErr) {
    console.error('Sanitized screenshot capture failed:', thirdErr)
    return null
  }
}

export function Header({
  connected, orchestratorStatus, creditsPausedUntil,
  onStart, onStop,
}) {
  const { stageStatus, config, submitReport, runtimes = [], supervisedRepos = [] } = useHydraFlow()
  const hasActiveWorkers = stageStatus.workload.active > 0
  const appVersion = config?.app_version || ''
  const latestVersion = config?.latest_version || ''
  const updateAvailable = Boolean(config?.update_available && latestVersion)

  // Track minimum stopping duration to prevent flicker
  const [stoppingHeld, setStoppingHeld] = useState(false)
  const stoppingTimer = useRef(null)

  useEffect(() => {
    if (orchestratorStatus === 'stopping') {
      setStoppingHeld(true)
      if (stoppingTimer.current) clearTimeout(stoppingTimer.current)
    } else if (stoppingHeld) {
      stoppingTimer.current = setTimeout(() => {
        setStoppingHeld(false)
      }, 1500)
    }
    return () => {
      if (stoppingTimer.current) clearTimeout(stoppingTimer.current)
    }
  }, [orchestratorStatus]) // eslint-disable-line react-hooks/exhaustive-deps

  // Clear held state early when workers confirm idle and status is not stopping
  useEffect(() => {
    if (!hasActiveWorkers && orchestratorStatus !== 'stopping') {
      if (stoppingTimer.current) clearTimeout(stoppingTimer.current)
      setStoppingHeld(false)
    }
  }, [hasActiveWorkers, orchestratorStatus])

  const isStopping = orchestratorStatus === 'stopping' || stoppingHeld
  const canStart = (orchestratorStatus === 'idle' || orchestratorStatus === 'done' || orchestratorStatus === 'auth_failed') &&
    !stoppingHeld
  const isRunning = orchestratorStatus === 'running'
  const isCreditsPaused = orchestratorStatus === 'credits_paused'

  const [reportModalOpen, setReportModalOpen] = useState(false)
  const [screenshotDataUrl, setScreenshotDataUrl] = useState(null)

  const handleReportClick = useCallback(async () => {
    // Capture screenshot BEFORE opening the modal so the overlay isn't in the shot.
    let dataUrl = null
    try {
      const mod = await import('html2canvas')
      const html2canvas = mod.default || mod
      const root = document.getElementById('root')
      dataUrl = await captureDashboardScreenshot(root, html2canvas)
    } catch (err) {
      console.error('Screenshot capture failed:', err)
    }
    setScreenshotDataUrl(dataUrl)
    setReportModalOpen(true)
  }, [])

  const handleReportSubmit = useCallback(async (data) => {
    if (submitReport) await submitReport(data)
  }, [submitReport])

  const totalRepos = supervisedRepos.length
  const supervisedSlugs = useMemo(
    () => new Set(supervisedRepos.map(r => r.slug)),
    [supervisedRepos]
  )
  const runningRepos = useMemo(
    () => runtimes.filter(rt => rt.running && supervisedSlugs.has(rt.slug)).length,
    [runtimes, supervisedSlugs]
  )

  const sessionStages = PIPELINE_STAGES.map((stage) => ({
    key: stage.key,
    count: stageStatus?.[stage.key]?.sessionCount || 0,
  }))

  return (
    <header style={styles.header}>
      <div style={styles.left}>
        <img src="/hydraflow-logo-small.png" alt="HydraFlow" style={styles.logoImg} />
        <div style={styles.logoGroup}>
          <span style={styles.logo}>HYDRAFLOW</span>
          <span style={styles.subtitle}>Intent in.</span>
          <span style={styles.subtitle}>Software out.</span>
          {appVersion && <span style={styles.version}>v{appVersion}</span>}
          {updateAvailable && (
            <span style={styles.updateNotice}>
              Update available: v{latestVersion} (`hf check-update`)
            </span>
          )}
        </div>
        <span style={connected ? dotConnected : dotDisconnected} />
      </div>
      <div style={styles.center}>
        <div style={styles.sessionBox}>
          <span style={styles.sessionLabel}>Session</span>
          <div style={styles.pipelineRow} data-testid="session-pipeline">
            {sessionStages.map((stage, index) => (
              <React.Fragment key={stage.key}>
                <div
                  style={pipelineStageStylesMap[stage.key]}
                  data-testid={`session-stage-${stage.key}`}
                >
                  <span style={pipelineLabelStylesMap[stage.key]}>
                    {stageAbbreviations[stage.key]}
                  </span>
                  <span style={styles.pipelineValue}>{stage.count}</span>
                </div>
                {index < sessionStages.length - 1 && (
                  <span style={styles.pipelineArrow}>→</span>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
      <div style={styles.controls}>
        {totalRepos > 0 && (
          <span
            style={runningRepos > 0 ? reposRunningBadgeActive : styles.reposRunningBadge}
            data-testid="repos-running-badge"
          >
            {runningRepos} / {totalRepos} {totalRepos === 1 ? 'repo' : 'repos'}
          </span>
        )}
        {canStart && (
          <button
            style={connected ? startBtnEnabled : startBtnDisabled}
            onClick={onStart}
            disabled={!connected}
          >
            Start
          </button>
        )}
        {isRunning && (
          <button style={styles.stopBtn} onClick={onStop}>
            Stop
          </button>
        )}
        {isCreditsPaused && (
          <>
            <span
              style={styles.creditsPausedBadge}
              title={creditsPausedUntil ? new Date(creditsPausedUntil).toString() : ''}
            >
              Credits Paused
              {creditsPausedUntil && (
                <span style={styles.creditResumeTime}>
                  {' · resumes '}
                  {new Date(creditsPausedUntil).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              )}
            </span>
            <button style={styles.stopBtn} onClick={onStop}>
              Stop
            </button>
          </>
        )}
        {isStopping && (
          <span style={styles.stoppingBadge}>
            Stopping…
          </span>
        )}
        <button
          style={connected ? styles.reportBtn : reportBtnDisabled}
          onClick={handleReportClick}
          disabled={!connected}
          data-testid="report-button"
        >
          Report
        </button>
      </div>
      <ReportIssueModal
        isOpen={reportModalOpen}
        screenshotDataUrl={screenshotDataUrl}
        onSubmit={handleReportSubmit}
        onClose={() => setReportModalOpen(false)}
      />
    </header>
  )
}

const styles = {
  header: {
    gridColumn: '1 / -1',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '20px 20px',
    background: theme.surface,
    borderBottom: `1px solid ${theme.border}`,
  },
  left: { display: 'flex', alignItems: 'flex-end', gap: 8, flexShrink: 0 },
  logoImg: { height: 56, width: 'auto' },
  logoGroup: { display: 'flex', flexDirection: 'column' },
  logo: { fontSize: 18, fontWeight: 700, color: theme.accent },
  subtitle: { color: theme.textMuted, fontWeight: 400, fontSize: 12 },
  version: { color: theme.textMuted, fontWeight: 500, fontSize: 11 },
  updateNotice: { color: theme.accent, fontWeight: 600, fontSize: 11 },
  dot: { width: 8, height: 8, borderRadius: '50%', display: 'inline-block' },
  center: {
    display: 'flex',
    alignItems: 'center',
    gap: 14,
    minWidth: 0,
    overflow: 'hidden',
  },
  sessionBox: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    gap: 8,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: '8px 14px',
    background: theme.bg,
  },
  sessionLabel: {
    color: theme.textMuted,
    fontSize: 13,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  pipelineRow: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
  },
  pipelineStage: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    borderRadius: 999,
    padding: '2px 8px',
    border: `1px solid ${theme.border}`,
    background: theme.surface,
  },
  pipelineLabel: {
    fontSize: 10,
    fontWeight: 600,
    letterSpacing: '0.5px',
    color: theme.textMuted,
  },
  pipelineValue: {
    fontSize: 13,
    fontWeight: 700,
    color: theme.textBright,
  },
  pipelineArrow: {
    color: theme.textMuted,
    fontSize: 12,
    fontWeight: 600,
  },
  controls: { display: 'flex', alignItems: 'center', gap: 10, marginLeft: 10, flexShrink: 0 },
  startBtn: {
    padding: '4px 14px',
    borderRadius: 6,
    border: 'none',
    background: theme.btnGreen,
    color: theme.white,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
  },
  stopBtn: {
    padding: '4px 14px',
    borderRadius: 6,
    border: 'none',
    background: theme.btnRed,
    color: theme.white,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
  },
  stoppingBadge: {
    padding: '4px 12px',
    borderRadius: 6,
    background: theme.yellow,
    color: theme.bg,
    fontSize: 12,
    fontWeight: 600,
  },
  creditsPausedBadge: {
    padding: '4px 12px',
    borderRadius: 6,
    background: theme.yellow,
    color: theme.bg,
    fontSize: 12,
    fontWeight: 600,
  },
  creditResumeTime: {
    fontWeight: 400,
    opacity: 0.85,
  },
  reposRunningBadge: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.textMuted,
    padding: '4px 8px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: theme.surface,
    whiteSpace: 'nowrap',
  },
  reportBtn: {
    padding: '4px 14px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: theme.surface,
    color: theme.textMuted,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
  },
}

// Pre-computed pipeline stage style maps (avoids object spread in render loops)
const abbreviateLabel = (label) => (label.length <= 4 ? label.toUpperCase() : label.slice(0, 3).toUpperCase())
export const stageAbbreviations = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, abbreviateLabel(s.label)]))
export const pipelineStageStylesMap = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, { ...styles.pipelineStage, borderColor: s.color }]))
export const pipelineLabelStylesMap = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, { ...styles.pipelineLabel, color: s.color }]))

// Pre-computed connection dot variants
export const dotConnected = { ...styles.dot, background: theme.green }
export const dotDisconnected = { ...styles.dot, background: theme.red }

// Pre-computed start button variants
export const startBtnEnabled = { ...styles.startBtn, opacity: 1, cursor: 'pointer' }
export const startBtnDisabled = { ...styles.startBtn, opacity: 0.4, cursor: 'not-allowed' }

// Pre-computed report button variant
const reportBtnDisabled = { ...styles.reportBtn, opacity: 0.4, cursor: 'not-allowed' }

// Pre-computed repos running badge variant
const reposRunningBadgeActive = { ...styles.reposRunningBadge, color: theme.green, borderColor: theme.green }
