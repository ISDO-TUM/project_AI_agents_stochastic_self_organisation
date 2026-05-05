"""Agent pool — the contract Pair A produces and the consensus layer reads."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AgentSpec:
    """One agent. `profile` is the role description Pair A's MorphAgent will evolve."""

    id: str
    profile: str
    llm_call: Callable[[str], str]
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Pool(Protocol):
    """Read-only view of the agent pool used by topology and consensus layers."""

    def __iter__(self) -> Iterator[AgentSpec]: ...
    def __len__(self) -> int: ...
    def __contains__(self, agent_id: object) -> bool: ...
    def get(self, agent_id: str) -> AgentSpec: ...
    def ids(self) -> list[str]: ...


class InMemoryPool:
    """List-backed pool. Pair A may replace this with a DB-backed implementation."""

    def __init__(self, agents: Iterable[AgentSpec]) -> None:
        self._agents: dict[str, AgentSpec] = {a.id: a for a in agents}

    def __iter__(self) -> Iterator[AgentSpec]:
        return iter(self._agents.values())

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, agent_id: object) -> bool:
        return isinstance(agent_id, str) and agent_id in self._agents

    def get(self, agent_id: str) -> AgentSpec:
        return self._agents[agent_id]

    def ids(self) -> list[str]:
        return list(self._agents.keys())
