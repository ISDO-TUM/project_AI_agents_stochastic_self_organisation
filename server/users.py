"""Anonymous per-browser data ownership (the app has no authentication).

The client generates a UUID once, keeps it in localStorage, and sends it as the
``X-User-Id`` header on every request. List endpoints (agents, files, trials,
messages, experiments) only return the caller's rows, writes stamp the id, and
bulk deletes only touch the caller's data. This is privacy shading, not auth —
three deliberate softenings keep it simple and backwards-compatible:

- rows with ``user_id IS NULL`` (written before scoping existed, or by clients
  that send no header) stay visible to everyone,
- requests *without* the header see everything, so curl sessions, tests and
  pre-scoping deployments keep working unchanged, and
- detail endpoints keyed by unguessable UUIDs are not re-checked: knowing an id
  is treated as a capability, exactly like an unlisted link.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Header

_MAX_USER_ID_LEN = 64


async def get_user_id(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> str | None:
    """FastAPI dependency: the caller's anonymous user id, if any."""
    if x_user_id is None:
        return None
    cleaned = x_user_id.strip()[:_MAX_USER_ID_LEN]
    return cleaned or None


UserIdDep = Annotated[str | None, Depends(get_user_id)]


def owned_or_shared(column: Any, user_id: str | None) -> Any | None:
    """WHERE clause limiting *column* to the caller's rows plus shared (NULL) rows.

    Returns ``None`` when the request carries no user id — meaning "no filter".
    Use with :func:`scoped` or guard the ``.where()`` call yourself.
    """
    if user_id is None:
        return None
    return (column == user_id) | (column.is_(None))


def scoped(stmt: Any, column: Any, user_id: str | None) -> Any:
    """Apply :func:`owned_or_shared` to a SELECT/DELETE statement when scoping is on."""
    clause = owned_or_shared(column, user_id)
    return stmt if clause is None else stmt.where(clause)
