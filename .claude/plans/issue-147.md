PLAN_START

## Issue Summary

Issue #147 requests a fundamental UX transformation: shift Hydra's dashboard from a tab-based ops monitoring tool to a **stream-first, conversational product experience**. Three key deliverables:

1. **Intent Input Bar** — users type requests directly in the dashboard, which creates GitHub issues via `POST /api/intent`
2. **Stream-First Unified View** — replace the 4-tab layout with a single scrollable activity feed organized by issue  
3. **Conversation Threading per Issue** — each issue renders as a card showing its full lifecycle (intent → triage → plan → implement → review → merge)

## Files to Modify

### Backend (Python)

1. **`dashboard_routes.py`** — Add `POST /api/intent` endpoint that creates a GitHub issue with `hydraflow-plan` label via `PRManager.create_issue()` and returns the issue number/URL. Also need to add the route path to test expectations.

2. **`models.py`** — Add `IntentRequest` and `IntentResponse` Pydantic models for the new endpoint.

### Frontend (React)

3. **`ui/src/App.jsx`** — Major restructure:
   - Replace tab-based layout with a two-mode view: Stream (default) + Detail tabs
   - Add `IntentInput` above the stream view
   - Add `StreamView` as the new default view
   - Keep existing tabs (Transcript, PRs, HITL, Livestream, System, Metrics) accessible via a secondary tab bar, but make Stream the default
   - Remove the inline `livestream` tab rendering (replaced by the Livestream component)

4. **`ui/src/hooks/useHydraSocket.js`** — Add `submitIntent` callback function that POSTs to `/api/intent` and dispatches an optimistic `INTENT_SUBMITTED` action to immediately show the intent in the stream. Add a new `intents` state field (array of `{text, issueNumber, timestamp, status}`) to the reducer.

5. **`ui/src/theme.js`** — Add new theme tokens for stream card styling: `intentBg`, `cardBorder`.

6. **`ui/index.html`** — Add CSS custom properties for the new theme tokens.

7. **`ui/src/constants.js`** — Add `STREAM_CARD_STATUSES` constant for card state management.

8. **`ui/src/types.js`** — Add JSDoc typedefs for `IntentRequest`, `StreamCardData`.

### Frontend (New Files)

9. **`ui/src/components/IntentInput.jsx`** — Chat-like input bar with:
   - Text input + submit button
   - Disabled state when disconnected or orchestrator not running
   - Submitting state with loading indicator
   - Calls `submitIntent(text)` from `useHydraSocket`

10. **`ui/src/components/StreamView.jsx`** — Unified stream/feed view:
    - Renders all issues as `StreamCard` components sorted by recency
    - Uses `useTimeline` hook (already exists) to derive per-issue lifecycle data
    - Active cards appear expanded with live progress, completed cards collapse
    - Filter bar similar to existing Timeline component

11. **`ui/src/components/StreamCard.jsx`** — Per-issue conversation card:
    - Shows lifecycle as a threaded conversation (intent → plan → implement → review → merge)
    - Each stage shows a summary line with icon and semantic status
    - Active stage shows live progress indicator (pulsing dot)
    - Collapsed/expanded toggle for completed cards
    - Quick action buttons: "View transcript" (navigates to transcript tab with worker selected), "View PR" (external link), "Request changes" (navigates to HITL)

## New Files

1. **`ui/src/components/IntentInput.jsx`** — Intent input component
2. **`ui/src/components/StreamView.jsx`** — Unified stream view
3. **`ui/src/components/StreamCard.jsx`** — Per-issue conversation card
4. **`tests/test_intent_endpoint.py`** — Backend tests for the intent endpoint

## Implementation Steps

### Step 1: Backend — Add Intent Models (`models.py`)

Add two new Pydantic models:

```python
class IntentRequest(BaseModel):
    """Request body for POST /api/intent."""
    text: str = Field(..., min_length=1, max_length=5000, description="The user's intent/request")

class IntentResponse(BaseModel):
    """Response for POST /api/intent."""
    issue_number: int
    title: str
    url: str = ""
    status: str = "created"
```

### Step 2: Backend — Add POST /api/intent endpoint (`dashboard_routes.py`)

Add a new route handler inside `create_router()`:

