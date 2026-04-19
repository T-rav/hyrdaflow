---
id: 0067
topic: architecture
source_issue: 6335
source_phase: plan
created_at: 2026-04-10T05:43:58.108275+00:00
status: active
---

# StrEnum Fields Serialize Without Migration

StrEnum fields serialize to the same string values already persisted in storage (state.json, etc.). Converting a bare `str` field to StrEnum is schema-additive and requires no data migration per ADR-0021 (persistence architecture).
