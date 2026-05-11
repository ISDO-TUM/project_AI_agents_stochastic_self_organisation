"""Drive the needle-in-a-haystack benchmark against the running API.

Usage (from the repo root, with `pnpm dev` already running):

    uv run --project api python -m api.benchmarks.run             # 1 trial, 3 agents
    uv run --project api python -m api.benchmarks.run --trials 5  # 5 voting trials
    uv run --project api python -m api.benchmarks.run --agents 5  # 5 benchmark agents

The benchmark is **self-contained** — it provisions its own agents, runs the
trials, and tears them down at the end. Whatever you have on the canvas
(e.g. an imported demo) is left alone.

For each trial:

1. The benchmark generator builds one chunk per agent — a strict majority
   contains the correct needle, the rest contain a plausible-but-wrong one.
2. Each chunk is uploaded as a knowledge file and attached to its temporary
   benchmark agent, so the agent reads its context with the ``files`` tool
   exactly the way the demo agents do.
3. The simulation runs in plurality-voting mode. The leading vote at round 0
   already matches the majority answer, so consensus typically converges by
   round 2.
4. The uploaded files (and only those files) are deleted at the end of the
   trial so the next trial starts clean.

Once all trials are done, the benchmark agents themselves are deleted.

The weighted-pool consensus mode still exists in the simulation engine; this
runner just doesn't exercise it for now.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO, cast

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
MODE = "voting"

# Sentinel used when --log is given without a value: auto-generate a path.
_LOG_AUTO = "<auto>"


class _Tee:
    """Mirror writes to stdout and (optionally) a log file."""

    def __init__(self, log_file: TextIO | None) -> None:
        self._log_file = log_file

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("file", sys.stdout)
        print(*args, **kwargs)
        if self._log_file is not None:
            kwargs["file"] = self._log_file
            print(*args, **kwargs)
            self._log_file.flush()


def _resolve_log_path(value: str | None) -> Path | None:
    if value is None:
        return None
    if value == _LOG_AUTO:
        return Path.cwd() / f"benchmark-{datetime.now():%Y%m%d-%H%M}.log"
    return Path(value).expanduser()


# System prompt for benchmark agents — bare-name answer, fall back to "unknown".
_BENCH_SYSTEM_PROMPT = (
    "You answer the user's question using ONLY the information in your "
    "attached files. Read every file with the `files` tool before answering. "
    "Reply with the bare answer (a single name, no full sentence, no "
    "explanation). If the answer is not in your files, reply with the "
    'literal string "unknown".'
)
_BENCH_PROVIDER = "openai"
_BENCH_MODEL = "gpt-4o-mini"


def _create_bench_agents(client: httpx.Client, count: int) -> list[dict[str, Any]]:
    """Create ``count`` temporary benchmark agents and return them."""
    created: list[dict[str, Any]] = []
    for i in range(1, count + 1):
        body = {
            "name": f"Bench Agent {i}",
            "description": "Temporary agent created by the benchmark runner.",
            "system_prompt": _BENCH_SYSTEM_PROMPT,
            "provider": _BENCH_PROVIDER,
            "model": _BENCH_MODEL,
            "tools": ["files"],
            "connections": [],
        }
        r = client.post("/api/agents/", json=body)
        r.raise_for_status()
        created.append(r.json())
    return created


def _delete_bench_agents(client: httpx.Client, agents: list[dict[str, Any]]) -> None:
    """Best-effort teardown of benchmark agents."""
    for agent in agents:
        try:
            client.delete(f"/api/agents/{agent['id']}")
        except httpx.HTTPError as exc:
            print(
                f"Warning: failed to delete benchmark agent {agent.get('id')}: {exc}",
                file=sys.stderr,
            )


def _create_benchmark(client: httpx.Client, num_agents: int, sentences: int) -> dict[str, Any]:
    r = client.post(
        "/benchmark/needlehaystack/create",
        json={
            "num_agents": num_agents,
            "sentences_per_agent": sentences,
            "include_answer": True,
        },
    )
    r.raise_for_status()
    return cast(dict[str, Any], r.json())


def _run_simulation(
    client: httpx.Client,
    prompt: str,
    rounds: int,
) -> dict[str, Any]:
    r = client.post(
        "/api/simulation/run",
        json={
            "prompt": prompt,
            "rounds": rounds,
            "mode": MODE,
        },
        timeout=600.0,
    )
    r.raise_for_status()
    return cast(dict[str, Any], r.json())


def _safe_filename(name: str) -> str:
    """Make a knowledge-file name safe and recognisable for the benchmark."""
    cleaned = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in name)
    return cleaned.strip().replace(" ", "_") or "agent"


def _attach_files(
    client: httpx.Client,
    agents: list[dict[str, Any]],
    chunks: dict[str, str],
    file_label: str,
) -> list[tuple[str, str]]:
    """Create a knowledge file per agent, attach it, ensure the files tool is on.

    Returns the list of (agent_id, file_id) pairs we created so the caller
    can clean them up.
    """
    created: list[tuple[str, str]] = []
    for i, agent in enumerate(agents):
        chunk = chunks[f"agent_{i + 1}"]
        file_name = f"{_safe_filename(agent['name'])}_{file_label}.txt"
        r = client.post("/api/files/", json={"name": file_name, "content": chunk})
        r.raise_for_status()
        file_id = r.json()["id"]

        attach = client.post(f"/api/agents/{agent['id']}/files/{file_id}")
        attach.raise_for_status()

        if "files" not in (agent.get("tools") or []):
            tools = [*(agent.get("tools") or []), "files"]
            patch = client.patch(f"/api/agents/{agent['id']}", json={"tools": tools})
            patch.raise_for_status()
            agent["tools"] = tools

        created.append((agent["id"], file_id))
    return created


def _detach_files(client: httpx.Client, created: list[tuple[str, str]]) -> None:
    """Detach + delete the knowledge files we created for this trial."""
    for agent_id, file_id in created:
        try:
            client.delete(f"/api/agents/{agent_id}/files/{file_id}")
        except httpx.HTTPError:
            pass
        try:
            client.delete(f"/api/files/{file_id}")
        except httpx.HTTPError:
            pass


def _evaluate(
    client: httpx.Client,
    benchmark_id: str,
    generated_answer: str,
) -> dict[str, Any]:
    r = client.post(
        "/benchmark/needlehaystack/evaluate",
        json={
            "benchmark_id": benchmark_id,
            "generated_answer": generated_answer or "",
        },
    )
    r.raise_for_status()
    return cast(dict[str, Any], r.json())


def _ok(b: bool | None) -> str:
    if b is True:
        return "✓"
    if b is False:
        return "✗"
    return "—"


def _run_trial(
    client: httpx.Client,
    agents: list[dict[str, Any]],
    sentences: int,
    rounds: int,
    trial_idx: int,
    out: _Tee,
) -> dict[str, Any]:
    """Run one majority-voting benchmark trial."""
    benchmark = _create_benchmark(client, num_agents=len(agents), sentences=sentences)
    benchmark_id = benchmark["benchmark_id"]
    question = benchmark["question"]
    needle_chunks = benchmark["chunks"]
    correct_count = benchmark.get("correct_agent_count")

    out(f"\n── Trial {trial_idx} ───────────────────────────────────────────")
    out(f"Question      : {question}")
    out(f"Expected      : {benchmark['answer']}  (held by {correct_count}/{len(agents)} agents)")

    created = _attach_files(client, agents, needle_chunks, file_label=f"trial{trial_idx}")
    try:
        t0 = time.perf_counter()
        sim = _run_simulation(client, question, rounds)
        elapsed = time.perf_counter() - t0
    finally:
        _detach_files(client, created)

    evaluated = _evaluate(client, benchmark_id, sim.get("consensus") or "")
    row = {
        "trial": trial_idx,
        "answer_correct": evaluated["answer_correct"],
        "converged": sim["converged"],
        "rounds_used": sim["rounds_used"],
        "elapsed_s": elapsed,
        "consensus": sim.get("consensus") or "",
    }
    out(
        f"  voting     answer {_ok(evaluated['answer_correct'])}  "
        f"converged {_ok(sim['converged'])}  "
        f"rounds={sim['rounds_used']}  "
        f"{elapsed:5.1f}s  "
        f"→ {(sim.get('consensus') or '').strip()[:70]}"
    )
    return row


def _summarise(rows: list[dict[str, Any]], out: _Tee) -> None:
    out("\n── Summary ──────────────────────────────────────────────────")
    out(f"{'metric':14s}  {'value':>10s}")
    if not rows:
        return
    ans_acc = sum(1 for r in rows if r["answer_correct"]) / len(rows)
    avg_rounds = statistics.mean(r["rounds_used"] for r in rows)
    avg_time = statistics.mean(r["elapsed_s"] for r in rows)
    converged_rate = sum(1 for r in rows if r["converged"]) / len(rows)
    out(f"{'answer acc':14s}  {ans_acc * 100:>9.1f}%")
    out(f"{'converged':14s}  {converged_rate * 100:>9.1f}%")
    out(f"{'avg rounds':14s}  {avg_rounds:>10.2f}")
    out(f"{'avg time':14s}  {avg_time:>9.1f}s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the majority-vote needle-in-a-haystack benchmark."
    )
    parser.add_argument(
        "--agents",
        type=int,
        default=3,
        help="Number of temporary benchmark agents to create (>= 3 for a strict majority).",
    )
    parser.add_argument("--trials", type=int, default=1, help="Number of benchmarks to run.")
    parser.add_argument(
        "--sentences", type=int, default=6, help="Distractor sentences per agent chunk."
    )
    parser.add_argument("--rounds", type=int, default=2, help="Discussion rounds per simulation.")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--log",
        nargs="?",
        const=_LOG_AUTO,
        default=None,
        metavar="PATH",
        help=(
            "Mirror benchmark output to a log file. With no value, writes to "
            "./benchmark-YYYYMMDD-HHMM.log. Pass an explicit path to override."
        ),
    )
    args = parser.parse_args(argv)

    if args.agents < 3:
        print(
            f"--agents must be >= 3 (got {args.agents}). Majority voting requires "
            "a strict majority.",
            file=sys.stderr,
        )
        return 2

    log_path = _resolve_log_path(args.log)
    log_file = log_path.open("w", encoding="utf-8") if log_path else None
    out = _Tee(log_file)
    if log_path is not None:
        out(f"# Logging to {log_path}")

    try:
        with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
            out(
                f"Provisioning {args.agents} benchmark agents (model={_BENCH_MODEL}). "
                f"Mode: {MODE}. Trials: {args.trials}."
            )
            agents = _create_bench_agents(client, args.agents)

            all_rows: list[dict[str, Any]] = []
            try:
                for i in range(1, args.trials + 1):
                    try:
                        all_rows.append(
                            _run_trial(
                                client,
                                agents,
                                sentences=args.sentences,
                                rounds=args.rounds,
                                trial_idx=i,
                                out=out,
                            )
                        )
                    except httpx.HTTPError as exc:
                        print(f"Trial {i} failed: {exc}", file=sys.stderr)
            finally:
                _delete_bench_agents(client, agents)
                out(f"\nTore down {len(agents)} benchmark agents.")

            if all_rows and args.trials > 1:
                _summarise(all_rows, out)
    finally:
        if log_file is not None:
            log_file.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
