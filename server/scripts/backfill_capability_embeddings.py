"""Backfill ``capability_embedding`` for agents created before it was wired in.

New agents get a capability embedding at creation time (see
``server.routes.agents``). Agents that predate that wiring have ``NULL`` and the
auction can only invite them inclusively. This one-off script fills the gap.

Requires an embedding API key (``OPENAI_API_KEY``); agents whose embedding cannot
be computed are left ``NULL`` and can be retried later.

Run from the repo root against the configured ``DATABASE_URL``:
    server/.venv/bin/python -m server.scripts.backfill_capability_embeddings
"""

import asyncio

from dotenv import load_dotenv

from server.db import get_engine
from server.market_hive.agent_embeddings import backfill_capability_embeddings


async def main() -> None:
    load_dotenv()
    async with get_engine().connect() as db:
        filled = await backfill_capability_embeddings(db)
    print(f"Backfilled capability_embedding for {filled} agent(s).")


if __name__ == "__main__":
    asyncio.run(main())
