"""Route registry — import all sub-routers here and expose them for ``index.py``."""

from api.routes.agents import router as agents_router
from api.routes.files import router as knowledge_files_router

__all__ = ["agents_router", "knowledge_files_router"]
