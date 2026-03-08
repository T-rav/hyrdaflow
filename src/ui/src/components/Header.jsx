import React, { useState, useCallback } from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'
import { PIPELINE_STAGES, SENSITIVE_SELECTORS } from '../constants'
import { ReportIssueModal } from './ReportIssueModal'
import { RepoSelector } from './RepoSelector'
import { RegisterRepoDialog } from './RegisterRepoDialog'

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
const MAX_SCREENSHOT_WIDTH = 1280

/**
 * Downscale a canvas to MAX_SCREENSHOT_WIDTH if it exceeds that width.
 * Returns a data URL of the (possibly resized) image.
 */
function downscaleCanvas(source) {
  if (source.width <= MAX_SCREENSHOT_WIDTH) {
    return source.toDataURL('image/png')
  }
  const ratio = MAX_SCREENSHOT_WIDTH / source.width
  const w = MAX_SCREENSHOT_WIDTH
  const h = Math.round(source.height * ratio)
  const offscreen = document.createElement('canvas')
  offscreen.width = w
  offscreen.height = h
  const ctx = offscreen.getContext('2d')
  ctx.drawImage(source, 0, 0, w, h)
  return offscreen.toDataURL('image/png')
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
    return downscaleCanvas(first)
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
    return downscaleCanvas(second)
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
    return downscaleCanvas(third)
  } catch (thirdErr) {
    console.error('Sanitized screenshot capture failed:', thirdErr)
    return null
  }
}

export function Header({ connected, orchestratorStatus }) {
  const {
    stageStatus,
    config,
    submitReport,
    startOrchestrator,
    stopOrchestrator,
  } = useHydraFlow()
  const appVersion = config?.app_version || ''
  const latestVersion = config?.latest_version || ''
  const updateAvailable = Boolean(config?.update_available && latestVersion)

  const [reportModalOpen, setReportModalOpen] = useState(false)
  const [registerModalOpen, setRegisterModalOpen] = useState(false)
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

  const openRegister = useCallback(() => {
    setRegisterModalOpen(true)
  }, [])

  const closeRegister = useCallback(() => {
    setRegisterModalOpen(false)
  }, [])

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
        <div style={styles.sessionBox} data-testid="session-box" aria-label="Session pipeline statistics">
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
      <div style={styles.selectorWrap}>
        <RepoSelector onOpenRegister={openRegister} />
      </div>
      <div style={styles.controls}>
        {orchestratorStatus === 'running' ? (
          <button
            style={connected ? styles.controlStopBtn : controlBtnDisabled}
            onClick={() => stopOrchestrator?.()}
            disabled={!connected}
            data-testid="header-stop-button"
          >
            Stop
          </button>
        ) : orchestratorStatus === 'stopping' ? (
          <span style={styles.controlStoppingBadge}>Stopping…</span>
        ) : (
          <button
            style={connected ? styles.controlStartBtn : controlBtnDisabled}
            onClick={() => startOrchestrator?.()}
            disabled={!connected}
            data-testid="header-start-button"
          >
            Start
          </button>
        )}
        <button
          style={connected ? styles.reportBtn : reportBtnDisabled}
          onClick={handleReportClick}
          disabled={!connected}
          data-testid="report-button"
          aria-label="Report issue"
          title="Report issue"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path d="M4.72.22a.75.75 0 0 1 1.06 0l1 .999a3.488 3.488 0 0 1 2.441 0l.999-1a.748.748 0 0 1 1.265.332.75.75 0 0 1-.205.729l-.775.776c.616.63.995 1.493.995 2.444v.327c0 .1-.009.197-.025.292.408.14.764.392 1.029.722l1.968-.787a.75.75 0 0 1 .556 1.392L13 7.258V9h2.25a.75.75 0 0 1 0 1.5H13v.5c0 .409-.049.806-.141 1.186l2.17.868a.75.75 0 0 1-.557 1.392l-2.184-.873A4.997 4.997 0 0 1 8 16a4.997 4.997 0 0 1-4.288-2.427l-2.183.873a.75.75 0 0 1-.558-1.392l2.17-.868A5.036 5.036 0 0 1 3 11v-.5H.75a.75.75 0 0 1 0-1.5H3V7.258L.971 6.446a.75.75 0 0 1 .558-1.392l1.967.787c.265-.33.62-.583 1.03-.722a1.677 1.677 0 0 1-.026-.292V4.5c0-.951.38-1.814.995-2.444L4.72 1.28a.75.75 0 0 1 0-1.06Zm.53 6.28a.75.75 0 0 0-.75.75V11a3.5 3.5 0 1 0 7 0V7.25a.75.75 0 0 0-.75-.75ZM6.173 5h3.654A.172.172 0 0 0 10 4.827V4.5a2 2 0 1 0-4 0v.327c0 .096.077.173.173.173Z" fill="currentColor" />
          </svg>
        </button>
      </div>
      <ReportIssueModal
        isOpen={reportModalOpen}
        screenshotDataUrl={screenshotDataUrl}
        onSubmit={handleReportSubmit}
        onClose={() => setReportModalOpen(false)}
      />
      <RegisterRepoDialog
        isOpen={registerModalOpen}
        onClose={closeRegister}
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
  selectorWrap: {
    width: 220,
    paddingLeft: 12,
    paddingRight: 12,
    flexShrink: 0,
  },
  sessionBox: {
    display: 'flex',
    alignItems: 'flex-start',
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: '8px 14px',
    background: theme.bg,
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
  controlStartBtn: {
    padding: '6px 12px',
    borderRadius: 6,
    border: `1px solid ${theme.green}`,
    background: theme.greenSubtle,
    color: theme.green,
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
  },
  controlStopBtn: {
    padding: '6px 12px',
    borderRadius: 6,
    border: `1px solid ${theme.red}`,
    background: theme.redSubtle,
    color: theme.red,
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
  },
  controlStoppingBadge: {
    fontSize: 12,
    fontWeight: 700,
    color: theme.yellow,
    border: `1px solid ${theme.yellow}`,
    background: theme.yellowSubtle,
    borderRadius: 6,
    padding: '6px 10px',
    whiteSpace: 'nowrap',
  },
  reportBtn: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 6,
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: theme.surface,
    color: theme.textMuted,
    cursor: 'pointer',
    transition: 'opacity 0.15s',
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

// Pre-computed report button variant
const reportBtnDisabled = { ...styles.reportBtn, opacity: 0.4, cursor: 'not-allowed' }
const controlBtnDisabled = {
  ...styles.controlStartBtn,
  opacity: 0.4,
  cursor: 'not-allowed',
  borderColor: theme.border,
  color: theme.textInactive,
}
