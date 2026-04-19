---
id: 0045
topic: architecture
source_issue: 6325
source_phase: plan
created_at: 2026-04-10T04:51:52.058659+00:00
status: active
---

# Logger names resolve to full module path from __name__

Modules using logging.getLogger(__name__) resolve to the full dotted module path (e.g., hydraflow.shape_phase), not just the filename (shape_phase). Tests that capture logs must use the full module path or logger name matchers will fail to find the expected logs.
