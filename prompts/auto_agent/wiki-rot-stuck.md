# Auto-Agent — wiki-rot-stuck Playbook

{{> _envelope.md}}

## Sub-label: wiki-rot-stuck

Wiki entries are stale. Read what changed in the codebase since the entry was
written; rewrite the entry, don't delete it unless the feature is gone.

## Specific guidance

The wiki-rot detector flagged one or more wiki entries as out-of-sync with
recent code changes.

Order of operations:

1. Read the affected wiki entry. Note its `last_updated` timestamp.
2. `git log --since=<last_updated>` against the files the entry references.
3. Rewrite the entry to match the current code reality, preserving the prose
   structure (intent, mechanism, gotchas).
4. If the feature the entry describes is gone, replace the entry with a
   one-paragraph "removed in <PR>" stub rather than deleting it.

The wiki is institutional memory. Prefer "rewrite + tombstone" over "delete".
