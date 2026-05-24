import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from server.db import cleanup_stale_data, close_db, get_engine, init_db
from server.llm.credentials import MissingCredentialsError
from server.routes import (
    agents_router,
    benchmark_router,
    knowledge_files_router,
    models_router,
    rules_router,
    simulation_router,
    test_router,
)

logger = logging.getLogger(__name__)

_CLEANUP_INTERVAL_SECONDS = 3600  # run every hour
_STALE_AFTER_HOURS = 24


async def _cleanup_loop() -> None:
    """Background task: delete agents and files older than 24 h, then wait an hour."""
    while True:
        try:
            deleted = await cleanup_stale_data(get_engine(), max_age_hours=_STALE_AFTER_HOURS)
            if deleted:
                logger.info("Periodic cleanup: removed %d stale agent(s)", deleted)
        except Exception:
            logger.exception("Periodic cleanup failed — will retry next cycle")
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)


load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise the session database on startup and close it on shutdown."""
    await init_db()
    cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            # Expected during shutdown after explicit task cancellation.
            # Intentionally ignored so application teardown can continue.
            pass
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
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MissingCredentialsError)
async def _missing_credentials_handler(
    request: Request, exc: MissingCredentialsError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.include_router(agents_router)
app.include_router(knowledge_files_router)
app.include_router(models_router)
app.include_router(benchmark_router)
app.include_router(rules_router)
app.include_router(simulation_router)
app.include_router(test_router)


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
