"""Route registry — import all sub-routers here and expose them for ``index.py``."""

from server.benchmarks import benchmark_router
from server.routes.agents import router as agents_router
from server.routes.files import router as knowledge_files_router
from server.routes.models import router as models_router
from server.routes.rules import rules_router
from server.routes.simulation import router as simulation_router
from server.routes.test import router as test_router

__all__ = [
    "agents_router",
    "benchmark_router",
    "knowledge_files_router",
    "models_router",
    "rules_router",
    "simulation_router",
    "test_router",
]
