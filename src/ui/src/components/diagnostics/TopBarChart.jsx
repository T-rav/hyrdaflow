import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import { theme } from '../../theme'
import { buildEChartsTheme } from '../../charts/echartsTheme'

export function TopBarChart({ title, data, valueKey = 'count', annotation = null }) {
  const option = useMemo(() => buildOption(data, valueKey, annotation), [data, valueKey, annotation])

  if (!data || data.length === 0) {
    return (
      <div style={styles.container}>
        <div style={styles.title}>{title}</div>
        <div style={styles.empty}>No data</div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.title}>{title}</div>
      <ReactECharts
        option={option}
        theme={buildEChartsTheme()}
        style={{ height: 220 }}
        opts={{ renderer: 'svg' }}
      />
    </div>
  )
}

function buildOption(data, valueKey, annotation) {
  const sorted = [...data].sort((a, b) => (a[valueKey] || 0) - (b[valueKey] || 0))
  return {
    grid: { left: 100, right: 30, top: 10, bottom: 20 },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: sorted.map((d) => d.name),
    },
    series: [
      {
        type: 'bar',
        data: sorted.map((d) => ({
          value: d[valueKey] || 0,
          itemStyle: { color: theme.accent },
        })),
        barWidth: '60%',
        label: {
          show: true,
          position: 'right',
          color: theme.textMuted,
          fontSize: 10,
          formatter: (params) => {
            const item = sorted[params.dataIndex]
            if (annotation) {
              return `${params.value} ${annotation(item)}`
            }
            return params.value
          },
        },
      },
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
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
