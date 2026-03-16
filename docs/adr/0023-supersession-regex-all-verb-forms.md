# ADR-0023: Supersession Regex Must Include All Verb Forms

**Status:** Accepted
**Date:** 2026-03-08

## Context

HydraFlow's ADR tooling needs to detect when one ADR supersedes another so that
the pre-validator (`src/adr_pre_validator.py`) can cross-check status fields and
the council reviewer (`src/adr_reviewer.py`) can exclude superseded ADRs from
the active index. The English verb "supersede" appears in four common forms in
ADR prose:

| Form | Example |
|------|---------|
| **supersede** (base) | "This ADR will supersede ADR-0006" |
| **supersedes** (3rd person) | "This ADR supersedes ADR-0006" |
| **superseded** (past tense) | "This ADR superseded ADR-0006" |
| **superseding** (progressive) | "superseding ADR-0006 effective immediately" |

An earlier iteration of the regex omitted the `ed` past-tense branch, which
silently missed phrases like "This ADR superseded ADR-0006" — the most common
form in older ADRs that have already been acted upon. Because the validator uses
the match to enforce that referenced ADRs carry `Status: Superseded`, a missed
match means stale ADRs stay listed as active with no warning.

The same concern applies to the task-link parser in `src/models.py`, which uses
a separate `supersedes?` pattern for GitHub issue references (`#NNN`). While
that pattern covers the base and 3rd-person forms, it does not capture
`superseded` or `superseding` in issue bodies.

## Decision

Standardise on the regex stem `supersed(?:es?|ed|ing)` wherever HydraFlow
matches supersession language, covering all four verb forms in a single
non-capturing group:

- `es?` matches **supersede** and **supersedes**
- `ed` matches **superseded**
- `ing` matches **superseding**

Concretely, the following call sites must use this pattern:

1. **`src/adr_pre_validator.py`** — `_SUPERSEDE_RE` for ADR-to-ADR references
   (already updated to the full pattern).
2. **`src/models.py`** — `_LINK_PATTERNS` entry for task-link supersession
   must use the same `supersed(?:es?|ed|ing)` stem so that issue-body
   references such as "superseded #5" and "superseding #12" are captured.

Any future code that detects supersession language must reuse this pattern
rather than inventing a new variant.

### Operational impact on HydraFlow workers

- **Triage / Plan phases:** No direct impact — these phases do not parse
  supersession references.
- **Review phase:** The ADR council reviewer builds an index of active ADRs
  by filtering out those with `Status: Superseded`. Correct regex matching
  ensures the `_check_supersession()` validator catches all references, so
  the council sees an accurate active-ADR list.
- **HITL phase:** Fewer false negatives in validation means fewer
  human-escalated ADR issues caused by missed supersession links.

## Consequences

**Positive**

- Eliminates silent misses for past-tense supersession references, which are
  the most common form in mature ADR sets.
- Single canonical pattern across the codebase reduces the risk of drift
  between ADR validation and task-link parsing.
- Easy to extend: adding future verb forms (e.g., hypothetical irregular
  conjugations) requires updating one pattern.

**Negative / Trade-offs**

- The broader pattern could match in unexpected contexts (e.g., prose that
  mentions "superseding" without an ADR reference), but the regex requires an
  `ADR-NNNN` or `#NNN` suffix so false positives remain unlikely.
- Aligning `models.py` task-link patterns with the full verb stem may surface
  previously undetected links in existing issue bodies, requiring a one-time
  review of matched results.

## Alternatives considered

1. **Keep `supersedes?` (base + 3rd person only)** — rejected because it
   silently misses `superseded`, the most common form in already-acted-upon
   ADRs.
2. **Full word list instead of regex** — rejected as more verbose and harder
   to maintain; the single stem pattern is compact and self-documenting.
3. **Case-sensitive matching** — rejected because ADR authors mix case
   inconsistently; `re.IGNORECASE` is already used and should remain.

## Related

- Source memory: [#2365 — Supersession regex must include all verb forms](https://github.com/T-rav/hydra/issues/2365)
- Implementing issue: [#2374](https://github.com/T-rav/hydra/issues/2374)
- ADR pre-validator: `src/adr_pre_validator.py` (`_SUPERSEDE_RE`)
- Task-link parser: `src/models.py` (`_LINK_PATTERNS`)
