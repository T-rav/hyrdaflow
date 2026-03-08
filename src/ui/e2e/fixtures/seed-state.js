/**
 * Deterministic seed state for screenshot capture.
 *
 * All timestamps are fixed ISO-8601 strings so renders are identical
 * across runs.  The shape matches `initialState` in HydraFlowContext.jsx.
 */

const FIXED_TS = '2025-06-15T12:00:00.000Z'
const FIXED_TS_2 = '2025-06-15T12:05:00.000Z'
const FIXED_TS_3 = '2025-06-15T12:10:00.000Z'
const FIXED_TS_4 = '2025-06-15T12:15:00.000Z'
const FIXED_TS_5 = '2025-06-15T12:20:00.000Z'

export const seedPipelineIssues = {
  triage: [
    { issue_number: 201, title: 'Add rate limiting to API', url: 'https://github.com/acme/app/issues/201', status: 'active' },
    { issue_number: 202, title: 'Refactor auth middleware', url: 'https://github.com/acme/app/issues/202', status: 'queued' },
  ],
  plan: [
    { issue_number: 203, title: 'Implement search indexing', url: 'https://github.com/acme/app/issues/203', status: 'active' },
  ],
  implement: [
    { issue_number: 204, title: 'Add CSV export to reports', url: 'https://github.com/acme/app/issues/204', status: 'active' },
    { issue_number: 205, title: 'Dark mode toggle', url: 'https://github.com/acme/app/issues/205', status: 'active' },
    { issue_number: 206, title: 'Fix pagination offset bug', url: 'https://github.com/acme/app/issues/206', status: 'queued' },
  ],
  review: [
    { issue_number: 207, title: 'Upgrade Node runtime to v22', url: 'https://github.com/acme/app/issues/207', status: 'active' },
  ],
  hitl: [
    { issue_number: 208, title: 'Migrate legacy DB schema', url: 'https://github.com/acme/app/issues/208', status: 'hitl' },
  ],
  merged: [
    { issue_number: 190, title: 'Add health-check endpoint', url: 'https://github.com/acme/app/issues/190', status: 'done' },
    { issue_number: 191, title: 'Update CI badge in README', url: 'https://github.com/acme/app/issues/191', status: 'done' },
    { issue_number: 192, title: 'Fix CORS headers', url: 'https://github.com/acme/app/issues/192', status: 'done' },
  ],
}

export const seedWorkers = {
  'triage-201': {
    status: 'active',
    worker: 'triage-0',
    role: 'triage',
    title: 'Triage Issue #201',
    branch: '',
    transcript: ['Analysing issue complexity...', 'Scoring: medium'],
    pr: null,
  },
  'plan-203': {
    status: 'active',
    worker: 'planner-0',
    role: 'planner',
    title: 'Plan Issue #203',
    branch: '',
    transcript: ['Scanning codebase...', 'Generating implementation plan...'],
    pr: null,
  },
  204: {
    status: 'active',
    worker: 'impl-0',
    role: 'implementer',
    title: 'Issue #204',
    branch: 'agent/issue-204',
    transcript: ['Cloning worktree...', 'Running tests...', 'Writing CSV helper...'],
    pr: null,
  },
  205: {
    status: 'active',
    worker: 'impl-1',
    role: 'implementer',
    title: 'Issue #205',
    branch: 'agent/issue-205',
    transcript: ['Reading theme config...'],
    pr: null,
  },
  'review-301': {
    status: 'active',
    worker: 'reviewer-0',
    role: 'reviewer',
    title: 'PR #301 (Issue #207)',
    branch: '',
    transcript: ['Checking diff quality...'],
    pr: 301,
  },
}

export const seedHitlItems = [
  {
    issue: 208,
    title: 'Migrate legacy DB schema',
    cause: 'CI failure: migration test timed out',
    pr: 310,
    branch: 'agent/issue-208',
    status: 'pending',
    context_summary: 'The migration script exceeded the 60 s CI timeout. Underlying cause appears to be a missing index on users.email, causing a full table scan during the data-copy step.',
    created_at: FIXED_TS_3,
  },
  {
    issue: 209,
    title: 'Add GraphQL subscriptions',
    cause: 'Type error in resolver',
    pr: 311,
    branch: 'agent/issue-209',
    status: 'pending',
    context_summary: 'The subscription resolver returns a string but the schema expects an object type. Needs schema alignment.',
    created_at: FIXED_TS_4,
  },
]

export const seedEvents = [
  { type: 'orchestrator_status', timestamp: FIXED_TS, data: { status: 'running' } },
  { type: 'triage_update', timestamp: FIXED_TS_2, data: { issue: 201, status: 'active', worker: 'triage-0' } },
  { type: 'planner_update', timestamp: FIXED_TS_3, data: { issue: 203, status: 'active', worker: 'planner-0' } },
  { type: 'worker_update', timestamp: FIXED_TS_4, data: { issue: 204, status: 'active', worker: 'impl-0' } },
  { type: 'review_update', timestamp: FIXED_TS_5, data: { pr: 301, issue: 207, status: 'active', worker: 'reviewer-0' } },
]

