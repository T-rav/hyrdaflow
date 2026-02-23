PLAN_START

## Issue Summary

Fix duplicate transcript entries in the dashboard log display. When the WebSocket reconnects (network glitch, tab sleep/wake), the full event history is replayed and the client-side reducer blindly appends all `transcript_line` events to worker transcript arrays, causing duplicated lines in the UI. The fix adds unique event IDs to `HydraFlowEvent` for deduplication and applies defense-in-depth at the WebSocket handler and reducer levels.

## Files to Modify

### 1. `events.py` — Add unique `id` field to `HydraFlowEvent`
- Add `import uuid` at the top
- Add `id: str = Field(default_factory=lambda: uuid.uuid4().hex)` to `HydraFlowEvent` (before `type`)
- UUID hex is 32 characters, globally unique, no counter-restart issues across server restarts
- Backward-compatible: events loaded from disk without `id` get a new UUID assigned by Pydantic's `default_factory`
- The `id` is automatically included in `model_dump_json()` output, so WebSocket messages carry it

### 2. `ui/src/context/HydraFlowContext.jsx` — Client-side deduplication
- **Add `seenTranscriptIdsRef`** in `HydraFlowProvider`: `const seenTranscriptIdsRef = useRef(new Set())` — persists across reconnects within the same page session
- **Pass event `id` through dispatch**: In `ws.onmessage`, include `event.id` in the dispatched action: `dispatch({ type: event.type, data: event.data, timestamp: event.timestamp, id: event.id })`
- **Dedup in `ws.onmessage`**: Before dispatching `transcript_line` events, check if `event.id` is in `seenTranscriptIdsRef.current`. If yes, skip entirely. If no, add to set and dispatch.
- **Update `transcript_line` reducer**: Store transcript entries as `{ id, line }` objects instead of plain strings, enabling stable React keys downstream. Change `[...w.transcript, action.data.line]` to `[...w.transcript, { id: action.id, line: action.data.line }]`
- **Update worker init templates**: In `triage_update`, `planner_update`, `review_update`, and `worker_update` handlers, the default `transcript: []` remains unchanged (still an array, now of objects)

### 3. `ui/src/components/TranscriptView.jsx` — Stable React keys and updated rendering
- **Single worker view** (line 31-35): Change `w.transcript.map((line, i) =>` to `w.transcript.map((entry) =>` with `key={entry.id || entry}` and render `entry.line || entry` for the markdown content (graceful fallback for plain strings during transition)
- **Combined view** (line 45-47): Change `allLines.push({ key, role: w.role, line })` to extract `entry.line` and `entry.id`
- **Combined view rendering** (line 64-68): Use `key={item.id || i}` instead of `key={i}`
- **Line count** (line 26): Unchanged — `w.transcript.length` still works since it's an array

## New Files

None — all changes are within existing files and test files.

## Implementation Steps

### Step 1: Add `id` field to `HydraFlowEvent` (`events.py`)

Add `import uuid` and the new field:

```python
import uuid

class HydraFlowEvent(BaseModel):
    """A single event published on the bus."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: EventType
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    data: dict[str, Any] = Field(default_factory=dict)
```

Key points:
- `uuid.uuid4().hex` produces a 32-character hex string (no hyphens), compact for JSON
- Using `str` rather than `int` avoids counter-restart issues across server restarts
- Pydantic's `default_factory` means old events from disk get a fresh UUID on load — this is correct behavior since the IDs just need to be unique within a WebSocket session

### Step 2: Add dedup tracking in `HydraFlowProvider` (`HydraFlowContext.jsx`)

Add a ref to track seen transcript event IDs:

```javascript
const seenTranscriptIdsRef = useRef(new Set())
```

Place after the existing `bgWorkersRef` declaration (~line 468).

### Step 3: Add dedup filtering in `ws.onmessage` (`HydraFlowContext.jsx`)

In the `ws.onmessage` handler, before dispatching, add dedup logic for `transcript_line` events:

