import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from server.db import close_db, init_db
from server.llm.credentials import MissingCredentialsError
from server.llm.langfuse_setup import langfuse_context
from server.market_hive.routes import router as market_hive_router
from server.routes import (
    agents_router,
    knowledge_files_router,
    models_router,
    simulation_router,
    test_router,
)
from server.topology.benchmarks import benchmark_router
from server.topology.routes import history_router, rules_router, statistics_router

# Uvicorn's own dictConfig (Config.configure_logging(), run before this module
# is imported) only touches its own "uvicorn"/"uvicorn.error"/"uvicorn.access"
# loggers — it never sets a level or handler on the root logger. Without this,
# every `logging.getLogger(__name__).info(...)` in server/* (swarm promotion,
# equilibrium, and termination decisions included) silently resolves to
# root's default WARNING threshold and never reaches the terminal, even with
# --reload running in the foreground. LOG_LEVEL lets DEBUG be dialed in for a
# specific run without a code change.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


# Search upward from this file so the .env at the repo root is always found,
# regardless of which directory uvicorn / uv run is invoked from.
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=False)
load_dotenv(override=False)  # also pick up any local server/.env if present

# Remove empty-string BASE_URL vars so SDK clients fall back to their own
# defaults.  The .env template ships these lines uncommented but empty as
# placeholders; passing "" to the OpenAI/Anthropic/Groq/Gemini constructors
# causes them to build request URLs without an http(s):// scheme, which then
# raises "Connection error." at runtime.
_BASE_URL_VARS = (
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "GROQ_BASE_URL",
    "GEMINI_BASE_URL",
    "LLM_PROXY_API_KEY",
)
for _var in _BASE_URL_VARS:
    if not os.environ.get(_var):  # missing or empty → clean up
        os.environ.pop(_var, None)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise the session database on startup and close it on shutdown.

    Note: there is deliberately NO periodic cleanup task here. Agents, knowledge
    files and run history persist until the user deletes them explicitly — the
    former 24h stale-agent sweep and trial pruning were removed so data survives
    long-running deployments.
    """
    await init_db()
    try:
        yield
    finally:
        # Drain any Langfuse events still buffered in the background consumer so
        # they survive the container stopping (e.g. a Railway redeploy) instead
        # of being dropped mid-batch.
        try:
            langfuse_context.flush()
        except Exception:
            logger.exception("Langfuse flush on shutdown failed — continuing teardown")
        await close_db()


app = FastAPI(
    title="AI Agents API",
    description=(
        "API for AI Agent orchestration and integration with "
        "stochastic self-organization capabilities."
    ),
    version="0.1.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
    redirect_slashes=False,
)

_allowed_origins = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-LLM-Provider",
        "X-LLM-API-Key",
        "X-LLM-Model",
        "X-Request-ID",
        "X-User-Id",
    ],
)

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "0",  # modern browsers ignore this; rely on CSP instead
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class _SecurityHeadersMiddleware:
    """Attach security-hardening response headers to every reply.

    Implemented as a plain ASGI middleware rather than ``@app.middleware("http")``
    (Starlette's ``BaseHTTPMiddleware``). ``BaseHTTPMiddleware`` runs the entire
    downstream call — including this app's long-lived SSE ``StreamingResponse``
    for ``POST /api/simulation/run`` — inside a *second* task with its own anyio
    cancel scope. When a client disconnects mid-stream (a dropped proxy, or the
    browser aborting the fetch — e.g. Next's Fast Refresh forcing a full page
    reload), that scope cancels everything running underneath it, including the
    swarm orchestrator's own best-effort "mark the run interrupted" cleanup and
    the DB connection pool's teardown of the now-defunct connection. That was
    producing a storm of ``asyncio.CancelledError`` / asyncpg "Exception
    terminating connection" tracebacks on every dropped SSE connection, even
    though the run itself was already being handled gracefully. A pure ASGI
    middleware only wraps ``send``, so it adds no extra task or cancel scope
    around the request.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for header, value in _SECURITY_HEADERS.items():
                    headers[header] = value
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


app.add_middleware(_SecurityHeadersMiddleware)


@app.exception_handler(MissingCredentialsError)
async def _missing_credentials_handler(
    request: Request, exc: MissingCredentialsError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# Shared platform routes (owned by neither engine).
app.include_router(agents_router)
app.include_router(knowledge_files_router)
app.include_router(models_router)
app.include_router(simulation_router)
app.include_router(test_router)

# Topology engine routes.
app.include_router(history_router)
app.include_router(statistics_router)
app.include_router(rules_router)
app.include_router(benchmark_router)

# Market-Hive (ECSAS) engine routes.
app.include_router(market_hive_router)


@app.get("/api/health", tags=["Health"], summary="Health check")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def mock_agent_stream() -> AsyncGenerator[str, None]:
    """A mock stream to test your frontend-backend connection."""
    yield f"data: {json.dumps({'status': 'Backend connected. Agents standing by.'})}\n\n"
    await asyncio.sleep(1)
    yield f"data: {json.dumps({'status': 'Ready for agent integration.'})}\n\n"


@app.get(
    "/api/test-stream",
    tags=["Testing"],
    summary="Test streaming endpoint",
    description=(
        "Returns a server-sent events (SSE) stream for testing frontend-backend connectivity."
    ),
    responses={
        200: {
            "description": "Stream of status messages",
            "content": {
                "text/event-stream": {
                    "example": (
                        'data: {"status": "Backend connected. '
                        'Agents standing by."}\n\ndata: {"status": '
                        '"Ready for integration."}\n\n'
                    )
                }
            },
        }
    },
)
async def test_stream() -> StreamingResponse:
    """
    Test the backend connection with a streaming response.

    This endpoint returns server-sent events (SSE) to verify that the frontend-backend
    connection is working properly. It sends two status messages with a 1-second delay
    between them, then closes the stream.

    Returns:
        StreamingResponse: A stream of JSON status messages in SSE format.

    Example:
        ```
        curl http://localhost:8000/api/test-stream
        ```
    """
    return StreamingResponse(mock_agent_stream(), media_type="text/event-stream")
