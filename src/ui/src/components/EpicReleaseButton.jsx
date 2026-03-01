import React, { useState } from 'react'
import { theme } from '../theme'
import { PULSE_ANIMATION } from '../constants'
import { deriveReadiness } from './EpicReadinessChecklist'

/**
 * EpicReleaseButton — merge & release trigger for bundled/bundled_hitl epics.
 *
 * Props:
 *   epic: epic object with readiness + children data
 *   onRelease: (epicNumber) => Promise<{ ok, version?, error? }>
 *   releasing: { epicNumber, progress, total } | null — current release progress
 */
export function EpicReleaseButton({ epic, onRelease, releasing }) {
  const [showConfirm, setShowConfirm] = useState(false)
  const [error, setError] = useState(null)

  const checks = deriveReadiness(epic)
  const allReady = checks.every(c => c.passed)
  const isReleasing = releasing?.epicNumber === epic.epic_number
  const isAutoMerge = epic.merge_strategy === 'bundled'
  const prCount = epic.total_children || epic.children?.length || 0
  const version = epic.readiness?.version || 'next'

  const handleClick = () => {
    if (!allReady || isReleasing) return
    setShowConfirm(true)
    setError(null)
  }

  const handleConfirm = async () => {
    setShowConfirm(false)
    setError(null)
    if (onRelease) {
      try {
        const result = await onRelease(epic.epic_number)
        if (!result?.ok) {
          setError(result?.error || 'Release failed')
        }
      } catch (err) {
        setError(err.message || 'Release failed')
      }
    }
  }

  const handleCancel = () => {
    setShowConfirm(false)
  }

  // Releasing state — show progress
  if (isReleasing) {
    return (
      <div style={styles.container} data-testid="release-button">
        <div style={styles.releasingBtn}>
          <span style={styles.spinner} />
          Releasing...
          {releasing.total > 0 && (
            <span style={styles.progress}>
              {releasing.progress}/{releasing.total}
            </span>
          )}
        </div>
      </div>
    )
  }

  // Confirmation dialog
  if (showConfirm) {
    return (
      <div style={styles.container} data-testid="release-button">
        <div style={styles.confirmBox} data-testid="release-confirm">
          <span style={styles.confirmText}>
            Merge {prCount} PRs and create release v{version}?
          </span>
          <div style={styles.confirmActions}>
            <span
              role="button"
              tabIndex={0}
              style={styles.confirmBtn}
              onClick={handleConfirm}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleConfirm() } }}
              data-testid="release-confirm-yes"
            >
              Confirm
            </span>
            <span
              role="button"
              tabIndex={0}
              style={styles.cancelBtn}
              onClick={handleCancel}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleCancel() } }}
              data-testid="release-confirm-no"
            >
              Cancel
            </span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={styles.container} data-testid="release-button">
      <span
        role="button"
        tabIndex={allReady ? 0 : -1}
        style={allReady ? styles.enabledBtn : styles.disabledBtn}
        onClick={handleClick}
        onKeyDown={e => { if (allReady && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); handleClick() } }}
        title={allReady ? `Merge & Release v${version}` : 'Not all checks are passing'}
        data-testid="release-trigger"
      >
        {isAutoMerge ? 'Auto Merge & Release' : 'Merge & Release'}
      </span>
      {error && (
        <span style={styles.error} data-testid="release-error">{error}</span>
      )}
    </div>
  )
}

const btnBase = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  fontSize: 12,
  fontWeight: 700,
  padding: '6px 16px',
  borderRadius: 8,
  userSelect: 'none',
}

const styles = {
  container: {
    padding: '8px 0',
  },
  enabledBtn: { ...btnBase, background: theme.green, color: theme.white, cursor: 'pointer', transition: 'all 0.15s' },
  disabledBtn: { ...btnBase, background: theme.border, color: theme.textMuted, cursor: 'not-allowed' },
  releasingBtn: { ...btnBase, gap: 8, background: theme.greenSubtle, color: theme.green, animation: PULSE_ANIMATION },
  spinner: {
    display: 'inline-block',
    width: 12,
    height: 12,
    borderRadius: '50%',
    border: `2px solid ${theme.green}`,
    borderTopColor: 'transparent',
    animation: 'spin 0.8s linear infinite',
  },
  progress: {
    fontSize: 10,
    color: theme.textMuted,
  },
  confirmBox: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    padding: 12,
    borderRadius: 8,
    border: `1px solid ${theme.border}`,
    background: theme.surfaceInset,
  },
  confirmText: {
    fontSize: 12,
    fontWeight: 600,
    color: theme.text,
  },
  confirmActions: {
    display: 'flex',
    gap: 8,
  },
  confirmBtn: {
    fontSize: 11,
    fontWeight: 700,
    padding: '4px 12px',
    borderRadius: 6,
    background: theme.green,
    color: theme.white,
    cursor: 'pointer',
    transition: 'all 0.15s',
    userSelect: 'none',
  },
  cancelBtn: {
    fontSize: 11,
    fontWeight: 700,
    padding: '4px 12px',
    borderRadius: 6,
    background: theme.border,
    color: theme.textMuted,
    cursor: 'pointer',
    transition: 'all 0.15s',
    userSelect: 'none',
  },
  error: {
    display: 'block',
    fontSize: 11,
    color: theme.red,
    marginTop: 4,
  },
}
