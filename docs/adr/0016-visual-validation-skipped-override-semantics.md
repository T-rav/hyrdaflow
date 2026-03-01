# ADR-0016: VisualValidation SKIPPED Override Semantics — Partial Suppression by Design

**Status:** Proposed
**Date:** 2026-03-01

## Context

After a PR is merged, `PostMergeHandler._should_create_verification_issue` decides
whether to open a human-verification issue. The decision uses three signals:

1. **Diff-based detection** (`_USER_SURFACE_DIFF_RE`): Does the diff touch UI files
   (`.tsx`, `.jsx`, `.css`, `src/ui/`, etc.)?
2. **Keyword-based manual cues** (`_MANUAL_VERIFY_KEYWORDS`): Does the issue
   title/body or the judge's verification instructions contain words like `ui`,
   `button`, `visual`, `frontend`, etc.?
3. **Visual-validation policy** (`VisualValidationDecision`): An explicit REQUIRED
   or SKIPPED policy set via the `hydraflow-visual-skip` label or pipeline logic.

When operators apply the `hydraflow-visual-skip` label, they expect verification
issues to be suppressed. However, the SKIPPED policy only disables signal (1) — the
diff-based user-surface check — while signal (2) — keyword-based manual cues — still
fires. This means a SKIPPED override will *not* prevent a verification issue if the
issue text or judge instructions contain trigger words like "ui", "button", or
"visual".

This "soft skip" behaviour was an intentional design choice (documented in the method
docstring as "still honours manual cues") but contradicts the common expectation that
a skip label fully suppresses verification issue creation. It has been a recurring
source of confusion when debugging why verification issues appear despite a skip
label.

Related code: `src/post_merge_handler.py`, lines 417–481.

## Decision

Adopt **partial suppression** as the documented, intentional behaviour for the
SKIPPED visual-validation policy:

- **SKIPPED suppresses**: the diff-based user-surface check
  (`_USER_SURFACE_DIFF_RE`). Even if the PR modifies `.tsx`, `.css`, or `src/ui/`
  files, the SKIPPED policy will prevent that signal from triggering a verification
  issue.

- **SKIPPED does NOT suppress**: keyword-based manual cues
  (`_MANUAL_VERIFY_KEYWORDS`). If the issue title, body, or judge verification
  instructions contain words like `ui`, `button`, `visual`, `screen`, `page`,
  `browser`, `click`, `manual`, `frontend`, or `form`, a verification issue will
  still be created regardless of the SKIPPED policy.

- **REQUIRED always forces**: a verification issue (when instructions exist),
  bypassing all heuristics.

The rationale for this asymmetry is safety: keyword cues in the issue text represent
an explicit human signal that verification matters. Silently suppressing those cues
with a label would risk merging user-facing changes without any verification
checkpoint. The diff-based check, by contrast, is a heuristic that can produce false
positives (e.g., a `.css` formatting-only change) and is therefore safe to override.

## Consequences

**Positive:**

- Provides a safety net: even when an operator skips visual validation, issues that
  explicitly mention user-facing work still get a verification checkpoint.
- Reduces the risk of merging broken UI changes that an operator did not realise were
  user-facing when applying the skip label.
- The diff-based heuristic (the most common source of false-positive verification
  issues) is fully suppressible, which satisfies the primary use case for the skip
  label.

**Negative / Trade-offs:**

- Operators may be confused when verification issues appear despite applying the skip
  label. The root cause is keyword cues in the issue text — not a bug.
- To fully suppress verification, operators must either: (a) remove trigger keywords
  from the issue text, or (b) implement a future "force-skip" policy that overrides
  both signals.
- The keyword list (`_MANUAL_VERIFY_KEYWORDS`) is static and broad; words like `ui`
  or `page` can match non-visual contexts (e.g., "update the wiki page").

## Alternatives considered

- **Full suppression ("force skip")**: SKIPPED disables both diff and keyword checks.
  Simpler mental model, but risks silently skipping verification for genuinely
  user-facing changes. Could be added as a separate `FORCE_SKIPPED` policy value
  in the future if the partial-suppression approach proves too noisy.

- **No override at all**: Remove the SKIPPED policy entirely and always use
  heuristics. This removes operator control and makes false-positive verification
  issues harder to suppress.

- **Configurable keyword list**: Move `_MANUAL_VERIFY_KEYWORDS` to config so
  operators can tune sensitivity. Adds complexity without solving the core semantics
  question; could be a follow-up if the static list proves too broad.

## Debugging guide

When a verification issue is created despite a `hydraflow-visual-skip` label:

1. Check the issue title and body for any of the keywords in
   `_MANUAL_VERIFY_KEYWORDS` (see `src/post_merge_handler.py`).
2. Check the judge's `verification_instructions` output for the same keywords.
3. If a keyword match is found, that is the cause — the SKIPPED policy only
   suppresses diff-based detection, not keyword cues.

## Related

- Source memory issue: [#1725](https://github.com/T-rav/hydra/issues/1725)
- ADR tracking issue: [#1747](https://github.com/T-rav/hydra/issues/1747)
- Implementation: `src/post_merge_handler.py` (`_should_create_verification_issue`)
- Models: `src/models.py` (`VisualValidationPolicy`, `VisualValidationDecision`)