```python
@router.post("/api/intent")
async def submit_intent(request: IntentRequest) -> JSONResponse:
    """Create a GitHub issue from a user intent typed in the dashboard."""
    title = request.text[:120]  # Truncate for title
    body = request.text
    labels = list(config.planner_label)  # e.g. ["hydraflow-plan"]
    
    issue_number = await pr_manager.create_issue(
        title=title, body=body, labels=labels
    )
    
    if issue_number == 0:
        return JSONResponse(
            {"error": "Failed to create issue"}, status_code=500
        )
    
    url = f"https://github.com/{config.repo}/issues/{issue_number}"
    response = IntentResponse(
        issue_number=issue_number, title=title, url=url
    )
    return JSONResponse(response.model_dump())
```

Key design decisions:
- Use the first 120 characters of the intent as the issue title
- Use the full text as the issue body
- Label with `planner_label` (default `hydraflow-plan`) so it enters the pipeline at the planning stage
- `PRManager.create_issue()` already publishes an `ISSUE_CREATED` event, so the stream view will receive the update via WebSocket automatically

### Step 3: Backend — Write tests for intent endpoint (`tests/test_intent_endpoint.py`)

Test cases:
- `test_intent_endpoint_creates_issue` — Happy path: mock `pr_manager.create_issue` to return 42, verify response has issue_number=42
- `test_intent_endpoint_returns_error_on_failure` — `create_issue` returns 0, verify 500 response
- `test_intent_endpoint_validates_empty_text` — Empty text returns 422 (Pydantic validation)
- `test_intent_endpoint_truncates_title` — Long text (>120 chars) gets truncated for title
- `test_intent_route_is_registered` — Verify `/api/intent` appears in registered routes

### Step 4: Frontend — Add theme tokens and constants

**`ui/index.html`** — Add to `:root`:
```css
--intent-bg: rgba(88,166,255,0.06);
--card-active-border: rgba(88,166,255,0.4);
```

**`ui/src/theme.js`** — Add:
```js
intentBg: 'var(--intent-bg)',
cardActiveBorder: 'var(--card-active-border)',
```

**`ui/src/constants.js`** — Add:
```js
export const STREAM_CARD_STATUSES = ['active', 'done', 'failed', 'hitl']
```

**`ui/src/types.js`** — Add:
```js
/**
 * @typedef {{ text: string, issueNumber: number|null, timestamp: string, status: 'pending'|'created'|'failed' }} IntentData
 * @typedef {{ issueNumber: number, title: string, currentStage: string, overallStatus: string, stages: Object, pr: Object|null, branch: string, intent: string|null }} StreamCardData
 */
```

### Step 5: Frontend — Add `submitIntent` to `useHydraSocket.js`

Add to the reducer:
```js
case 'INTENT_SUBMITTED':
  return {
    ...state,
    intents: [...state.intents, {
      text: action.data.text,
      issueNumber: null,
      timestamp: new Date().toISOString(),
      status: 'pending',
    }],
  }

case 'INTENT_CREATED':
  return {
    ...state,
    intents: state.intents.map(i =>
      i.status === 'pending' && i.text === action.data.text
        ? { ...i, issueNumber: action.data.issueNumber, status: 'created' }
        : i
    ),
  }

case 'INTENT_FAILED':
  return {
    ...state,
    intents: state.intents.map(i =>
      i.status === 'pending' && i.text === action.data.text
        ? { ...i, status: 'failed' }
        : i
    ),
  }
```

Add `intents: []` to `initialState`.

Add the `submitIntent` callback:
```js
const submitIntent = useCallback(async (text) => {
  dispatch({ type: 'INTENT_SUBMITTED', data: { text } })
  try {
    const res = await fetch('/api/intent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
    if (!res.ok) {
      dispatch({ type: 'INTENT_FAILED', data: { text } })
      return null
    }
    const data = await res.json()
    dispatch({ type: 'INTENT_CREATED', data: { text, issueNumber: data.issue_number } })
    return data
  } catch {
    dispatch({ type: 'INTENT_FAILED', data: { text } })
    return null
  }
}, [])
```

Return `submitIntent` and `intents` from the hook alongside existing values.

### Step 6: Frontend — Create `IntentInput.jsx`

