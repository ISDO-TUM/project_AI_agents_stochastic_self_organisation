"""Request-scoped data ownership (lightweight, header-based).

Authentication is out of scope, but data must not leak between users sharing a
deployment. Each browser generates a random owner id once and sends it as the
``X-Owner-Id`` header on every request; the API scopes all user data — agents,
knowledge files, and simulation trials/history — to that id so one browser never
sees another's data.

This is **isolation, not authentication**: the id is chosen by the client, so it
is not a security boundary against a determined attacker. It is sufficient here
because collaboration/sharing is explicitly not a feature and the ids are
unguessable random UUIDs that never appear in any response.

A request without the header (or with a blank one) falls into the shared ``NULL``
bucket. The browser app always sends the header; the ``NULL`` bucket is therefore
only ever used by the test suite and non-browser tooling, where a single shared
scope is fine.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Header

#: HTTP header carrying the client-generated owner id.
OWNER_HEADER = "X-Owner-Id"


async def current_owner(
    x_owner_id: Annotated[str | None, Header()] = None,
) -> str | None:
    """FastAPI dependency: the owner id for this request, or ``None``.

    A blank or absent header maps to ``None`` (the shared bucket).
    """
    if x_owner_id is None:
        return None
    owner = x_owner_id.strip()
    return owner or None


#: Inject the resolved owner id straight into a route signature.
OwnerDep = Annotated[str | None, Depends(current_owner)]


def owner_match(column: Any, owner: str | None) -> Any:
    """Build a ``WHERE`` clause scoping ``column`` to ``owner``.

    ``NULL`` owners are matched with ``IS NULL`` rather than ``= NULL`` so the
    shared bucket behaves consistently across dialects.
    """
    return column.is_(None) if owner is None else column == owner
