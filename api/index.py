import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

# Initialize the FastAPI app
app = FastAPI()


async def mock_agent_stream() -> AsyncGenerator[str, None]:
    """A mock stream to test your frontend-backend connection."""
    yield f"data: {json.dumps({'status': 'Backend connected. Agents standing by.'})}\n\n"
    await asyncio.sleep(1)
    yield f"data: {json.dumps({'status': 'Ready for agent integration.'})}\n\n"


@app.get("/api/test-stream")
async def test_stream() -> StreamingResponse:
    return StreamingResponse(mock_agent_stream(), media_type="text/event-stream")
