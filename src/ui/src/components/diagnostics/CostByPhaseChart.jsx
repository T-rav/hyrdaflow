import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import { theme } from '../../theme'
import { buildEChartsTheme } from '../../charts/echartsTheme'

const PHASE_COLORS = {
  triage: theme.yellow,
  plan: theme.purple,
  implement: theme.accent,
  review: theme.orange,
  hitl: theme.red,
}

export function CostByPhaseChart({ data }) {
  const option = useMemo(() => buildOption(data), [data])
  const phases = Object.keys(data || {})

  if (phases.length === 0) {
    return (
      <div style={styles.container}>
        <div style={styles.title}>Cost by Phase</div>
        <div style={styles.empty}>No data</div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.title}>Cost by Phase</div>
      <ReactECharts
        option={option}
        theme={buildEChartsTheme()}
        style={{ height: 240 }}
        opts={{ renderer: 'svg' }}
      />
    </div>
  )
}

function buildOption(data) {
  const phases = Object.entries(data || {}).sort((a, b) => b[1] - a[1])
  return {
    grid: { left: 80, right: 30, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: phases.map(([phase]) => phase),
    },
    yAxis: { type: 'value', name: 'Tokens' },
    series: [
      {
        type: 'bar',
        data: phases.map(([phase, value]) => ({
          value,
          itemStyle: { color: PHASE_COLORS[phase] || theme.accent },
        })),
        barWidth: '50%',
      },
    ],
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  }
}

const styles = {
  container: {
    background: theme.surfaceInset,
    borderRadius: 8,
    padding: 16,
  },
  title: {
    fontSize: 13,
    fontWeight: 600,
    color: theme.textBright,
    marginBottom: 8,
  },
  empty: {
    padding: 30,
    textAlign: 'center',
    color: theme.textMuted,
    fontSize: 11,
  },
}
