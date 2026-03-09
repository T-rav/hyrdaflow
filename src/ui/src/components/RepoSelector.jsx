import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useHydraFlow } from '../context/HydraFlowContext'
import { canonicalRepoSlug } from '../constants'
import { theme } from '../theme'

function buildDisplayName(repo) {
  if (repo.full_name) return repo.full_name
  if (repo.slug) return repo.slug
  if (repo.repo) return repo.repo
  if (repo.path) {
    const parts = repo.path.split(/[\\/]/)
    return parts[parts.length - 1] || repo.path
  }
  return 'Unnamed repo'
}

const statusDotBase = {
  width: 8,
  height: 8,
  borderRadius: '50%',
  flexShrink: 0,
  marginTop: 2,
}
const statusDotRunning = { ...statusDotBase, background: theme.green }
const statusDotStopped = { ...statusDotBase, background: theme.textMuted }

export function RepoSelector({ onOpenRegister }) {
  const {
    supervisedRepos = [],
    runtimes = [],
    selectedRepoSlug,
    selectRepo,
  } = useHydraFlow()
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const handleClick = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const runtimeMap = useMemo(() => {
    return new Map(
      (runtimes || []).map(rt => [canonicalRepoSlug(rt.slug), rt]),
    )
  }, [runtimes])

  const repoOptions = useMemo(() => {
    const entries = supervisedRepos.map((repo, index) => {
      const rawSlug = repo.slug || repo.repo || repo.full_name || repo.path || `repo-${index + 1}`
      const filterSlug = canonicalRepoSlug(rawSlug)
      const runtime = runtimeMap.get(filterSlug)
      const isRunning = runtime?.running ?? repo.running ?? repo.status === 'running'
      return {
        key: `${filterSlug || rawSlug}-${index}`,
        label: buildDisplayName(repo),
        subLabel: repo.path || runtime?.repo || '',
        filterSlug,
        rawSlug,
        isRunning,
      }
    })
    entries.sort((a, b) => a.label.localeCompare(b.label))
    return entries
  }, [supervisedRepos, runtimeMap])

  const currentLabel = useMemo(() => {
    if (!selectedRepoSlug) return 'All repos'
    const match = repoOptions.find(opt => opt.filterSlug === selectedRepoSlug)
    return match?.label || 'All repos'
  }, [repoOptions, selectedRepoSlug])

  const handleSelect = (slug) => {
    selectRepo(slug)
    setOpen(false)
  }

  const showEmptyState = repoOptions.length === 0

  return (
    <div ref={containerRef} style={styles.wrapper}>
      <button
        type="button"
        style={open ? triggerOpen : styles.trigger}
        onClick={() => setOpen(prev => !prev)}
        aria-haspopup="listbox"
        aria-expanded={open}
        data-testid="repo-selector-trigger"
      >
        <span style={styles.triggerLabel}>{currentLabel}</span>
        <span style={styles.chevron}>{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div style={styles.dropdown} role="listbox" data-testid="repo-selector-dropdown">
          <button
            type="button"
            onClick={() => handleSelect(null)}
            style={selectedRepoSlug == null ? optionActiveStyle : optionStyle}
            role="option"
            aria-selected={selectedRepoSlug == null}
          >
            <span style={styles.optionLabel}>All repos</span>
            <span style={styles.optionStatus}>Aggregated</span>
          </button>
          <div style={styles.divider} />
          <div style={styles.optionList}>
            {showEmptyState ? (
              <div style={styles.empty}>No repos registered</div>
            ) : repoOptions.map(opt => (
              <button
                key={opt.key}
                type="button"
                onClick={() => handleSelect(opt.rawSlug)}
                style={opt.filterSlug === selectedRepoSlug ? optionActiveStyle : optionStyle}
                role="option"
                aria-selected={opt.filterSlug === selectedRepoSlug}
              >
                <span style={styles.optionLeft}>
                  <span style={opt.isRunning ? statusDotRunning : statusDotStopped} />
                  <span>
                    <span style={styles.optionLabel}>{opt.label}</span>
                    {opt.subLabel && <span style={styles.optionSubLabel}>{opt.subLabel}</span>}
                  </span>
                </span>
                <span style={styles.optionStatus}>{opt.isRunning ? 'Running' : 'Stopped'}</span>
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => {
              setOpen(false)
              onOpenRegister?.()
            }}
            style={styles.registerBtn}
          >
            + Register repo
          </button>
        </div>
      )}
    </div>
  )
}

const styles = {
  wrapper: {
    position: 'relative',
    minWidth: 200,
  },
  trigger: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    padding: '8px 10px',
    borderRadius: 8,
    border: `1px solid ${theme.border}`,
    background: theme.surface,
    color: theme.text,
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: 600,
    gap: 8,
  },
  triggerLabel: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    minWidth: 0,
  },
  chevron: {
    fontSize: 10,
    color: theme.textMuted,
  },
  dropdown: {
    position: 'absolute',
    top: 'calc(100% + 4px)',
    left: 0,
    right: 0,
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    boxShadow: '0 6px 18px rgba(0,0,0,0.35)',
    zIndex: 10,
    display: 'flex',
    flexDirection: 'column',
    maxHeight: 320,
  },
  optionList: {
    overflowY: 'auto',
  },
  optionBase: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    padding: '8px 10px',
    border: 'none',
    color: theme.text,
    cursor: 'pointer',
    textAlign: 'left',
    gap: 12,
  },
  optionLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  optionLabel: {
    fontSize: 12,
    fontWeight: 600,
    color: theme.text,
    display: 'block',
  },
  optionSubLabel: {
    display: 'block',
    fontSize: 10,
    color: theme.textMuted,
    fontWeight: 500,
  },
  optionStatus: {
    fontSize: 11,
    color: theme.textMuted,
    flexShrink: 0,
  },
  divider: {
    height: 1,
    background: theme.border,
    margin: '4px 0',
  },
  empty: {
    padding: '10px 12px',
    fontSize: 11,
    color: theme.textMuted,
  },
  registerBtn: {
    border: 'none',
    borderTop: `1px solid ${theme.border}`,
    background: theme.surfaceInset,
    padding: '8px 10px',
    fontSize: 12,
    fontWeight: 600,
    color: theme.accent,
    cursor: 'pointer',
  },
}

// Pre-computed trigger variant for open state
const triggerOpen = { ...styles.trigger, border: `1px solid ${theme.accent}`, background: theme.surfaceInset }

// Pre-computed option variants (active/inactive)
const optionStyle = { ...styles.optionBase, background: 'transparent' }
const optionActiveStyle = { ...styles.optionBase, background: theme.accentSubtle }
