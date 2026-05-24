"""Shared pytest fixtures for the API test suite."""

import os
from collections.abc import AsyncGenerator

import pytest

# Tests always run against an in-memory SQLite database, regardless of any
# DATABASE_URL in the shell or .env. Set before importing the app so the
# value is in place before its lifespan builds the engine. ``load_dotenv``
# does not override already-set variables, so this wins.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from httpx import ASGITransport, AsyncClient

from server.index import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Yield an async HTTP client wired directly to the ASGI app.

    The app's lifespan runs for each test, giving every test a clean
    in-memory database.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
