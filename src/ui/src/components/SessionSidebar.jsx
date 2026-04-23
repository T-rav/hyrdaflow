import React, { useState, useCallback, useMemo } from 'react'
import { useHydraFlow } from '../context/HydraFlowContext'
import { theme } from '../theme'
import { canonicalRepoSlug } from '../constants'
import { RepoSelector } from './RepoSelector'
import { RegisterRepoDialog } from './RegisterRepoDialog'
import { formatRelative, formatDuration } from '../utils/timeFormat'

function pickLatestSession(sessions) {
  if (!sessions || sessions.length === 0) return null
  let latest = sessions[0]
  for (let i = 1; i < sessions.length; i++) {
    if ((sessions[i].started_at || '') > (latest.started_at || '')) {
      latest = sessions[i]
    }
  }
  return latest
}

function LastRunLine({ session, repoRunning, stageStatus }) {
  if (!session) {
    return <span style={styles.lastRunMuted}>never run</span>
  }

  const isActive = session.status === 'active'
  const succeededRaw = session.issues_succeeded ?? 0
  const failedRaw = session.issues_failed ?? 0

  if (isActive && repoRunning) {
    const now = new Date().toISOString()
    const duration = formatDuration(session.started_at, now)
    const succeeded = stageStatus?.workload?.done ?? succeededRaw
    const failed = stageStatus?.workload?.failed ?? failedRaw
    const parts = [`running · ${duration}`]
    if (succeeded > 0) parts.push(`${succeeded} ✓`)
    if (failed > 0) parts.push(`${failed} ✗`)
    return <span style={styles.lastRunRunning}>{parts.join(' · ')}</span>
  }

  if (isActive && !repoRunning) {
    const ago = formatRelative(session.started_at)
    return <span style={styles.lastRunMuted}>last run ended — {ago}</span>
  }

  const ago = formatRelative(session.ended_at || session.started_at)
  const duration = formatDuration(session.started_at, session.ended_at)
  const mainParts = [`ran ${ago}`]
  if (duration) mainParts.push(duration)
  const countParts = []
  if (succeededRaw > 0) countParts.push(`${succeededRaw} ✓`)
  if (failedRaw > 0) countParts.push(`${failedRaw} ✗`)
  const text = countParts.length > 0
    ? `${mainParts.join(' · ')} · ${countParts.join(' ')}`
    : mainParts.join(' · ')
  return <span style={styles.lastRunCompleted}>{text}</span>
}

export function SessionSidebar() {
  const {
    sessions,
    selectedRepoSlug,
    stageStatus,
    orchestratorStatus,
    selectRepo,
    supervisedRepos = [],
    runtimes = [],
    startRuntime,
    stopRuntime,
    removeRepoShortcut,
  } = useHydraFlow()
  const [registerModalOpen, setRegisterModalOpen] = useState(false)
  const openRegister = useCallback(() => setRegisterModalOpen(true), [])
  const closeRegister = useCallback(() => setRegisterModalOpen(false), [])

  const repoEntries = useMemo(() => {
    const entries = new Map()
    const slugIndex = new Map()

    const ensureEntry = (key, rawSlug, filterSlug, displayName) => {
      if (!entries.has(key)) {
        entries.set(key, {
          key,
          repoSlug: rawSlug || null,
          filterSlug,
          displayName,
          sessions: [],
          info: null,
          repoPath: null,
        })
        if (filterSlug) slugIndex.set(filterSlug, key)
      }
      return entries.get(key)
    }

    for (const session of sessions) {
      const canonical = canonicalRepoSlug(session.repo)
      const key = canonical || session.repo
      const entry = ensureEntry(key, session.repo, canonical, session.repo)
      entry.sessions.push(session)
    }

    for (const repo of supervisedRepos || []) {
      if (!repo) continue
      const rawSlug = repo.slug || repo.repo || repo.full_name || repo.path || ''
      const filterSlug = canonicalRepoSlug(rawSlug || repo.path || '')
      let entryKey = (filterSlug && slugIndex.get(filterSlug)) || filterSlug
      let entry = entryKey ? entries.get(entryKey) : undefined
      if (!entry) {
        entryKey = filterSlug || repo.path || repo.slug || `repo-${entries.size + 1}`
        entry = ensureEntry(
          entryKey,
          rawSlug,
          filterSlug,
          repo.slug || rawSlug || repo.path || entryKey,
        )
      }
      if (repo.slug) entry.repoSlug = repo.slug
      entry.repoPath = repo.path || entry.repoPath
      if (!entry.filterSlug) entry.filterSlug = filterSlug
      entry.info = repo
      if (filterSlug && !slugIndex.has(filterSlug)) slugIndex.set(filterSlug, entry.key)
      if (!entry.displayName && (repo.slug || repo.path)) {
        entry.displayName = repo.slug || repo.path
      }
    }

    const runtimeMap = new Map(
      (runtimes || []).map((rt) => [canonicalRepoSlug(rt.slug), rt]),
    )
    for (const entry of entries.values()) {
      entry.runtime = runtimeMap.get(entry.filterSlug) || null
      entry.latestSession = pickLatestSession(entry.sessions)
    }

    return Array.from(entries.values()).sort((a, b) =>
      (a.displayName || '').localeCompare(b.displayName || '')
    )
  }, [sessions, supervisedRepos, runtimes])

  const handleDisconnect = (e, slug, isRunning) => {
    e.stopPropagation()
    if (isRunning) {
      if (!window.confirm(`Repo "${slug}" is currently running. Disconnect anyway?`)) {
        return
      }
    }
    if (removeRepoShortcut) removeRepoShortcut(slug)
  }

  return (
    <div style={styles.sidebar}>
      <div style={styles.repoSelectorSection}>
        <RepoSelector onOpenRegister={openRegister} />
      </div>

      <div style={styles.list}>
        {repoEntries.map(entry => {
          const isRepoSelected = selectedRepoSlug === entry.filterSlug
          const rt = entry.runtime
          const isRunning = rt?.running ?? entry.info?.running ?? false
          const orchRunning = orchestratorStatus === 'running'
          const disabled = !orchRunning && !isRunning
          const slug = entry.repoSlug || entry.displayName

          return (
            <div
              key={entry.key}
              onClick={() => selectRepo(isRepoSelected ? null : entry.repoSlug)}
              style={isRepoSelected ? repoRowSelected : styles.repoRow}
            >
              <div style={styles.repoLineOne}>
                <span style={isRunning ? styles.repoDotRunning : styles.repoDotStopped} />
                <div style={styles.repoText}>
                  <span style={styles.repoName}>{entry.displayName}</span>
                  {entry.info?.path && entry.info.path !== entry.displayName && (
                    <span style={styles.repoSubLabel}>{entry.info.path}</span>
                  )}
                </div>
                <div style={styles.repoControls}>
                  {(entry.info || entry.runtime) && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (disabled) return
                        if (isRunning) stopRuntime(slug); else startRuntime(slug)
                      }}
                      disabled={disabled}
                      style={isRunning ? styles.runtimeStopBtn : disabled ? styles.runtimeDisabledBtn : styles.runtimeStartBtn}
                      aria-label={isRunning ? 'Stop repo' : 'Start repo'}
                      title={disabled ? 'Start the orchestrator first' : isRunning ? 'Stop processing' : 'Start processing'}
                    >
                      {isRunning ? '■' : '▶'}
                    </button>
                  )}
                  {entry.info && (
                    <button
                      onClick={(e) => handleDisconnect(e, slug, isRunning)}
                      style={styles.disconnectBtn}
                      aria-label="Disconnect repo"
                      title="Disconnect repo"
                    >
                      −
                    </button>
                  )}
                </div>
              </div>
              <div style={styles.repoLineTwo}>
                <LastRunLine
                  session={entry.latestSession}
                  repoRunning={isRunning}
                  stageStatus={stageStatus}
                />
              </div>
            </div>
          )
        })}

        {repoEntries.length === 0 && (
          <div style={styles.empty}>No repos connected</div>
        )}
      </div>
      <RegisterRepoDialog isOpen={registerModalOpen} onClose={closeRegister} />
    </div>
  )
}

