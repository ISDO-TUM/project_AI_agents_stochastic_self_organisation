"""Four benchmark mode adapters behind one ``ModeAdapter`` protocol.

Every adapter accepts the same ``BenchmarkTask`` and returns a
``BenchmarkResult`` with the same shape, so the judge and report never need to
know which mode produced an answer. ``agent_runner`` injection keeps every
adapter offline-testable with a scripted/fake runner; ``fail_agent`` implements
the robustness ablation by making that named agent's turns raise.

* **B-01 single-agent**: one strong model call with every source document
  concatenated into the prompt — the "just ask GPT-4o with everything" baseline.
* **B-02 topology**: the existing broadcast topology engine. Offline
  (``agent_runner`` given) drives one simplified broadcast round directly
  (``run_topology`` itself has no injectable runner seam); online, it drives
  the real engine and reads back the last round's messages as the answer.
* **B-03 minimal supervisor**: an intentionally honest ~60-line planner
  (one JSON-planning call, one call per subtask, one aggregation call) — no
  retries, no bidding, no deliberate crippling either. A subtask routed to a
  failed agent is recorded as lost; aggregation proceeds without it.
* **B-04 ECSAS swarm**: drives ``run_swarm`` end-to-end.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal, Protocol

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.benchmarks.tasks import BenchmarkTask
from server.db import create_trial
from server.llm import call_agent
from server.market_hive.orchestrator import AgentRunner, run_swarm
from server.market_hive.schemas import SwarmRunConfig
from server.topology import run_topology


class BenchmarkResult(BaseModel):
    mode: Literal["b01", "b02", "b03", "b04"]
    task_id: str
    trial: int
    answer: str
    tokens: int
    wall_seconds: float
    metadata: dict[str, Any] = {}


class ModeAdapter(Protocol):
    async def run(
        self,
        task: BenchmarkTask,
        db: AsyncConnection,
        *,
        agent_runner: AgentRunner | None = None,
        fail_agent: str | None = None,
    ) -> BenchmarkResult: ...


async def _seed_task(db: AsyncConnection, task: BenchmarkTask) -> list[str]:
    """Insert the task's agents + source files (demo-canvas shape) into the
    DB — every source attached to every agent, so any mode's ``files`` tool
    (or direct concatenation) can reach the full document set. Returns the
    agent ids in the task's original order."""
    agent_ids: list[str] = []
    for a in task.agents:
        await db.execute(
            text(
                "INSERT INTO agents "
                "(id, name, description, system_prompt, provider, model, tools, connections) "
                "VALUES (:id, :name, :desc, :sp, :provider, :model, :tools, :connections)"
            ),
            {
                "id": a["id"],
                "name": a["name"],
                "desc": a["description"],
                "sp": a["systemPrompt"],
                "provider": a["provider"],
                "model": a["model"],
                "tools": json.dumps(a.get("tools", [])),
                "connections": json.dumps(a.get("connections", [])),
            },
        )
        agent_ids.append(a["id"])
    for s in task.sources:
        await db.execute(
            text("INSERT INTO knowledge_files (id, name, content) VALUES (:id, :name, :content)"),
            {"id": s["id"], "name": s["name"], "content": s["content"]},
        )
        for aid in agent_ids:
            await db.execute(
                text("INSERT INTO agent_files (agent_id, file_id) VALUES (:a, :f)"),
                {"a": aid, "f": s["id"]},
            )
    await db.commit()
    return agent_ids


def _sources_text(task: BenchmarkTask) -> str:
    return "\n\n".join(f"[{s['name']}]\n{s['content']}" for s in task.sources)


async def _call(
    agent_runner: AgentRunner | None,
    *,
    agent_id: str,
    agent_name: str,
    user_prompt: str,
    system_suffix: str,
) -> str:
    """One LLM turn, through the injected runner when testing or a real
    ``call_agent`` call otherwise. No tools — every mode concatenates source
    text directly into the prompt rather than offering file-reading tools,
    keeping all four modes' inputs identical (PRD "same inputs" constraint)."""
    if agent_runner is not None:
        response, _ = await agent_runner(
            {"id": agent_id, "name": agent_name, "provider": "openai", "model": "gpt-4o"},
            user_prompt=user_prompt,
            system_suffix=system_suffix,
            tool_names=[],
            tool_context={},
        )
        return response
    response, _ = await call_agent(
        user_prompt, provider="openai", model="gpt-4o", system_prompt=system_suffix
    )
    return response


