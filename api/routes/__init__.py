"""Route registry — import all sub-routers here and expose them for ``index.py``."""

from api.benchmarks import router as needlehaystack_router
from api.routes.agents import router as agents_router
from api.routes.files import router as knowledge_files_router
from api.routes.test import router as test_router

__all__ = ["agents_router", "knowledge_files_router", "needlehaystack_router", "test_router"]
