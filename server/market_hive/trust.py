"""Trust registry — cross-run ``agent_trust`` update at run end (PRD §6.7).

Deferred for now. ``NoopTrustRegistry`` lets the orchestrator call
``trust.update(...)`` unconditionally at run end without special-casing. The real
registry (winner gain proportional to confirmed-citation share, flat observer
loss, clamped to ``[0, 1]``) will replace it behind the same ``update`` signature,
so the orchestrator does not change when it lands.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection


class NoopTrustRegistry:
    """Placeholder: records nothing. Swap for the real registry later."""

    async def update(
        self, *, run_id: str, takers: list[str], observers: list[str], db: AsyncConnection
    ) -> None:
        return None
