// Maps HydraFlow theme tokens to an Apache ECharts theme JSON.
// All charts in the diagnostics tab use this single theme so they
// match the dashboard's look without raw hex values in chart code.

import { theme } from '../theme'

export function buildEChartsTheme() {
  return {
    color: [
      theme.accent,
      theme.green,
      theme.orange,
      theme.purple,
      theme.cyan,
      theme.pink,
      theme.yellow,
      theme.red,
    ],
    backgroundColor: 'transparent',
    textStyle: {
      color: theme.text,
      fontFamily: 'inherit',
    },
    title: {
      textStyle: { color: theme.textBright, fontSize: 14 },
      subtextStyle: { color: theme.textMuted, fontSize: 11 },
    },
    grid: {
      borderColor: theme.border,
      backgroundColor: 'transparent',
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: theme.border } },
      axisTick: { lineStyle: { color: theme.border } },
      axisLabel: { color: theme.textMuted, fontSize: 11 },
      splitLine: { lineStyle: { color: theme.border, opacity: 0.3 } },
    },
    valueAxis: {
      axisLine: { lineStyle: { color: theme.border } },
      axisTick: { lineStyle: { color: theme.border } },
      axisLabel: { color: theme.textMuted, fontSize: 11 },
      splitLine: { lineStyle: { color: theme.border, opacity: 0.3 } },
    },
    legend: {
      textStyle: { color: theme.textMuted, fontSize: 11 },
    },
    tooltip: {
      backgroundColor: theme.bg,
      borderColor: theme.border,
      borderWidth: 1,
      textStyle: { color: theme.text },
      extraCssText: 'box-shadow: 0 2px 8px rgba(0,0,0,0.4);',
    },
  }
}
