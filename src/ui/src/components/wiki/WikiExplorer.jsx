import React, { useCallback, useEffect, useState } from 'react'
import { theme } from '../../theme'
import { WikiTopBar } from './WikiTopBar'
import { WikiEntryList } from './WikiEntryList'
import { WikiEntryDetail } from './WikiEntryDetail'
import { WikiMaintenancePanel } from './WikiMaintenancePanel'

export function WikiExplorer() {
  const [repos, setRepos] = useState([])
  const [selectedRepo, setSelectedRepo] = useState(null)
  const [filters, setFilters] = useState({ topic: '', status: '', q: '' })
  const [entries, setEntries] = useState([])
  const [selectedEntry, setSelectedEntry] = useState(null)
  const [entryDetail, setEntryDetail] = useState(null)

  useEffect(() => {
    fetch('/api/wiki/repos')
      .then((r) => {
        if (!r.ok) {
          console.warn('wiki/repos fetch non-ok:', r.status)
          return []
        }
        return r.json()
      })
      .then((data) => {
        const list = Array.isArray(data) ? data : []
        setRepos(list)
        if (list.length > 0 && selectedRepo === null) {
          setSelectedRepo(list[0])
        }
      })
      .catch((err) => {
        console.warn('wiki/repos fetch failed:', err)
        setRepos([])
      })
    // We want this to fire exactly once on mount; selectedRepo is intentionally
    // outside the dep array so we don't overwrite a user-chosen repo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!selectedRepo) {
      setEntries([])
      return
    }
    const qs = new URLSearchParams()
    if (filters.topic) qs.set('topic', filters.topic)
    if (filters.status) qs.set('status', filters.status)
    if (filters.q) qs.set('q', filters.q)
    qs.set('limit', '200')
    fetch(
      `/api/wiki/repos/${selectedRepo.owner}/${selectedRepo.repo}/entries?${qs}`,
    )
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setEntries(Array.isArray(data) ? data : []))
      .catch(() => setEntries([]))
  }, [selectedRepo, filters.topic, filters.status, filters.q])

  useEffect(() => {
    if (!selectedEntry || !selectedRepo) {
      setEntryDetail(null)
      return
    }
    fetch(
      `/api/wiki/repos/${selectedRepo.owner}/${selectedRepo.repo}/entries/${selectedEntry.id}`,
    )
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setEntryDetail(data))
      .catch(() => setEntryDetail(null))
  }, [selectedEntry, selectedRepo])

  const handleAdminAction = useCallback(
    async (path, payload) => {
      try {
        const response = await fetch(`/api/wiki/admin/${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        if (!response.ok) {
          console.warn(`wiki/admin/${path} returned ${response.status}`)
        }
      } catch (err) {
        console.warn(`wiki/admin/${path} failed:`, err)
      }
    },
    [],
  )

  const styles = {
    root: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      background: theme.bg,
      color: theme.text,
      minHeight: 0,
    },
    panes: {
      flex: 1,
      display: 'flex',
      flexDirection: 'row',
      minHeight: 0,
      borderTop: `1px solid ${theme.border}`,
    },
    leftPane: {
      width: '40%',
      minWidth: 280,
      borderRight: `1px solid ${theme.border}`,
      overflowY: 'auto',
    },
    rightPane: {
      flex: 1,
      overflowY: 'auto',
      padding: '12px 16px',
    },
  }

  return (
    <div style={styles.root}>
      <WikiTopBar
        repos={repos}
        selectedRepo={selectedRepo}
        onRepoChange={setSelectedRepo}
        filters={filters}
        onFiltersChange={setFilters}
      />
      <div style={styles.panes}>
        <div style={styles.leftPane}>
          <WikiEntryList
            entries={entries}
            selectedId={selectedEntry?.id ?? null}
            onSelect={setSelectedEntry}
          />
        </div>
        <div style={styles.rightPane}>
          <WikiEntryDetail
            entry={entryDetail}
            selectedRepo={selectedRepo}
            onAdminAction={handleAdminAction}
          />
        </div>
      </div>
      <WikiMaintenancePanel onAdminAction={handleAdminAction} />
    </div>
  )
}

export default WikiExplorer
