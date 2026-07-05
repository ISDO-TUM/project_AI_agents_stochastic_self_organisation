"""Tests for stand_down persistence, tool, and table."""

from __future__ import annotations


def test_swarm_stand_downs_table_shape() -> None:
    from server.db.tables import swarm_stand_downs

    cols = {c.name for c in swarm_stand_downs.columns}
    assert {"run_id", "agent_id", "thread_id", "round", "reason", "created_at"} <= cols
