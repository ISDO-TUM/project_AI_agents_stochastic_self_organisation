import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

# Initialize the FastAPI app
app = FastAPI(
    title="SAP AI Agents API",
    description=(
        "API for SAP AI Agent orchestration and integration with "
        "stochastic self-organization capabilities."
    ),
    version="0.1.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)


async def mock_agent_stream() -> AsyncGenerator[str, None]:
    """A mock stream to test your frontend-backend connection."""
    yield f"data: {json.dumps({'status': 'Backend connected. Agents standing by.'})}\n\n"
    await asyncio.sleep(1)
    yield f"data: {json.dumps({'status': 'Ready for SAP integration.'})}\n\n"


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
                        '"Ready for SAP integration."}\n\n'
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
    connection is working properly. It sends status updates at 1-second intervals.

    Returns:
        StreamingResponse: A stream of JSON status messages in SSE format.

    Example:
        ```
        curl http://localhost:8000/api/test-stream
        ```
    """
    return StreamingResponse(mock_agent_stream(), media_type="text/event-stream")
