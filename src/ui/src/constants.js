import { theme } from './theme'

/**
 * Statuses that indicate a worker is actively processing.
 * Used across dashboard components to filter/count active workers.
 */
export const ACTIVE_STATUSES = [
  'running', 'testing', 'committing', 'reviewing', 'planning', 'quality_fix',
  'start', 'merge_main', 'merge_fix', 'ci_wait', 'ci_fix', 'merging',
  'evaluating', 'validating', 'retrying', 'fixing',
]

/** Maximum number of events retained in the frontend event buffer. */
export const MAX_EVENTS = 5000

/**
 * Canonical pipeline stage definitions.
 * All stage metadata lives here to prevent drift across components.
 * Components derive their own views (uppercase labels, filtered subsets, etc.) from this array.
 */
export const PIPELINE_STAGES = [
  { key: 'triage',    label: 'Triage',    color: theme.yellow,      subtleColor: theme.yellowSubtle,  role: 'triage',      configKey: 'max_triagers' },
  { key: 'plan',      label: 'Plan',      color: theme.purple,      subtleColor: theme.purpleSubtle, role: 'planner',     configKey: 'max_planners' },
  { key: 'implement', label: 'Implement', color: theme.accent,      subtleColor: theme.accentSubtle, role: 'implementer', configKey: 'max_workers' },
  { key: 'review',    label: 'Review',    color: theme.orange,      subtleColor: theme.orangeSubtle, role: 'reviewer',    configKey: 'max_reviewers' },
  { key: 'merged',    label: 'Merged',    color: theme.green,       subtleColor: theme.greenSubtle,  role: null,           configKey: null },
]

/**
 * Pencil cursor for the annotation canvas in the Report Issue modal.
 * SVG data URI with crosshair fallback; double quotes encoded as %22 for
 * cross-browser compatibility (Firefox rejects unencoded " in SVG data URIs).
 */
export const ANNOTATION_PENCIL_CURSOR = "url('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2224%22 height=%2224%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%23ffffff%22 stroke-width=%222%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22%3E%3Cpath d=%22M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z%22/%3E%3Cpath d=%22m15 5 4 4%22/%3E%3C/svg%3E') 2 22, crosshair"

/**
 * Annotation pen colors for the Report Issue modal.
 * Maps to pipeline stage palette so operators can color-code annotations.
 */
export const ANNOTATION_COLORS = [
  { key: 'triage',    label: 'Triage',    color: theme.yellow },
  { key: 'plan',      label: 'Plan',      color: theme.purple },
  { key: 'implement', label: 'Implement', color: theme.accent },
  { key: 'review',    label: 'Review',    color: theme.orange },
  { key: 'merged',    label: 'Merged',    color: theme.green },
  { key: 'failed',    label: 'Failed',    color: theme.red },
]

/** Shared CSS animation value for the stream-pulse keyframe. */
export const PULSE_ANIMATION = 'stream-pulse 1.5s ease-in-out infinite'

/** Valid overall statuses for stream cards. */
export const STREAM_CARD_STATUSES = ['active', 'queued', 'done', 'failed', 'hitl']

/**
 * Pipeline loop definitions — core processing loops that can be toggled on/off.
 */
export const PIPELINE_LOOPS = [
  { key: 'triage',    label: 'Triage',    color: theme.yellow,      dimColor: theme.yellowSubtle  },
  { key: 'plan',      label: 'Plan',      color: theme.purple,      dimColor: theme.purpleSubtle },
  { key: 'implement', label: 'Implement', color: theme.accent,      dimColor: theme.accentSubtle },
  { key: 'review',    label: 'Review',    color: theme.orange,      dimColor: theme.orangeSubtle },
]

/**
 * Preset interval options for background worker schedule editor.
 */
export const INTERVAL_PRESETS = [
  { label: '30m', seconds: 1800 },
  { label: '1h', seconds: 3600 },
  { label: '2h', seconds: 7200 },
  { label: '4h', seconds: 14400 },
]

/**
 * Preset interval options for the pipeline_poller worker.
 * Short-duration only — long-duration presets (30m, 1h, 2h, 4h) are intentionally excluded.
 */
export const PIPELINE_POLLER_PRESETS = [
  { label: '5s', seconds: 5 },
  { label: '10s', seconds: 10 },
  { label: '15s', seconds: 15 },
]

/**
 * Workers whose interval can be edited from the UI.
 */
export const EDITABLE_INTERVAL_WORKERS = new Set(['memory_sync', 'metrics', 'pr_unsticker', 'pipeline_poller', 'report_issue'])

/**
 * Default intervals (in seconds) for system workers.
 * Used as fallback when state?.interval_seconds is not yet available
 * (e.g., before the worker's first run report from the backend).
 */
export const SYSTEM_WORKER_INTERVALS = {
  pipeline_poller: 5,
  pr_unsticker: 3600,
  memory_sync: 3600,
  metrics: 7200,
  report_issue: 30,
}

/**
 * Options for the PR Unsticker batch size dropdown.
 */
export const UNSTICK_BATCH_OPTIONS = [1, 2, 3, 5, 10, 15, 20, 30, 50]

/**
 * Valid session statuses for the session sidebar.
 */
export const SESSION_STATUSES = ['active', 'completed']

/**
 * Background worker definitions — maintenance and system loops that can be toggled on/off.
 * Workers with `system: true` are internal services shown with a "system" badge.
 */
export const BACKGROUND_WORKERS = [
  { key: 'retrospective',   label: 'Retrospective',  description: 'Captures post-merge outcomes and recurring delivery patterns.', color: theme.purple },
  { key: 'review_insights', label: 'Review Insights', description: 'Aggregates recurring review feedback into improvement opportunities.', color: theme.orange },
  { key: 'pipeline_poller', label: 'Pipeline Poller', description: 'Refreshes live pipeline snapshots for queue and status visibility.', color: theme.textMuted, system: true },
  { key: 'memory_sync',     label: 'Memory Manager', description: 'Ingests memory and transcript issues into durable learnings.', color: theme.accent, system: true },
  { key: 'metrics',         label: 'Metrics Munger', description: 'Updates operational and GitHub metrics used by the dashboard.', color: theme.yellow, system: true },
  { key: 'pr_unsticker',    label: 'PR Unsticker',   description: 'Requeues stalled HITL PRs once requirements are actionable.', color: theme.orange, system: true },
  { key: 'report_issue',   label: 'Report Issue',   description: 'Processes queued bug reports into GitHub issues.', color: theme.red },
]