const styles = {
  sidebar: {
    width: 280,
    flexShrink: 0,
    borderRight: `1px solid ${theme.border}`,
    background: theme.surface,
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
  },
  repoSelectorSection: {
    padding: '12px 12px 0',
  },
  list: {
    flex: 1,
    overflowY: 'auto',
    padding: '4px 0',
  },
  repoRow: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    padding: '8px 12px',
    cursor: 'pointer',
    borderBottom: `1px solid ${theme.border}`,
  },
  repoLineOne: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    minWidth: 0,
  },
  repoLineTwo: {
    fontSize: 10,
    color: theme.textMuted,
    paddingLeft: 14,
  },
  repoText: {
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
    flex: 1,
  },
  repoName: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  repoSubLabel: {
    fontSize: 10,
    fontWeight: 500,
    color: theme.textMuted,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  repoControls: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    flexShrink: 0,
  },
  repoDotRunning: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.green,
    flexShrink: 0,
  },
  repoDotStopped: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.textMuted,
    flexShrink: 0,
  },
  runtimeStartBtn: {
    background: 'none',
    border: 'none',
    color: theme.green,
    fontSize: 10,
    cursor: 'pointer',
    padding: '0 4px',
    lineHeight: 1,
    borderRadius: 4,
  },
  runtimeStopBtn: {
    background: 'none',
    border: 'none',
    color: theme.red,
    fontSize: 10,
    cursor: 'pointer',
    padding: '0 4px',
    lineHeight: 1,
    borderRadius: 4,
  },
  runtimeDisabledBtn: {
    background: 'none',
    border: 'none',
    color: theme.textMuted,
    fontSize: 10,
    cursor: 'not-allowed',
    padding: '0 4px',
    lineHeight: 1,
    borderRadius: 4,
    opacity: 0.4,
  },
  disconnectBtn: {
    background: 'none',
    border: 'none',
    color: theme.textMuted,
    fontSize: 14,
    fontWeight: 700,
    cursor: 'pointer',
    padding: '0 4px',
    lineHeight: 1,
    borderRadius: 4,
    flexShrink: 0,
  },
  lastRunMuted: {
    color: theme.textMuted,
  },
  lastRunCompleted: {
    color: theme.textMuted,
  },
  lastRunRunning: {
    color: theme.green,
    fontWeight: 600,
  },
  empty: {
    padding: '16px 12px',
    fontSize: 11,
    color: theme.textMuted,
    textAlign: 'center',
  },
}

const repoRowSelected = { ...styles.repoRow, background: theme.accentSubtle }