```javascript
ws.onmessage = (e) => {
  try {
    const event = JSON.parse(e.data)
    
    // Dedup transcript lines by event ID (prevents replay on reconnect)
    if (event.type === 'transcript_line' && event.id) {
      if (seenTranscriptIdsRef.current.has(event.id)) return
      seenTranscriptIdsRef.current.add(event.id)
    }
    
    dispatch({ type: event.type, data: event.data, timestamp: event.timestamp, id: event.id })
    // ... rest of existing handler unchanged
  }
}
```

This is the primary dedup mechanism — O(1) Set lookup prevents duplicate events from ever reaching the reducer.

### Step 4: Update reducer `transcript_line` handler (`HydraFlowContext.jsx`)

Change transcript storage from plain strings to objects with IDs:

```javascript
case 'transcript_line': {
  let key = action.data.issue || action.data.pr
  if (action.data.source === 'triage') {
    key = `triage-${action.data.issue}`
  } else if (action.data.source === 'planner') {
    key = `plan-${action.data.issue}`
  } else if (action.data.source === 'reviewer') {
    key = `review-${action.data.pr}`
  }
  if (!key || !state.workers[key]) return addEvent(state, action)
  const w = state.workers[key]
  return {
    ...addEvent(state, action),
    workers: {
      ...state.workers,
      [key]: { ...w, transcript: [...w.transcript, { id: action.id, line: action.data.line }] },
    },
  }
}
```

### Step 5: Update `TranscriptView.jsx` rendering

**Single worker view:**
```jsx
w.transcript.map((entry) => (
  <div key={entry.id || `line-${w.transcript.indexOf(entry)}`} style={styles.line}>
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
      {typeof entry === 'string' ? entry : entry.line}
    </ReactMarkdown>
  </div>
))
```

**Combined view building:**
```javascript
for (const entry of w.transcript) {
  const line = typeof entry === 'string' ? entry : entry.line
  const entryId = typeof entry === 'string' ? null : entry.id
  allLines.push({ key, role: w.role, line, id: entryId })
}
```

**Combined view rendering:**
```jsx
{allLines.map((item, i) => (
  <div key={item.id || `combined-${i}`} style={styles.line}>
    <span style={styles.linePrefix}>[{item.role} #{item.key}]</span>
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{item.line}</ReactMarkdown>
  </div>
))}
```

The `typeof entry === 'string'` checks provide graceful backward compatibility during any transition period.

### Step 6: Update backend tests (`tests/test_events.py`)

Add tests for the new `id` field on `HydraFlowEvent`:
- `test_hydra_event_has_id_field` — Verify instances have a non-empty `id` string
- `test_hydra_event_ids_are_unique` — Create multiple events, verify all IDs are distinct
- `test_hydra_event_id_in_serialization` — Verify `model_dump_json()` includes `id`
- `test_hydra_event_without_id_in_json_gets_default` — Verify `model_validate_json` with missing `id` assigns a default

### Step 7: Update frontend tests

**`ui/src/hooks/__tests__/useHydraSocket.test.js`:**
- Add test: `transcript_line` with `id` stores `{id, line}` object in transcript
- Add test: `transcript_line` without `id` stores `{id: undefined, line}` object

**`ui/src/components/__tests__/TranscriptView.test.jsx`:**
- Update all test fixtures from `transcript: ['line one', 'line two']` to `transcript: [{ id: 'a', line: 'line one' }, { id: 'b', line: 'line two' }]`
- Verify rendering still works with `screen.getByText('line one')`

## Testing Strategy

### Backend Tests (`tests/test_events.py`)
- **`test_hydra_event_has_id_field`** — Verify `HydraFlowEvent` instances have a non-empty `id` string
- **`test_hydra_event_ids_are_unique`** — Create 100 events, verify all IDs are distinct
- **`test_hydra_event_id_in_serialization`** — Verify `model_dump_json()` includes the `id` field
- **`test_hydra_event_without_id_in_json_gets_default`** — `model_validate_json('{"type": "error"}')` assigns a default ID (backward compat with disk events)

### Frontend Tests (`ui/src/hooks/__tests__/useHydraSocket.test.js`)
- **`test transcript_line stores id and line as object`** — Dispatch `transcript_line` with `id: 'abc123'`, verify `workers[key].transcript[0]` is `{ id: 'abc123', line: '...' }`
- **`test transcript_line without id still appends`** — Dispatch without `id`, verify entry has `{ id: undefined, line: '...' }`

