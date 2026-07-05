"""Mirror a swarm run into the shared history tables (trials → rounds → messages).

The topology engine records every run in ``trials → rounds → connections →
messages``, and that event log is what the history page, the statistics
dashboards and the Langfuse session linkage are all built on. Rather than teach
those views a second data model, a swarm run mirrors its ``SimulationStep``
stream into the same tables:

- every run gets a ``trials`` row (mode ``"swarm"``) grouped under an experiment,
- each phase (auction, proposals, vote, discussion round N, final) becomes a
  ``rounds`` row,
- each board action becomes a ``messages`` row from the acting agent to the
  shared blackboard (``to_agent_id`` NULL — the statistics endpoints synthesise
  the agent→Blackboard edges from the ``swarm_*`` message types).

Mirroring is strictly best-effort: a failed history write must never break the
run itself, so every hook swallows and logs its own errors.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import create_round, record_message, update_trial_status
from server.market_hive.schemas import SimulationStep

logger = logging.getLogger(__name__)

# step type → mirrored message_type. Types missing here (agent-thinking,
# bb-mention) are UI pulses with no analytical value and are not mirrored.
_STEP_MESSAGE_TYPES: dict[str, str] = {
    "system": "swarm_system",
    "bid": "swarm_bid",
    "abstain": "swarm_abstain",
    "bb-post": "swarm_post",
    "bb-cite": "swarm_cite",
    "bb-vote": "swarm_vote",
    "bb-promote": "swarm_promote",
    "bb-delete": "swarm_delete",
    "amendment": "swarm_amendment",
    "amendment-approved": "swarm_amendment",
    "amendment-rejected": "swarm_amendment",
    "convergence": "swarm_final",
}

# The agent-authored subset — these define the agent→Blackboard edges the
# statistics views draw (imported by server.topology.routes.statistics).
SWARM_BOARD_MESSAGE_TYPES: tuple[str, ...] = (
    "swarm_bid",
    "swarm_abstain",
    "swarm_post",
    "swarm_cite",
    "swarm_vote",
)
SWARM_BOARD_ID = "__market_hive_board__"
SWARM_BOARD_NAME = "Blackboard"


def _message_content(step: SimulationStep) -> str:
    """Pick the most useful text to persist for a step."""
    data = step.data or {}
    if step.type == "bb-post" and isinstance(data.get("content"), str):
        return str(data["content"])
    if step.type == "convergence" and isinstance(data.get("final_answer"), str):
        return str(data["final_answer"])
    if step.type == "bb-promote" and isinstance(data.get("content"), str):
        return str(data["content"])
    return str(step.msg)


class SwarmHistoryRecorder:
    """Consumes a swarm run's steps and mirrors them into the history tables.

    The orchestrator drives it with ``set_phase`` at each stage boundary,
    ``record`` per emitted step, and ``finish`` once the run's terminal status is
    known. It shares the run's database connection: writes interleave with the
    engines' own commits on the same (sequential) task.
    """

    def __init__(self, db: AsyncConnection, trial_id: str) -> None:
        self._db = db
        self.trial_id = trial_id
        self._round_ids: dict[tuple[int, str], int] = {}
        self._round_index = 0
        self._phase = "setup"

    def set_phase(self, round_index: int, phase: str) -> None:
        """Mark the current stage; subsequent steps land in this rounds row."""
        self._round_index = round_index
        self._phase = phase

    async def record(self, step: SimulationStep) -> None:
        """Mirror one step into the messages table (best-effort)."""
        message_type = _STEP_MESSAGE_TYPES.get(step.type)
        if message_type is None:
            return
        try:
            round_id = await self._round_id()
            await record_message(
                self._db,
                round_id,
                step.node_id,
                None,
                message_type,
                _message_content(step),
            )
        except Exception:
            logger.exception("Failed to mirror swarm step into history (type=%s)", step.type)
            await self._safe_rollback()

    async def finish(self, status: str) -> None:
        """Persist the run's terminal status onto its trial row (best-effort)."""
        try:
            await update_trial_status(self._db, self.trial_id, status)
        except Exception:
            logger.exception("Failed to mark swarm trial %s as %s", self.trial_id, status)
            await self._safe_rollback()

    async def _round_id(self) -> int:
        key = (self._round_index, self._phase)
        round_id = self._round_ids.get(key)
        if round_id is None:
            round_id = await create_round(self._db, self.trial_id, self._round_index, self._phase)
            self._round_ids[key] = round_id
        return round_id

    async def _safe_rollback(self) -> None:
        """Clear a possibly-aborted transaction so the run itself can continue."""
        try:
            if self._db.in_transaction():
                await self._db.rollback()
        except Exception:
            logger.exception("Rollback after failed history mirror also failed")
