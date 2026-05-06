---
id: "01KQV37D10M06PGF32CF77W6K6"
name: "RepoWikiStore"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/repo_wiki.py:RepoWikiStore"
aliases: ["repo wiki store", "wiki store", "per-repo wiki"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668780+00:00"
updated_at: "2026-05-05T03:35:36.668781+00:00"
---

## Definition

File-based per-repo wiki manager (ADR-0032). Owns the on-disk layout for both the self-repo wiki (flattened directly under wiki_root so it can live at docs/wiki/ alongside code) and managed-repo wikis (nested under wiki_root/owner/repo). Provides ingest, lookup, indexing, lint, and append-only operation logging across the topic pages and structured WikiIndex.

## Invariants

- Self-repo pages live directly under wiki_root; every other slug is nested under wiki_root/owner/repo.
- ingest() updates topic pages, refreshes index.json/index.md, and appends to log.jsonl in a single operation.
- When a tracked_root with per-entry layout is configured, reads prefer it and fall back to the legacy topic-page layout.
