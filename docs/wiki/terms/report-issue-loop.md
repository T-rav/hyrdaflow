---
id: "01KR9A3F20M01PGF32CF88W9A9"
name: "ReportIssueLoop"
kind: "loop"
bounded_context: "builder"
code_anchor: "src/report_issue_loop.py:ReportIssueLoop"
aliases: ["report issue loop", "bug report loop", "dashboard report processor"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Background loop that dequeues pending bug reports from state, saves any attached screenshots to temp files, and invokes the Claude CLI with `/hf.issue` so the agent can see the image, research the codebase, and file a well-structured GitHub issue (ADR-0028). This is the same issue-filing flow triggered by dashboard bug reports. Supports base64-encoded screenshot payloads and scans them for secrets before saving. Caps retries at 5 attempts per report.

## Invariants

- Screenshot payloads are scanned for secrets before being written to disk.
- Reports cap at `_MAX_REPORT_ATTEMPTS` (5) before being abandoned.
- Kill-switch is via `enabled_cb("report_issue")` (ADR-0049).
