"""Manual history-delete endpoints.

The former automatic retention sweep (``cleanup_stale_data`` / ``prune_trials``)
was removed — data persists until the user deletes it — so only the explicit
delete endpoints remain under test.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import create_trial, get_engine


async def _seed_trial(conn: AsyncConnection) -> str:
    return str(await create_trial(conn, "Prompt", "Test trial", "broadcast_no_consensus"))


async def test_delete_single_trial_endpoint(client: AsyncClient) -> None:
    async with get_engine().connect() as conn:
        keep_id = await _seed_trial(conn)
        drop_id = await _seed_trial(conn)

    resp = await client.delete(f"/api/history/trials/{drop_id}")
    assert resp.status_code == 204
    assert (await client.delete(f"/api/history/trials/{drop_id}")).status_code == 404

    remaining = {t["id"] for t in (await client.get("/api/history/trials")).json()}
    assert remaining == {keep_id}


async def test_clear_all_history_endpoint(client: AsyncClient) -> None:
    async with get_engine().connect() as conn:
        await _seed_trial(conn)
        await _seed_trial(conn)

    resp = await client.delete("/api/history/trials")
    assert resp.status_code == 204
    assert (await client.get("/api/history/trials")).json() == []