export const seedBackgroundWorkers = [
  { name: 'manifest_refresh', status: 'ok', enabled: true, last_run: FIXED_TS, details: {}, interval_seconds: 3600 },
  { name: 'memory_sync', status: 'ok', enabled: true, last_run: FIXED_TS, details: {}, interval_seconds: 1800 },
  { name: 'metrics_sync', status: 'ok', enabled: true, last_run: FIXED_TS_2, details: {}, interval_seconds: 900 },
  { name: 'pr_unsticker', status: 'ok', enabled: true, last_run: FIXED_TS, details: {}, interval_seconds: 600 },
  { name: 'pipeline_poller', status: 'ok', enabled: true, last_run: FIXED_TS_2, details: {}, interval_seconds: 5 },
  { name: 'repo_scanner', status: 'ok', enabled: false, last_run: null, details: {}, interval_seconds: 7200 },
  { name: 'stale_session_cleanup', status: 'ok', enabled: true, last_run: FIXED_TS, details: {}, interval_seconds: 3600 },
  { name: 'credit_monitor', status: 'ok', enabled: true, last_run: FIXED_TS_2, details: {}, interval_seconds: 300 },
]

export const seedSessions = [
  {
    id: 'session-001',
    repo: 'acme/app',
    started_at: FIXED_TS,
    ended_at: null,
    issues_processed: [190, 191, 192, 201, 203, 204, 205, 207, 208],
    issues_succeeded: 3,
    issues_failed: 0,
    status: 'active',
  },
  {
    id: 'session-000',
    repo: 'acme/app',
    started_at: '2025-06-14T08:00:00.000Z',
    ended_at: '2025-06-14T18:30:00.000Z',
    issues_processed: [180, 181, 182, 183],
    issues_succeeded: 4,
    issues_failed: 0,
    status: 'completed',
  },
]

export const seedMetrics = {
  lifetime: {
    issues_triaged: 42,
    issues_planned: 38,
    issues_implemented: 35,
    issues_reviewed: 33,
    issues_merged: 30,
    total_tokens: 1250000,
    total_cost_usd: 87.5,
  },
}

export const seedPipelineStats = {
  triage: { total: 2, active: 1, queued: 1 },
  plan: { total: 1, active: 1, queued: 0 },
  implement: { total: 3, active: 2, queued: 1 },
  review: { total: 1, active: 1, queued: 0 },
  hitl: { total: 1, active: 0, queued: 0 },
  merged: { total: 3 },
}

export const seedEpics = [
  {
    epic_number: 100,
    title: 'API v2 Migration',
    status: 'active',
    total_issues: 8,
    completed_issues: 3,
    child_issues: [190, 191, 192, 204, 205, 206, 207, 208],
  },
  {
    epic_number: 101,
    title: 'Performance Optimisation',
    status: 'active',
    total_issues: 4,
    completed_issues: 1,
    child_issues: [201, 202, 203, 209],
  },
]

export const seedConfig = {
  repo: 'acme/app',
  max_workers: 3,
  max_reviewers: 2,
  max_planners: 1,
  max_hitl_workers: 1,
  model: 'opus',
  review_model: 'sonnet',
  planner_model: 'opus',
  batch_size: 15,
  ready_label: 'hydraflow-ready',
  planner_label: 'hydraflow-plan',
  app_version: '0.9.0',
}

export const seedSupervisedRepos = [
  { slug: 'acme-app', full_name: 'acme/app', status: 'running' },
]

/**
 * Complete seed state matching `initialState` in HydraFlowContext.jsx.
 * Injected via `window.__HYDRAFLOW_SEED_STATE__` before React mounts.
 */
export const seedState = {
  connected: true,
  lastSeenId: 100,
  phase: 'implement',
  orchestratorStatus: 'running',
  creditsPausedUntil: null,
  workers: seedWorkers,
  prs: [
    { pr: 301, issue: 207, merged: false },
    { pr: 290, issue: 190, merged: true },
    { pr: 291, issue: 191, merged: true },
  ],
  reviews: [],
  sessionPrsCount: 3,
  lifetimeStats: seedMetrics.lifetime,
  queueStats: { triage: 2, plan: 1, implement: 1, review: 0 },
  config: seedConfig,
  events: seedEvents,
  hitlItems: seedHitlItems,
  hitlEscalation: null,
  humanInputRequests: {},
  backgroundWorkers: seedBackgroundWorkers,
  metrics: seedMetrics,
  systemAlert: null,
  intents: [],
  epics: seedEpics,
  epicReleasing: null,
  githubMetrics: null,
  metricsHistory: null,
  pipelineIssues: seedPipelineIssues,
  pipelineStats: seedPipelineStats,
  pipelinePollerLastRun: FIXED_TS_2,
  sessions: seedSessions,
  currentSessionId: 'session-001',
  selectedSessionId: null,
  selectedRepoSlug: null,
  supervisedRepos: seedSupervisedRepos,
  runtimes: [],
  issueHistory: null,
  harnessInsights: null,
  reviewInsights: null,
  retrospectives: null,
  troubleshooting: null,
  memories: null,
}

/**
 * Variant with empty pipeline for testing the "idle" state.
 */
export const seedStateEmpty = {
  ...seedState,
  connected: true,
  phase: 'idle',
  orchestratorStatus: 'idle',
  workers: {},
  prs: [],
  reviews: [],
  sessionPrsCount: 0,
  events: [],
  hitlItems: [],
  hitlEscalation: null,
  intents: [],
  pipelineIssues: { triage: [], plan: [], implement: [], review: [], hitl: [], merged: [] },
  pipelineStats: null,
  sessions: [],
  currentSessionId: null,
  epics: [],
}
