---
id: 0002
topic: dependencies
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T06:57:24.154763+00:00
status: active
---

# Data Schema Evolution & Transitive Dependency Tracking

Manage data schemas through changes using: embed schema_version in each JSON line for self-describing records; use Pydantic defaults so old records missing new fields deserialize without migration code. Scan transitive dependencies recursively when invalidating items, updating all ancestors to point to final successors with depth limits to prevent infinite loops. Format complete content before truncating to character limits; use unconditional overwrite for small files; use atomic writes with rotate_backups for natural versioning and recovery. For external APIs not returning memory IDs, use sha256(text)[:16] as synthetic content hashes for temporal tracking.
