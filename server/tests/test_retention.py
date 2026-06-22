"""History retention (prune_trials), canvas cleanup, and manual delete endpoints."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import (
    cleanup_stale_data,
    create_round,
    create_trial,
    get_engine,
    prune_trials,
    record_message,
)
from server.db.tables import agents, messages, trials


async def _seed_trial(conn: AsyncConnection, created_at: str | None = None) -> str:
    trial_id = await create_trial(conn, "Prompt", "Test trial", "broadcast_no_consensus")
    if created_at is not None:
        await conn.execute(
            trials.update().where(trials.c.id == trial_id).values(created_at=created_at)
        )
        await conn.commit()
    return str(trial_id)


async def _trial_ids(conn: AsyncConnection) -> set[str]:
    rows = await conn.execute(select(trials.c.id))
    return {row.id for row in rows}


async def test_prune_trials_count_cap_keeps_newest(client: AsyncClient) -> None:
    async with get_engine().connect() as conn:
        # Distinct, increasing timestamps so ordering is deterministic.
        base = datetime(2026, 1, 1, tzinfo=UTC)
        created: list[tuple[str, str]] = []
        for i in range(5):
            ts = (base + timedelta(minutes=i)).isoformat(timespec="seconds")
            created.append((await _seed_trial(conn, ts), ts))

    # Keep only the 2 newest, no age cap.
    deleted = await prune_trials(get_engine(), max_trials=2, max_age_days=None)
    assert deleted == 3

    async with get_engine().connect() as conn:
        remaining = await _trial_ids(conn)
    newest_two = {created[-1][0], created[-2][0]}
    assert remaining == newest_two


async def test_prune_trials_age_cap(client: AsyncClient) -> None:
    now = datetime.now(UTC)
    async with get_engine().connect() as conn:
        old_id = await _seed_trial(conn, (now - timedelta(days=40)).isoformat(timespec="seconds"))
        fresh_id = await _seed_trial(conn, (now - timedelta(days=1)).isoformat(timespec="seconds"))

    deleted = await prune_trials(get_engine(), max_trials=None, max_age_days=30)
    assert deleted == 1

    async with get_engine().connect() as conn:
        remaining = await _trial_ids(conn)
    assert remaining == {fresh_id}
    assert old_id not in remaining


async def test_prune_trials_cascades_messages(client: AsyncClient) -> None:
    async with get_engine().connect() as conn:
        await conn.execute(
            insert(agents).values(
                id="agent_x",
                name="Agent X",
                description="d",
                system_prompt="p",
                provider="openai",
                model="gpt-4o",
                tools="[]",
                connections="[]",
            )
        )
        await conn.commit()
        old_ts = (datetime.now(UTC) - timedelta(days=99)).isoformat(timespec="seconds")
        trial_id = await _seed_trial(conn, old_ts)
        round_id = await create_round(conn, trial_id, 1, "broadcast")
        await record_message(conn, round_id, None, "agent_x", "system_broadcast", "hi")

        before = await conn.scalar(select(func.count()).select_from(messages))
    assert before and before > 0

    await prune_trials(get_engine(), max_trials=None, max_age_days=30)

    async with get_engine().connect() as conn:
        after = await conn.scalar(select(func.count()).select_from(messages))
    assert after == 0


async def test_cleanup_stale_data_preserves_history(client: AsyncClient) -> None:
    async with get_engine().connect() as conn:
        stale_ts = datetime.now(UTC) - timedelta(hours=48)
        await conn.execute(
            insert(agents).values(
                id="stale_agent",
                name="Stale",
                description="d",
                system_prompt="p",
                provider="openai",
                model="gpt-4o",
                tools="[]",
                connections="[]",
                created_at=stale_ts,
            )
        )
        await conn.commit()
        trial_id = await _seed_trial(conn)
        round_id = await create_round(conn, trial_id, 1, "broadcast")
        await record_message(conn, round_id, "stale_agent", "stale_agent", "agent_output", "hi")

    removed = await cleanup_stale_data(get_engine(), max_age_hours=24)
    assert removed == 1

    async with get_engine().connect() as conn:
        # Agent gone, but the trial + messages (with name snapshot) survive.
        assert await conn.scalar(select(func.count()).select_from(agents)) == 0
        assert (await _trial_ids(conn)) == {trial_id}
        name = await conn.scalar(select(messages.c.from_agent_name))
    assert name == "Stale"


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
