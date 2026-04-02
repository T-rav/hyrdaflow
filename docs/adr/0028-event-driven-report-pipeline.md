# ADR-0028: Event-Driven Report Pipeline with Extractable Widget

## Status

Accepted

## Context

The bug report pipeline (`ReportIssueLoop`) silently updated `TrackedReport` status on disk but never notified the frontend. Users submitted bugs and saw "queued" indefinitely until the next 30-second HTTP poll. The `BugReportTracker` was a modal with no filtering, sorting, or inline submission — unusable for power users.

Additionally, the report UI needed to be extractable as a standalone widget for embedding in external systems (other dashboards, Slack bots, monitoring tools) without depending on the HydraFlow React context.

## Decision

### Backend: Publish `REPORT_UPDATE` events at every status transition

Added `EventType.REPORT_UPDATE` to the `EventBus`. `ReportIssueLoop._do_work()` now publishes events at 6 transition points: queued→in-progress, filed, retry, escalation, stale close, and fixed. The frontend reducer handles `report_update` WebSocket events to update `trackedReports` inline.

**Why events over direct state mutation:** The `EventBus` is the established notification mechanism. WebSocket subscribers receive events automatically. Metrics and logging can also react. This is consistent with how `WORKER_UPDATE`, `MERGE_UPDATE`, etc. already work.

### Frontend: Self-contained `useReportPoller` hook + `BugReportPanel` component

Replaced the `BugReportTracker` modal with a full-width `BugReportPanel` dashboard tab. The panel uses `useReportPoller(apiBaseUrl, reporterId, { interval })` — a hook that manages its own polling, submission, and action dispatch.

**Why HTTP polling over WebSocket-only:** The widget must work outside the HydraFlow dashboard where no WebSocket connection exists. HTTP polling at 10s intervals is portable — any system with HTTP access can embed it. The WebSocket `report_update` handler provides instant updates when available, and the poll catches up when it's not.

**Why a hook, not context:** `useReportPoller` takes `apiBaseUrl` and `reporterId` as explicit props. No `HydraFlowProvider` needed. This makes the component truly extractable:

```jsx
<BugReportPanel apiBaseUrl="https://hydra.example.com" reporterId={userId} />
```

### Server: Status filter on `GET /api/reports`

Added `?status=` query parameter to `GET /api/reports` for server-side filtering. The `useReportPoller` can request only active reports, reducing payload size for embedded widgets.

## Consequences

- Report status updates are live via WebSocket when available, polled via HTTP otherwise
- The `BugReportPanel` can be extracted to a standalone npm package with zero HydraFlow dependencies
- The old `BugReportTracker` modal and its tests were deleted
- `REPORT_UPDATE` events appear in the WebSocket stream alongside all other events — external monitoring tools can subscribe