A chat-like input bar component:
- Full-width text input with a "Send" button
- Shows "Type your intent..." placeholder
- Disabled when not connected or orchestrator is not running
- Shows a brief loading state while submitting
- On submit, calls `submitIntent(text)` and clears the input
- Styled to look like a chat input: rounded, subtle background, prominent in the layout
- Follow existing component patterns: `const styles = {}` at bottom, pre-computed variants, theme tokens

### Step 7: Frontend — Create `StreamCard.jsx`

Per-issue conversation card component. Receives an issue timeline object (from `useTimeline`) and renders:

**Collapsed state** (for completed issues):
- Issue number, title, current stage badge, duration, status indicator
- PR link if available
- Click to expand

**Expanded state** (for active issues, or when clicked):
- Intent text (if available from intents array)
- Per-stage lifecycle rows, each showing:
  - Stage icon/color (from `PIPELINE_STAGES`)
  - Stage label + status badge
  - Semantic progress text (e.g., "Exploring codebase...", "Tests passing", "PR created")
  - Duration
  - Active stage has pulsing indicator
- Quick action buttons row:
  - "View Transcript" — calls `onViewTranscript(issueNumber)` 
  - "View PR" — opens PR URL in new tab (if PR exists)
  - "Request Changes" — calls `onRequestChanges(issueNumber)` (navigates to HITL)

Reuses existing patterns from `Timeline.jsx`:
- `StatusIndicator` component pattern
- `STAGE_META` for colors and labels
- `formatDuration` from `useTimeline`
- Pre-computed style variants per stage

### Step 8: Frontend — Create `StreamView.jsx`

