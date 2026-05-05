"""Topology — the contract Pair B's `build_topology(pool, task)` will produce."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable


@runtime_checkable
class Topology(Protocol):
    """Graph view used by the consensus layer."""

    def nodes(self) -> list[str]: ...
    def neighbors(self, agent_id: str) -> list[str]: ...
    def edge_weight(self, src: str, dst: str) -> float: ...


class CompleteGraphTopology:
    """Fully-connected fallback used until Pair B's builder is wired in."""

    def __init__(self, ids: Iterable[str]) -> None:
        self._ids: list[str] = list(ids)
        self._set: set[str] = set(self._ids)

    def nodes(self) -> list[str]:
        return list(self._ids)

    def neighbors(self, agent_id: str) -> list[str]:
        if agent_id not in self._set:
            return []
        return [i for i in self._ids if i != agent_id]

    def edge_weight(self, src: str, dst: str) -> float:
        if src in self._set and dst in self._set and src != dst:
            return 1.0
        return 0.0