class B01SingleAgent:
    """One strong model, all context in the prompt — no multi-agent structure."""

    async def run(
        self,
        task: BenchmarkTask,
        db: AsyncConnection,
        *,
        agent_runner: AgentRunner | None = None,
        fail_agent: str | None = None,
    ) -> BenchmarkResult:
        start = time.monotonic()
        prompt = (
            f"{task.prompt}\n\nSOURCE DOCUMENTS:\n{_sources_text(task)}\n\n"
            "Provide a thorough, well-cited analysis covering every material risk."
        )
        answer = await _call(
            agent_runner,
            agent_id="b01-single-agent",
            agent_name="Single Agent",
            user_prompt=prompt,
            system_suffix="You are a thorough generalist analyst reviewing a document end to end.",
        )
        return BenchmarkResult(
            mode="b01",
            task_id=task.id,
            trial=0,
            answer=answer,
            tokens=0,
            wall_seconds=time.monotonic() - start,
        )


async def _last_round_answer(db: AsyncConnection, trial_id: str) -> str:
    """Concatenate every message from a trial's final round as its answer."""
    round_id = (
        await db.execute(
            text(
                "SELECT id FROM rounds WHERE trial_id = :t ORDER BY round_index DESC LIMIT 1"
            ),
            {"t": trial_id},
        )
    ).scalar()
    if round_id is None:
        return ""
    rows = (
        await db.execute(
            text(
                "SELECT from_agent_name, message FROM messages "
                "WHERE round_id = :r AND message IS NOT NULL ORDER BY id"
            ),
            {"r": round_id},
        )
    ).fetchall()
    return "\n\n".join(f"{name}: {msg}" for name, msg in rows if msg)


class B02Topology:
    """The existing broadcast topology engine."""

    async def run(
        self,
        task: BenchmarkTask,
        db: AsyncConnection,
        *,
        agent_runner: AgentRunner | None = None,
        fail_agent: str | None = None,
    ) -> BenchmarkResult:
        start = time.monotonic()
        agent_ids = await _seed_task(db, task)
        sources_block = _sources_text(task)

        if agent_runner is not None:
            # run_topology has no injectable runner seam, so the offline path
            # drives one simplified broadcast round directly — every agent
            # answers the prompt once, independently, which is topology's
            # essential shape (no consensus operator in the default mode).
            responses = []
            for aid in agent_ids:
                row = (
                    await db.execute(
                        text("SELECT name FROM agents WHERE id = :id"), {"id": aid}
                    )
                ).mappings().fetchone()
                name = row["name"]
                if fail_agent is not None and name == fail_agent:
                    responses.append(f"{name}: [failed to respond]")
                    continue
                prompt = f"{task.prompt}\n\nSOURCE DOCUMENTS:\n{sources_block}"
                text_ = await _call(
                    agent_runner,
                    agent_id=aid,
                    agent_name=name,
                    user_prompt=prompt,
                    system_suffix="",
                )
                responses.append(f"{name}: {text_}")
            answer = "\n\n".join(responses)
            trial_id = "offline"
        else:
            trial_id = await create_trial(
                db, task.prompt, f"benchmark {task.id}", "broadcast_no_consensus"
            )
            await run_topology(
                task.prompt, db, rounds=2, mode="broadcast_no_consensus", trial_id=trial_id
            )
            answer = await _last_round_answer(db, trial_id)

        return BenchmarkResult(
            mode="b02",
            task_id=task.id,
            trial=0,
            answer=answer,
            tokens=0,
            wall_seconds=time.monotonic() - start,
            metadata={"trial_id": trial_id},
        )


_PLANNER_PROMPT = (
    "You are a project planner. Given a task and a roster of specialist agents, "
    'break the task into subtasks, one per relevant agent. Respond with ONLY a '
    'JSON array of objects: [{"subtask": "...", "agent_name": "..."}, ...]. '
    "Use only agent names from the roster, and cover every agent whose expertise "
    "is relevant."
)


