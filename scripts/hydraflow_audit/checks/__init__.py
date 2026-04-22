"""Registering all check modules.

Import each principle module so its `@register(...)` decorators fire. Unimplemented
principles (no module imported, or rows without a matching function) surface as
NOT_IMPLEMENTED findings — by design, to keep ADR-0044 and the audit in lockstep.
"""

from . import (
    p1_docs,  # noqa: F401
    p2_architecture,  # noqa: F401
    p3_testing,  # noqa: F401
    p4_quality,  # noqa: F401
    p5_ci,  # noqa: F401
    p6_agents,  # noqa: F401
)
