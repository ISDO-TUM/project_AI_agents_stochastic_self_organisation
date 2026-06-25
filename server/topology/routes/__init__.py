"""HTTP routes owned by the Topology engine.

History, statistics and rules are all V0/topology concerns — they read and
shape the ``trials → rounds → connections → messages`` trace produced by
``run_topology``. They live inside the engine package (not the shared
``server/routes/``) so the topology surface is self-contained.
"""

from server.topology.routes.history import router as history_router
from server.topology.routes.rules import rules_router
from server.topology.routes.statistics import router as statistics_router

__all__ = ["history_router", "rules_router", "statistics_router"]
