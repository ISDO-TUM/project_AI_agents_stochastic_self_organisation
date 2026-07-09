"""The post length guard keeps replies terse (deltas, not walls of text)."""

from __future__ import annotations

import json

import pytest

from server.market_hive.tools import (
    MAX_PROPOSAL_CHARS,
    MAX_REPLY_CHARS,
    PostToBlackboardInput,
    PostToBlackboardTool,
)


@pytest.mark.asyncio
async def test_overlong_reply_is_rejected_without_db_write() -> None:
    tool = PostToBlackboardTool()
    long_reply = "x" * (MAX_REPLY_CHARS + 1)
    # No db in context: if the guard fails to short-circuit, the code will fault
    # on ctx["db"], so a clean error result proves the guard ran first.
    result = await tool.execute(
        PostToBlackboardInput(
            content=long_reply, entry_type="reply", thread_id="t1", reply_to="e1"
        ),
        {"run_id": "r1", "agent_id": "a1", "thread_id": "t1", "round": 3},
    )
    parsed = json.loads(result)
    assert "error" in parsed
    assert "shorten" in parsed["error"].lower() or "too long" in parsed["error"].lower()


@pytest.mark.asyncio
async def test_reply_at_limit_passes_the_guard() -> None:
    tool = PostToBlackboardTool()
    ok_reply = "x" * MAX_REPLY_CHARS
    # At-limit content passes the guard, then faults on the missing db — which
    # proves the guard did NOT reject it. A KeyError('db') is the expected signal.
    with pytest.raises(KeyError):
        await tool.execute(
            PostToBlackboardInput(
                content=ok_reply, entry_type="reply", thread_id="t1", reply_to="e1"
            ),
            {"run_id": "r1", "agent_id": "a1", "thread_id": "t1", "round": 3},
        )


@pytest.mark.asyncio
async def test_proposal_uses_higher_ceiling() -> None:
    tool = PostToBlackboardTool()
    # A proposal longer than the reply cap but under the proposal cap must pass
    # the guard (faults later on missing db).
    content = "x" * (MAX_REPLY_CHARS + 100)
    assert MAX_REPLY_CHARS + 100 <= MAX_PROPOSAL_CHARS
    with pytest.raises(KeyError):
        await tool.execute(
            PostToBlackboardInput(content=content, entry_type="proposal", thread_id="t1"),
            {"run_id": "r1", "agent_id": "a1", "thread_id": "t1", "round": 1},
        )