### Frontend Tests (`ui/src/components/__tests__/TranscriptView.test.jsx`)
- Update existing test data from `transcript: ['line one']` to `transcript: [{ id: 'a', line: 'line one' }]`
- Verify rendering still works correctly
- Add test with mixed old (string) and new (object) entries if backward compat matters

## Acceptance Criteria

- [ ] Each transcript line appears exactly once in the UI, even after WebSocket reconnection
- [ ] `HydraFlowEvent` has a unique `id` field for deduplication
- [ ] Client-side `ws.onmessage` handler skips duplicate `transcript_line` events based on event ID
- [ ] WebSocket reconnect does not replay already-displayed transcript events
- [ ] React keys are stable (event IDs, not array indices)
- [ ] Combined transcript view (all workers) has no duplicates
- [ ] Unit tests verify event ID generation and transcript dedup logic
- [ ] No performance regression from dedup checks (O(1) lookup via Set)

## Key Considerations

### Edge Cases
- **Events without `id` field**: Old events loaded from disk or events from other sources may lack `id`. The reducer and TranscriptView handle this gracefully with fallbacks (`typeof entry === 'string'` checks, `entry.id || fallback` keys).
- **Server restart**: On server restart, events loaded from disk get new UUIDs. However, the `orchestrator_status` handler already clears workers (including transcripts) when status is `idle`/`done`/`stopping`, so stale transcripts from a previous server session are cleaned up.
- **Memory growth of `seenTranscriptIdsRef`**: The Set grows with each unique transcript event. With a typical session producing hundreds to low thousands of transcript events, this is well within memory limits. Could be pruned on page visibility change for very long sessions, but not needed initially.

### Backward Compatibility
- `HydraFlowEvent.id` uses `default_factory`, so existing code creating events without explicit `id` continues to work
- `EventLog` loads old events from disk without `id`; Pydantic assigns a default UUID
- TranscriptView renders both old `string` format and new `{id, line}` format entries
- All existing tests continue to pass (event ID is auto-generated, doesn't affect existing assertions beyond needing updates to exact-match assertions)

### Concurrent Plan Conflicts
- **Issue #118** also modifies `events.py` — the `id` field addition is isolated to `HydraFlowEvent` and should merge cleanly
- **Issue #268** also modifies `events.py` — same consideration; field addition is non-conflicting
- **Issue #147** also modifies `useHydraSocket.js` — this file is now just a re-export wrapper; real logic is in `HydraFlowContext.jsx`, so there's no actual conflict

### Pre-Mortem: Top 3 Failure Risks

1. **Breaking existing tests that assert on `HydraFlowEvent` fields**: Adding `id` changes `model_dump()` output. Tests that do exact dict comparisons (e.g., `assert event.model_dump() == {...}`) will fail because they don't expect `id`. Mitigation: audit all test assertions on `HydraFlowEvent` in `test_events.py`, `test_event_persistence.py`, `test_dashboard.py`, and `test_dashboard_routes.py` — update those that do exact matching.

2. **TranscriptView rendering breaks with new transcript format**: Changing from `string[]` to `{id, line}[]` affects any component that reads `w.transcript` and expects strings. Mitigation: add `typeof` guards for graceful fallback in TranscriptView, and update all transcript data in test fixtures across `useHydraSocket.test.js`, `TranscriptView.test.jsx`, and `HydraContext.test.jsx`.

3. **`seenTranscriptIdsRef` not accessible inside `ws.onmessage` closure**: The ref must be created at the HydraFlowProvider level and captured by the `connect` callback. Since `connect` is wrapped in `useCallback`, the ref access via `.current` will always get the latest value (refs don't need to be in dependency arrays). Verified this pattern is already used for `lastEventTsRef` and `bgWorkersRef` in the existing code — safe to follow.

PLAN_END

SUMMARY: Add UUID-based event IDs to HydraFlowEvent and implement client-side deduplication in ws.onmessage handler plus stable React keys in TranscriptView to prevent duplicate transcript entries on WebSocket reconnect.
