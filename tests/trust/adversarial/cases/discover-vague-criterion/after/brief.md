## Intent

Deliver a materially better search experience for power users — the
top 5% of our customer base by query volume — so they stop falling
back to `grep`-ing the raw export API. This is a retention play: three
of our largest accounts listed "search UX" as a churn risk in their
last QBR.

## Affected area

- `src/search/query.py` — query parser and ranker
- `src/search/index.py` — Tantivy index build
- `src/ui/search/SearchBar.tsx` — the power-user command palette
- `src/api/search_routes.py` — the `/api/search` endpoint

## Acceptance criteria

- The search is faster.
- Users are happier with search.
- Power users love it.

## Open questions

- Should we ship a keyboard-first command palette, a classic search
  bar with filters, or both behind a feature flag?
- Do we keep Tantivy or migrate to Meilisearch for typo tolerance?

## Known unknowns

- Whether our current query logs are detailed enough to mine for
  common intents, or whether we need to add structured query
  instrumentation first.
