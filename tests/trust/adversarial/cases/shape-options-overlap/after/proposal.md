# Shape proposal — server-side search

## Option A — Integrate search engine, approach 1

Wire the query router and index builder through Algolia. Edits:

- `src/search/query.py` — new `SearchClient` wrapper around Algolia SDK
- `src/search/index.py` — incremental index build on document write

Trade-off: extra latency budget on the write path (~30ms per doc).

## Option B — Integrate search engine, approach 2

Wire the query router and index builder through Meilisearch. Edits:

- `src/search/query.py` — new `SearchClient` wrapper around Meilisearch SDK
- `src/search/index.py` — incremental index build on document write

Trade-off: extra latency budget on the write path (~30ms per doc).

## Option C — Defer

Accept the current SQL `LIKE` query path. Cost of inaction: search
stays slow; power users churn to competitors with better search UX.
