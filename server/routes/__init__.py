"""Shared HTTP routes — infrastructure owned by neither reasoning engine.

Agent CRUD, knowledge files, model catalogue, health and the mode-dispatched
simulation entrypoint live here. Engine-specific routes live in their own
packages: ``server.topology.routes`` and ``server.market_hive.routes``.
"""

from server.routes.agents import router as agents_router
from server.routes.files import router as knowledge_files_router
from server.routes.models import router as models_router
from server.routes.simulation import router as simulation_router
from server.routes.test import router as test_router

__all__ = [
    "agents_router",
    "knowledge_files_router",
    "models_router",
    "simulation_router",
    "test_router",
]
