"""MockWorld — alternative adapter set for HydraFlow.

This package contains Fake adapters that satisfy the same Ports as the
production adapters (PRPort, WorkspacePort, IssueStorePort, IssueFetcherPort,
plus the LLM runner ports). They are always loaded; selection between
real and Fake happens at entrypoint level, not via config.

See docs/superpowers/specs/2026-04-26-sandbox-tier-scenarios-design.md
"""
