# ADR-0013: Screenshot Capture Pipeline Architecture

**Status:** Superseded by ADR-0018
**Date:** 2026-03-01

## Context

HydraFlow's dashboard needs a way for operators to report bugs with visual
context. Screenshots of the dashboard state at the time of a bug are far more
useful than text descriptions alone, but capturing browser-rendered content
reliably is non-trivial — cross-origin images, CSS Color 4 functions, and
varying browser rendering engines all cause `html2canvas` to fail in
unpredictable ways.

The pipeline also needs to transport large binary payloads (PNG screenshots)
from the browser to a GitHub issue without bloating the issue body or
requiring a dedicated image-hosting service.

## Decision

Adopt a **multi-stage screenshot capture and upload pipeline** with three
capture fallback tiers and GitHub Gist-based image hosting:

### Capture (Frontend)

1. **Full fidelity** (`Header.jsx`): `html2canvas` with computed style
   resolution via `onclone`, device-pixel-ratio scaling, and cross-origin
   image filtering. This produces the highest quality screenshot but is most
   susceptible to CSS parsing failures.

2. **Safe mode** (`Header.jsx`): Simplified `html2canvas` call with fixed
   `scale: 1`, no style cloning, and cross-origin image filtering. Handles
   most CSS parsing edge cases that break the full-fidelity tier.

3. **Sanitized clone** (`Header.jsx`): Aggressive DOM sanitization — removes
   all stylesheets, forces deterministic fallback colors (`#c9d1d9` text,
   `#0d1117` background, `#30363d` border), strips unsupported CSS `color()`
   functions, and enables `foreignObjectRendering`. This is the last resort
   and always produces a usable (if visually degraded) capture.

Each tier catches errors and falls through to the next. If all three fail,
the report is submitted without a screenshot.

### Transport

1. `ReportIssueModal.jsx` receives the captured `dataURL`, renders it on an
   annotation canvas (allowing the user to draw on the screenshot), and
   converts the annotated result to a base64 PNG string.

2. The frontend POSTs to `/api/report` with the base64 PNG, a text
   description, and environment metadata (orchestrator status, queue depths,
   app version).

3. `dashboard_routes.py` creates a `PendingReport` and enqueues it in
   `StateTracker` (JSON-persisted FIFO queue) for immediate acknowledgement.

### Upload & Issue Creation

1. `ReportIssueLoop` (background worker) dequeues pending reports from
   `StateTracker`.

2. `PRManager.upload_screenshot_gist()` decodes the base64 PNG, writes it to
   a temp file, and uploads via `gh gist create --public --filename
   screenshot.png`. The returned gist URL is converted to a raw
   `gist.githubusercontent.com` CDN URL for direct image embedding.

3. The loop builds an issue body with the screenshot as a markdown image link
   and invokes `gh issue create` to file the bug report.

### Public Gist Decision

Gists are created with the `--public` flag. This is intentional: public gists
provide stable, unauthenticated CDN URLs that render inline in GitHub issue
bodies without access-control issues. The screenshots contain only dashboard
UI state — no secrets, tokens, or credentials are captured (cross-origin
images are filtered out, and the DOM sanitizer strips external resources).

## Consequences

**Positive:**
- Three-tier fallback makes screenshot capture resilient across browsers and
  CSS edge cases — operators always get the best quality their environment
  supports.
- Async queue (`PendingReport` in `StateTracker`) decouples the UI response
  from the potentially slow gist upload + issue creation, keeping the
  dashboard responsive.
- GitHub Gists as image hosting avoids adding an external storage dependency
  (S3, Cloudinary, etc.) while providing reliable CDN delivery.
- Environment metadata attached to reports gives developers immediate context
  about system state at the time of the bug.

**Trade-offs:**
- Public gists expose dashboard screenshots to anyone with the URL. This is
  acceptable for development/internal use but may need revisiting for
  deployments with sensitive data visible in the dashboard.
- The base64 PNG transport doubles the payload size (~33% overhead for base64
  encoding) compared to multipart upload. At typical dashboard screenshot
  sizes (< 2 MB) this is acceptable; the 5 MB `max_length` cap on
  `ReportIssueRequest.screenshot_base64` prevents abuse.
- `html2canvas` is a client-side rendering library that approximates browser
  rendering — it will never produce pixel-perfect screenshots. The sanitized
  clone tier intentionally trades visual fidelity for reliability.
- FIFO queue in `StateTracker` is not durable across process restarts if the
  JSON file is lost. This is consistent with other HydraFlow state management
  (see ADR-0008 discussion of filesystem-based state).

## Alternatives considered

1. **Server-side screenshot capture (Puppeteer/Playwright).**
   Rejected: adds a headless browser dependency to the backend, increases
   resource usage, and cannot capture the exact viewport state the operator
   sees (including transient UI states, scroll position, annotations).

2. **Multipart file upload instead of base64.**
   Considered but deferred: would reduce payload size and simplify binary
   handling, but requires changes to the API contract and frontend fetch
   logic. The current base64 approach works within the JSON-only API pattern
   used throughout the dashboard.

3. **Private gists with token-based access.**
   Rejected for now: private gists require authentication to view, which
   breaks inline image rendering in GitHub issue bodies for users without the
   gist owner's credentials. If sensitive data appears in screenshots, a
   better mitigation is redaction at capture time rather than access control
   on the hosted image.

4. **GitHub issue attachment upload via the API.**
   Rejected: the GitHub REST API does not support programmatic attachment
   uploads to issues. The `gh` CLI's gist feature provides a convenient
   workaround.

## Related

- Source memory: #1700
- ADR issue: #1704
- `src/ui/src/components/Header.jsx` (capture + three-tier fallback)
- `src/ui/src/components/ReportIssueModal.jsx` (annotation + base64 conversion)
- `src/dashboard_routes.py` (`POST /api/report` endpoint)
- `src/models.py` (`PendingReport`, `ReportIssueRequest`, `ReportIssueResponse`)
- `src/state.py` (`enqueue_report`, `dequeue_report`)
- `src/report_issue_loop.py` (`ReportIssueLoop` background worker)
- `src/pr_manager.py` (`upload_screenshot_gist` method)
