# Repo Wiki

Per-target-repo LLM knowledge bases ([ADR-0032](../docs/adr/0032-per-repo-wiki-knowledge-base.md)). Each entry is a standalone markdown file with YAML frontmatter, grouped under topic directories.

## Layout

```
repo_wiki/
└── {owner}/{repo}/
    ├── index.md                     # human-readable index, regenerated deterministically
    ├── log/{issue_number}.jsonl     # per-issue append-only audit
    ├── architecture/
    ├── patterns/
    ├── gotchas/
    ├── testing/
    └── dependencies/
        └── {id}-issue-{N}-{slug}.md
```

## Entry format

```markdown
---
id: 0042
topic: patterns
source_issue: 100
source_phase: plan | review | synthesis | legacy-migrated
created_at: 2026-04-18T14:22:00Z
status: active | stale | superseded
---

# Short title

Markdown body.
```

## Lifecycle

- **Writes** happen automatically during plan and review phases (`src/repo_wiki_ingest.py`, wired in a later phase). Entries land in the producing issue's worktree and ship with that issue's PR.
- **Maintenance** (mark stale, prune, synthesis) runs in `src/repo_wiki_loop.py`, which opens its own auto-merged PR titled `chore(wiki): maintenance <date>`.
- **Index** (`index.md` per repo) is regenerated from entry frontmatter — do not hand-edit. It will be regenerated on next maintenance run.

## Design

See [`docs/git-backed-wiki-design.md`](../docs/git-backed-wiki-design.md).
