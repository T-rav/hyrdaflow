import React, { useEffect, useState, useCallback } from 'react'
import { theme } from '../../theme'
import { HeadlineCards } from './HeadlineCards'
import { TopBarChart } from './TopBarChart'
import { CostByPhaseChart } from './CostByPhaseChart'
import { CacheHitChart } from './CacheHitChart'
import { IssueTable } from './IssueTable'
import { DrillDownPane } from './DrillDownPane'

export function DiagnosticsTab() {
  const [range, setRange] = useState('7d')
  const [overview, setOverview] = useState(null)
  const [tools, setTools] = useState([])
  const [skills, setSkills] = useState([])
  const [subagents, setSubagents] = useState([])
  const [costByPhase, setCostByPhase] = useState({})
  const [cache, setCache] = useState([])
  const [issues, setIssues] = useState([])
  const [loading, setLoading] = useState(false)
  const [selectedRun, setSelectedRun] = useState(null)

  useEffect(() => {
    let cancelled = false
    const params = `?range=${encodeURIComponent(range)}`
    setLoading(true)
    Promise.all([
      fetch(`/api/diagnostics/overview${params}`).then((r) => r.json()),
      fetch(`/api/diagnostics/tools${params}`).then((r) => r.json()),
      fetch(`/api/diagnostics/skills${params}`).then((r) => r.json()),
      fetch(`/api/diagnostics/subagents${params}`).then((r) => r.json()),
      fetch(`/api/diagnostics/cost-by-phase${params}`).then((r) => r.json()),
      fetch(`/api/diagnostics/cache${params}`).then((r) => r.json()),
      fetch(`/api/diagnostics/issues${params}`).then((r) => r.json()),
    ])
      .then(([ov, tl, sk, sa, cbp, ch, is]) => {
        if (cancelled) return
        setOverview(ov)
        setTools(tl)
        setSkills(sk)
        setSubagents(sa)
        setCostByPhase(cbp)
        setCache(ch)
        setIssues(is)
      })
      .catch((err) => {
        if (!cancelled) {
          console.error('diagnostics fetch failed', err)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [range])

  const handleRowClick = useCallback(async (row) => {
    const url = `/api/diagnostics/issue/${row.issue}/${row.phase}/${row.run_id}`
    try {
      const r = await fetch(url)
      if (!r.ok) {
        setSelectedRun({
          summary: null,
          subprocesses: [],
          error: `Failed to load run (${r.status})`,
        })
        return
      }
      setSelectedRun(await r.json())
    } catch (err) {
      setSelectedRun({ summary: null, subprocesses: [], error: String(err) })
    }
  }, [])

  return (
    <div style={styles.tab}>
      <div style={styles.header}>
        <h2 style={styles.title}>Factory Diagnostics</h2>
        <label style={styles.filterLabel}>
          Range:
          <select
            style={styles.select}
            value={range}
            onChange={(e) => setRange(e.target.value)}
          >
            <option value="24h">Last 24h</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="all">All time</option>
          </select>
        </label>
      </div>

      <HeadlineCards data={overview} loading={loading} />

      <div style={styles.gridTwo}>
        <TopBarChart title="Top Tools" data={tools} valueKey="count" />
        <TopBarChart
          title="Top Skills"
          data={skills}
          valueKey="count"
          annotation={(item) =>
            `(${Math.round((item.first_try_pass_rate || 0) * 100)}% 1st-try)`
          }
        />
      </div>

      <div style={styles.gridTwo}>
        <TopBarChart title="Top Subagents" data={subagents} valueKey="count" />
        <CostByPhaseChart data={costByPhase} />
      </div>

      <CacheHitChart data={cache} />

      <IssueTable rows={issues} onRowClick={handleRowClick} />

      {selectedRun && (
        <DrillDownPane
          runData={selectedRun}
          onClose={() => setSelectedRun(null)}
        />
      )}
    </div>
  )
}

const styles = {
  tab: {
    padding: 24,
    overflowY: 'auto',
    height: '100%',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 24,
  },
  title: {
    color: theme.textBright,
    fontSize: 20,
    fontWeight: 700,
    margin: 0,
  },
  filterLabel: {
    color: theme.textMuted,
    fontSize: 12,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  select: {
    background: theme.surfaceInset,
    color: theme.text,
    border: `1px solid ${theme.border}`,
    padding: '4px 8px',
    fontSize: 12,
    borderRadius: 4,
  },
  gridTwo: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: 16,
    marginBottom: 16,
  },
}
