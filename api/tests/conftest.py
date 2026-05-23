"""Shared pytest fixtures for the API test suite."""

import os

os.environ.setdefault("DB_PATH", ":memory:")  # Must be before app import

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from api.index import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Yield an async HTTP client wired directly to the ASGI app.

    The app's lifespan runs for each test, giving every test a clean
    in-memory database.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
