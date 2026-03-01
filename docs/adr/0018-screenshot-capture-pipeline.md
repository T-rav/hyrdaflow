# ADR-0018: Screenshot Capture Pipeline Architecture

**Status:** Proposed
**Date:** 2026-03-01

## Context

HydraFlow's dashboard includes a "Report Issue" feature that captures a
screenshot of the current dashboard state, allows the user to annotate it, and
submits it as a GitHub issue with the image attached via a GitHub Gist. Because
the dashboard displays pipeline data, agent transcripts, and event logs, the
screenshot payload can inadvertently contain secrets (API keys, tokens, or
sensitive configuration values rendered in the UI).

The pipeline must balance screenshot fidelity (useful for debugging) against
security (no secret leakage in uploaded images). It must also handle
html2canvas rendering failures caused by unsupported CSS (e.g. CSS Color Level 4
`color()` functions) that vary across browser environments.

## Decision

Adopt a **defense-in-depth screenshot pipeline** with three distinct security
layers and a progressive-fallback capture strategy:

### 1. Frontend DOM redaction (always active)

Before html2canvas renders the cloned DOM, `redactSensitiveElements()` replaces
all elements matching `[data-sensitive]` with an opaque placeholder
(`"[Content redacted for security]"`). This is the **primary protection** — it
prevents sensitive content from entering the captured image at all.

Components that display unfiltered system data (e.g. `EventLog`, `TranscriptPreview`)
are marked with `data-sensitive="true"`. New components that render user-supplied
or agent-generated content must also carry this attribute.

### 2. Three-attempt progressive fallback capture

`captureDashboardScreenshot()` in `Header.jsx` tries three html2canvas
configurations in order:

1. **Full fidelity** — captures computed styles, native `devicePixelRatio`,
   cross-origin image filtering. Produces the highest-quality screenshot.
2. **Safe mode** — drops computed style cloning, uses fixed `scale: 1`. Avoids
   failures from complex CSS that html2canvas cannot parse.
3. **Aggressive sanitization** — enables `foreignObjectRendering`, strips all
   `<style>`/`<link>` elements, and forces baseline colors on every DOM element.
   Replaces any CSS `color()` function values with fallback hex colors. This
   is the last resort when the browser's CSS is entirely incompatible with
   html2canvas.

All three attempts invoke `redactSensitiveElements()` via the `onclone`
callback, ensuring redaction is never bypassed regardless of which attempt
succeeds.

### 3. Backend base64 secret scan (configurable)

Before uploading to GitHub Gist, `ReportIssueLoop` in `report_issue_loop.py`
passes the base64 payload through `screenshot_scanner.scan_base64_for_secrets()`.
This regex-based scanner checks for 13 known token patterns (GitHub PATs, AWS
keys, Slack tokens, Anthropic/OpenAI API keys, PEM private keys, and generic
secret assignments). If any pattern matches, the screenshot is **stripped** from
the report and a warning is logged.

**Important limitation:** For actual PNG screenshots, visible text undergoes
zlib compression before base64 encoding, so rendered secrets will not produce
recognizable substrings in the encoded payload. This scanner is primarily
effective against non-image payloads (SVG data URIs, plain-text blobs, or
payloads erroneously containing raw tokens). The frontend DOM redaction step
remains the principal defense.

This layer is controlled by `screenshot_redaction_enabled` (default: `True`,
env: `HYDRAFLOW_SCREENSHOT_REDACTION_ENABLED`).

### 4. Gist visibility control

`PRManager.upload_screenshot_gist()` uploads the decoded PNG as a GitHub Gist.
Visibility is controlled by `screenshot_gist_public` (default: `False`, env:
`HYDRAFLOW_SCREENSHOT_GIST_PUBLIC`). The default creates secret/unlisted gists
that require a direct link to access, limiting exposure if a screenshot
inadvertently contains sensitive information.

## Consequences

**Positive:**
- Defense-in-depth: three independent layers (DOM redaction, base64 scan, gist
  visibility) each reduce the blast radius of a missed redaction.
- Progressive fallback ensures screenshots succeed across browser environments
  with varying CSS support, avoiding blank or broken captures.
- The `data-sensitive` attribute convention is simple to adopt — new components
  only need a single attribute to opt in to redaction.
- Configuration knobs (`screenshot_redaction_enabled`, `screenshot_gist_public`)
  allow operators to tune the security/usability tradeoff per deployment.

**Trade-offs:**
- The base64 secret scanner has limited effectiveness on compressed PNG payloads.
  It is a backstop, not a primary defense. Teams must not rely on it as a
  substitute for proper `data-sensitive` annotation.
- Three capture attempts add latency to the screenshot flow (each failed attempt
  is caught and retried). In practice, the first attempt usually succeeds.
- The aggressive sanitization fallback (attempt 3) produces lower-fidelity
  screenshots with stripped styles. This is acceptable as a last resort but
  means some bug reports may have less visual context.
- Secret/unlisted gists are not truly private — anyone with the URL can view
  them. For highly sensitive deployments, operators should consider disabling
  screenshot uploads entirely or routing through a private artifact store.

## Alternatives considered

1. **Server-side rendering (Puppeteer/Playwright).**
   Rejected: adds a headless browser dependency to the backend, increases
   resource requirements, and introduces latency. Client-side html2canvas is
   sufficient for dashboard-state screenshots and avoids the operational burden.

2. **Pixel-level OCR scanning on the backend.**
   Rejected: OCR adds significant processing time and a heavy dependency
   (Tesseract or similar). The zlib-compressed base64 scan is lightweight, and
   the primary defense (DOM redaction) operates before capture.

3. **Upload screenshots as PR/issue attachments instead of Gists.**
   Rejected: GitHub issue attachments are always public on public repos and
   cannot be made unlisted. Gists provide the `--public` / unlisted toggle,
   giving operators control over visibility.

4. **Single html2canvas configuration with no fallback.**
   Rejected: html2canvas frequently fails on modern CSS features (especially
   `color()` function syntax). A single configuration would leave users with
   broken screenshot functionality on affected browsers.

## Related

- Source memory: #1734
- ADR issue: #1749
- `src/ui/src/components/Header.jsx` — `captureDashboardScreenshot()`, `redactSensitiveElements()`
- `src/ui/src/components/ReportIssueModal.jsx` — annotation canvas and submission
- `src/ui/src/constants.js` — `SENSITIVE_SELECTORS`
- `src/report_issue_loop.py` — `ReportIssueLoop._do_work()`
- `src/screenshot_scanner.py` — `scan_base64_for_secrets()`
- `src/pr_manager.py` — `PRManager.upload_screenshot_gist()`
- `src/config.py` — `screenshot_redaction_enabled`, `screenshot_gist_public`
