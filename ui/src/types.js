/**
 * @typedef {'batch_start'|'phase_change'|'worker_update'|'transcript_line'|'pr_created'|'review_update'|'triage_update'|'planner_update'|'merge_update'|'ci_check'|'hitl_escalation'|'issue_created'|'batch_complete'|'hitl_update'|'orchestrator_status'|'error'|'memory_sync'|'retrospective'|'metrics_update'|'review_insight'|'background_worker_status'|'session_start'|'session_end'} EventType
 *
 * @typedef {{ type: EventType, timestamp: string, data: Record<string, any> }} HydraFlowEvent
 *
 * @typedef {'queued'|'running'|'planning'|'validating'|'retrying'|'evaluating'|'testing'|'committing'|'quality_fix'|'merge_fix'|'reviewing'|'fixing'|'fix_done'|'start'|'merge_main'|'ci_wait'|'ci_fix'|'merging'|'escalating'|'escalated'|'done'|'failed'} WorkerStatus
 *
 * @typedef {{ status: WorkerStatus, worker: number, role: string, title: string, branch: string, transcript: string[], pr: object|null }} WorkerState
 *
 * @typedef {{ pr: number, issue: number, branch: string, draft: boolean, url: string }} PRData
 *
 * @typedef {{ pr: number, verdict: string, summary: string, duration?: number }} ReviewData
 *
 * @typedef {{ issue: number, title: string, issueUrl: string, pr: number, prUrl: string, branch: string, cause: string, status: 'pending'|'processing'|'resolved'|'approval'|string, isMemorySuggestion: boolean }} HITLItem
 *
 * @typedef {Record<string, string>} HumanInputRequests
 *
 * @typedef {{ name: string, status: string, last_run: string|null, interval_seconds: number|null, next_run: string|null, details: Record<string, any> }} BackgroundWorkerState
 *
 * @typedef {{ lifetime: { issues_completed: number, prs_merged: number, issues_created: number }, rates: Record<string, number> }} MetricsData
 *
 * @typedef {{ text: string, issueNumber: number|null, timestamp: string, status: 'pending'|'created'|'failed' }} IntentData
 *
 * @typedef {{ issueNumber: number, title: string, issueUrl: string|null, currentStage: string, overallStatus: string, stages: Object, pr: Object|null, branch: string, startTime: string|null, endTime: string|null }} StreamCardData
 *
 * @typedef {Object} SessionData
 * @property {string} id
 * @property {string} repo
 * @property {string} started_at
 * @property {string|null} ended_at
 * @property {number[]} issues_processed
 * @property {number} issues_succeeded
 * @property {number} issues_failed
 * @property {string} status - 'active' | 'completed'
 */

export {}
