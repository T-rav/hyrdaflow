import React, { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import { theme } from '../../theme'
import { buildEChartsTheme } from '../../charts/echartsTheme'

export function CacheHitChart({ data }) {
  const option = useMemo(() => buildOption(data), [data])

  if (!data || data.length === 0) {
    return (
      <div style={styles.container}>
        <div style={styles.title}>Cache Hit Rate</div>
        <div style={styles.empty}>No data</div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.title}>Cache Hit Rate</div>
      <ReactECharts
        option={option}
        theme={buildEChartsTheme()}
        style={{ height: 220 }}
        opts={{ renderer: 'svg' }}
      />
    </div>
  )
}

function buildOption(data) {
  return {
    grid: { left: 60, right: 30, top: 20, bottom: 40 },
    xAxis: {
      type: 'time',
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 1,
      axisLabel: {
        formatter: (v) => `${Math.round(v * 100)}%`,
      },
    },
    series: [
      {
        type: 'line',
        data: data.map((d) => [d.timestamp, d.cache_hit_rate]),
        smooth: true,
        symbol: 'circle',
        symbolSize: 4,
        lineStyle: { color: theme.cyan, width: 2 },
        itemStyle: { color: theme.cyan },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: theme.cyan + '40' },
              { offset: 1, color: theme.cyan + '00' },
            ],
          },
        },
      },
    ],
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const value = params[0].value[1]
        return `${params[0].axisValueLabel}: ${Math.round(value * 100)}%`
      },
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
