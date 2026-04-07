import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import { theme } from '../../theme'
import { buildEChartsTheme } from '../../charts/echartsTheme'

export function DrillDownPane({ runData, onClose }) {
  const ganttOption = useMemo(
    () => runData ? buildGanttOption(runData.subprocesses || []) : null,
    [runData]
  )

  if (!runData) {
    return (
      <div style={styles.container}>
        <div style={styles.empty}>Select a row to view its trace</div>
      </div>
    )
  }

  if (runData.error) {
    return (
      <div style={styles.container}>
        <div style={styles.empty}>{runData.error}</div>
      </div>
    )
  }

  const summary = runData.summary || {}
  const subprocesses = runData.subprocesses || []

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={styles.title}>
          Issue #{summary.issue_number} — {summary.phase} (run {summary.run_id})
        </div>
        <button style={styles.close} onClick={onClose}>×</button>
      </div>

      <div style={styles.subprocessList}>
        {subprocesses.map((sp) => (
          <SubprocessRow key={sp.subprocess_idx} sp={sp} />
        ))}
      </div>

      {ganttOption && (
        <div style={styles.ganttSection}>
          <div style={styles.sectionTitle}>Call Trace Timeline</div>
          <ReactECharts
            option={ganttOption}
            theme={buildEChartsTheme()}
            style={{ height: 200 }}
            opts={{ renderer: 'svg' }}
          />
        </div>
      )}
    </div>
  )
}

function SubprocessRow({ sp }) {
  const tokens = sp.tokens || {}
  const totalTokens =
    (tokens.prompt_tokens || 0) +
    (tokens.completion_tokens || 0) +
    (tokens.cache_read_tokens || 0)

  return (
    <div style={styles.subprocess}>
      <div style={styles.subprocessHeader}>
        <span style={styles.subprocessName}>
          subprocess-{sp.subprocess_idx} ({sp.backend})
        </span>
        <span style={styles.subprocessStats}>
          {totalTokens.toLocaleString()} tokens · {sp.tool_calls?.length || 0} tool calls
        </span>
      </div>
      {sp.skill_results && sp.skill_results.length > 0 && (
        <div style={styles.skillsList}>
          {sp.skill_results.map((sr, i) => (
            <span
              key={i}
              style={{
                ...styles.skillBadge,
                color: sr.passed ? theme.green : theme.red,
              }}
            >
              {sr.passed ? '✓' : '✗'} {sr.skill_name}
              {sr.attempts > 1 && ` (${sr.attempts} tries)`}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function buildGanttOption(subprocesses) {
  // Each subprocess becomes a row; tool_calls are bars within the row
  const rows = []
  subprocesses.forEach((sp, idx) => {
    (sp.tool_calls || []).forEach((tc) => {
      const start = new Date(tc.started_at)
      if (isNaN(start.getTime())) return
      const startMs = start.getTime()
      const duration = Number(tc.duration_ms) || 0
      rows.push({
        name: `sub-${idx}`,
        value: [idx, startMs, startMs + duration, tc.tool_name],
        itemStyle: { color: tc.succeeded ? theme.accent : theme.red },
      })
    })
  })

  return {
    grid: { left: 80, right: 30, top: 30, bottom: 30 },
    xAxis: { type: 'time' },
    yAxis: {
      type: 'category',
      data: subprocesses.map((_, idx) => `sub-${idx}`),
    },
    series: [
      {
        type: 'custom',
        renderItem: (params, api) => {
          const categoryIdx = api.value(0)
          const start = api.coord([api.value(1), categoryIdx])
          const end = api.coord([api.value(2), categoryIdx])
          const height = api.size([0, 1])[1] * 0.6
          return {
            type: 'rect',
            shape: {
              x: start[0],
              y: start[1] - height / 2,
              width: Math.max(2, end[0] - start[0]),
              height,
            },
            style: api.style(),
          }
        },
        encode: { x: [1, 2], y: 0 },
        data: rows,
      },
    ],
    tooltip: {
      formatter: (params) => `${params.value[3]}<br/>duration: ${params.value[2] - params.value[1]}ms`,
    },
  }
}

const styles = {
  container: {
    background: theme.surfaceInset,
    borderRadius: 8,
    padding: 16,
    marginTop: 16,
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  title: {
    fontSize: 14,
    fontWeight: 600,
    color: theme.textBright,
  },
  close: {
    background: 'transparent',
    border: 'none',
    color: theme.textMuted,
    fontSize: 20,
    cursor: 'pointer',
  },
  subprocessList: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    marginBottom: 16,
  },
  subprocess: {
    background: theme.bg,
    borderRadius: 4,
    padding: '8px 12px',
  },
  subprocessHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  subprocessName: {
    fontSize: 12,
    color: theme.text,
    fontWeight: 600,
  },
  subprocessStats: {
    fontSize: 11,
    color: theme.textMuted,
  },
  skillsList: {
    marginTop: 4,
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
  },
  skillBadge: {
    fontSize: 10,
  },
  ganttSection: {
    marginTop: 16,
  },
  sectionTitle: {
    fontSize: 11,
    color: theme.textMuted,
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  empty: {
    padding: 40,
    textAlign: 'center',
    color: theme.textMuted,
    fontSize: 11,
  },
}