class B03MinimalSupervisor:
    """Honest-minimal supervisor: one plan call, one call per subtask, one
    aggregation call. No retries, no bidding — and no deliberate crippling."""

    async def run(
        self,
        task: BenchmarkTask,
        db: AsyncConnection,
        *,
        agent_runner: AgentRunner | None = None,
        fail_agent: str | None = None,
    ) -> BenchmarkResult:
        start = time.monotonic()
        roster = ", ".join(a["name"] for a in task.agents)
        agents_by_name = {a["name"]: a for a in task.agents}
        sources_block = _sources_text(task)

        plan_raw = await _call(
            agent_runner,
            agent_id="b03-planner",
            agent_name="planner",
            user_prompt=f"TASK: {task.prompt}\n\nROSTER: {roster}",
            system_suffix=_PLANNER_PROMPT,
        )
        try:
            subtasks = json.loads(plan_raw)
            if not isinstance(subtasks, list):
                raise ValueError("planner did not return a list")
        except (json.JSONDecodeError, ValueError):
            # Degenerate but honest fallback: one subtask per agent, unchanged
            # from the task prompt — never crash the suite on a bad plan.
            subtasks = [{"subtask": task.prompt, "agent_name": a["name"]} for a in task.agents]

        lost_subtasks: list[str] = []
        completed: list[str] = []
        for item in subtasks:
            agent_name = item.get("agent_name") if isinstance(item, dict) else None
            agent = agents_by_name.get(agent_name) if agent_name else None
            if agent is None:
                continue
            subtask_text = item.get("subtask", "") if isinstance(item, dict) else ""
            if fail_agent is not None and agent_name == fail_agent:
                lost_subtasks.append(subtask_text)
                continue
            prompt = f"SUBTASK: {subtask_text}\n\nSOURCE DOCUMENTS:\n{sources_block}"
            result = await _call(
                agent_runner,
                agent_id=str(agent.get("id", agent_name)),
                agent_name=agent_name,
                user_prompt=prompt,
                system_suffix=agent["systemPrompt"],
            )
            completed.append(f"{agent_name}: {result}")

        aggregation_prompt = f"TASK: {task.prompt}\n\nSUBTASK RESULTS:\n" + "\n\n".join(completed)
        if lost_subtasks:
            aggregation_prompt += (
                f"\n\nNOTE: these subtasks could not be completed and are NOT reflected "
                f"above: {lost_subtasks}"
            )
        answer = await _call(
            agent_runner,
            agent_id="b03-aggregator",
            agent_name="aggregator",
            user_prompt=aggregation_prompt,
            system_suffix="Synthesize the subtask results into one direct, well-cited answer.",
        )

        return BenchmarkResult(
            mode="b03",
            task_id=task.id,
            trial=0,
            answer=answer,
            tokens=0,
            wall_seconds=time.monotonic() - start,
            metadata={"plan": subtasks, "lost_subtasks": lost_subtasks},
        )


class B04Swarm:
    """Drives the real ECSAS ``run_swarm`` end-to-end."""

    async def run(
        self,
        task: BenchmarkTask,
        db: AsyncConnection,
        *,
        agent_runner: AgentRunner | None = None,
        fail_agent: str | None = None,
    ) -> BenchmarkResult:
        start = time.monotonic()
        await _seed_task(db, task)
        config = SwarmRunConfig(prompt=task.prompt, max_rounds=3)

        runner = agent_runner
        if fail_agent is not None and runner is not None:
            inner = runner

            async def _ablated(agent: dict[str, Any], **kw: Any) -> tuple[str, list[Any]]:
                if agent.get("name") == fail_agent and "submit_bid" not in kw["tool_names"]:
                    raise RuntimeError(f"{fail_agent} is down")
                return await inner(agent, **kw)

            runner = _ablated

        run_id: str | None = None
        final_answer: str | None = None
        async for step in run_swarm(config, db, agent_runner=runner):
            if step.data and isinstance(step.data.get("run_id"), str):
                run_id = step.data["run_id"]
            if step.type == "convergence":
                final_answer = step.data.get("final_answer") if step.data else None

        return BenchmarkResult(
            mode="b04",
            task_id=task.id,
            trial=0,
            answer=final_answer or "",
            tokens=0,
            wall_seconds=time.monotonic() - start,
            metadata={"run_id": run_id},
        )