Unified stream view component:
- Uses `useTimeline` hook to derive issue timelines from events/workers/prs
- Renders a list of `StreamCard` components
- Active issues auto-expand, completed issues collapse
- Filter bar (reuse pattern from `Timeline.jsx` FilterBar)
- Intent cards (pending intents that haven't matched an issue yet) appear at the top
- Empty state: "No active work. Type an intent above to get started."

### Step 9: Frontend — Restructure `App.jsx`

Replace the tab-based layout with a stream-first design:

**Layout change:**
- Keep the grid: header (full width) → sidebar (280px) + main
- Main area now has: `IntentInput` at top → Tab bar → Content
- Tab bar adds "Stream" as the first/default tab
- Stream tab renders `StreamView`
- All other tabs remain accessible (Transcript, PRs, HITL, Timeline, Livestream, System, Metrics)
- Default `activeTab` changes from `'transcript'` to `'stream'`

**New state:**
- Pass `intents` and `submitIntent` down from `useHydraSocket`
- Add `onViewTranscript` handler that sets `selectedWorker` and switches to transcript tab
- Add `onRequestChanges` handler that switches to HITL tab

**Props flow:**
```
App
  ├── Header (unchanged)
  ├── WorkerList (unchanged)
  └── Main
       ├── IntentInput(connected, orchestratorStatus, submitIntent)
       ├── TabBar (adds 'stream' as first tab)
       └── TabContent
            ├── StreamView(events, workers, prs, intents, onViewTranscript, onRequestChanges)
            ├── TranscriptView (unchanged)
            ├── PRTable (unchanged)
            ├── ... (other tabs unchanged)
```

### Step 10: Update test expectations

Update `test_dashboard_routes.py`:
- Add `/api/intent` to the expected routes set in `test_router_registers_expected_routes`

## Testing Strategy

### Backend Tests (`tests/test_intent_endpoint.py`)

1. **`test_intent_creates_issue_with_planner_label`** — Verify that `pr_manager.create_issue` is called with `config.planner_label` labels
2. **`test_intent_returns_issue_number_and_url`** — Happy path: mock `create_issue` → 42, verify response JSON
3. **`test_intent_returns_500_on_create_failure`** — `create_issue` returns 0, verify 500 status
4. **`test_intent_rejects_empty_text`** — POST with `{"text": ""}` returns 422
5. **`test_intent_truncates_long_title`** — Text > 120 chars → title is truncated, body is full text
6. **`test_intent_route_is_registered`** — `/api/intent` in router paths (update existing test)

### Frontend Tests (manual verification criteria)

Since the project uses inline React without a test runner for UI:
- Intent input renders and is disabled when disconnected
- Typing and submitting creates an intent card in the stream
- Stream cards show correct lifecycle stages
- Active cards auto-expand, completed cards collapse
- Quick actions navigate correctly
- Mobile responsive (stream view works on narrow screens)

### Existing Test Updates (`tests/test_dashboard_routes.py`)

- Update `test_router_registers_expected_routes` to include `/api/intent` in expected paths

## Acceptance Criteria

- [ ] Intent input bar visible and functional — type a request, it becomes a GitHub issue with `hydraflow-plan` label
- [ ] Stream view shows all active and recent issues as conversation cards
- [ ] Each card shows lifecycle progression (intent → plan → implement → review → merge)
- [ ] Active cards stream real-time updates with semantic progress indicators
- [ ] Completed cards collapse to summary (PR link, duration, status)
- [ ] No tab switching required for the core workflow (stream view is default)
- [ ] Feels like a chat/messaging experience, not a monitoring dashboard
- [ ] Quick actions (view transcript, view PR, request changes) on each card
- [ ] Mobile-responsive (stream view works on narrow screens)
- [ ] All existing tabs remain accessible (Transcript, PRs, HITL, Timeline, Livestream, System, Metrics)
- [ ] Backend tests pass for the new `/api/intent` endpoint
- [ ] Existing tests remain passing

## Key Considerations

### Edge Cases
- **Disconnected state**: Intent input should be disabled and show a clear visual indicator when WebSocket is disconnected
- **Dry-run mode**: `PRManager.create_issue()` returns 0 in dry-run, the UI should handle this gracefully (show error state on the intent card)
- **Long intents**: Text > 120 chars is truncated for the issue title but preserved in the body
- **Concurrent intents**: Multiple rapid submissions should each create separate issues and cards
- **Empty state**: When no issues exist and no intents submitted, show a welcoming empty state encouraging the user to type

### Backward Compatibility
- All existing tabs remain accessible — this is additive, not destructive
- The `WorkerList` sidebar is unchanged — clicking a worker still selects it and switches to transcript
- The WebSocket protocol is unchanged — no new event types from the backend
- The `useTimeline` hook is reused as-is for timeline derivation
- Existing components (`Timeline.jsx`, `TranscriptView.jsx`, etc.) are not modified

### Dependencies
- `PRManager.create_issue()` already exists and handles issue creation + event publishing
- `useTimeline` hook already derives per-issue lifecycle data from events/workers/prs
- `PIPELINE_STAGES` in `constants.js` provides stage colors and metadata
- `Timeline.jsx` provides established patterns for stage visualization that `StreamCard` can follow

### Pre-Mortem: Top 3 Failure Risks

1. **Stream view performance with many issues**: If hundreds of issues accumulate, rendering all `StreamCard` components could cause jank. Mitigation: limit visible cards (e.g., 50 most recent) and add pagination or virtual scrolling if needed. The existing `MAX_EVENTS` constant (5000) already bounds event data.

2. **Intent-to-issue matching**: When a user submits an intent, we optimistically create a local intent card. We then need to match it with the resulting issue when events arrive via WebSocket. The matching is done by text content, which could fail if the same text is submitted twice. Mitigation: also match by timestamp proximity and use the `issue_number` returned by the API response to definitively link them.

3. **Layout disruption from adding Stream as default tab**: Adding a new default tab could confuse existing users who expect to land on the transcript view. Mitigation: Stream view incorporates transcript previews per-issue, so users still see output. The transcript tab remains one click away. The worker sidebar still functions identically.

PLAN_END

SUMMARY: Add intent input bar, stream-first unified view with per-issue conversation cards, and POST /api/intent backend endpoint to transform the dashboard from tab-based monitoring to a chat-like conversational experience.

NEW_ISSUES_START
- title: Livestream tab duplicates raw event rendering inline in App.jsx
  body: "The Livestream tab in App.jsx (lines 122-133) renders events inline with `JSON.stringify(e.data).slice(0, 120)`, duplicating the dedicated `Livestream.jsx` component which uses the `EventLog` component's `eventSummary` formatter. The inline rendering at App.jsx:122-133 should be replaced with `<Livestream events={events} />` to use the proper component. This was likely left over from before the Livestream component was created. The current inline rendering shows raw JSON which is not user-friendly."
  labels: hydraflow-find
NEW_ISSUES_END
