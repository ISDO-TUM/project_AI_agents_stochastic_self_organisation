"""FanOutQA evidence-provided benchmark runner against the ECSAS swarm engine.

Evaluates the blackboard consensus algorithm on FanOutQA questions by splitting
each question's pre-fetched Wikipedia evidence pages across n agents, running the
swarm, and scoring the final answer with ROUGE and accuracy metrics.

Usage (from repo root, with the server running):

    uv run python -m server.topology.benchmarks.fanoutqa_run
    uv run python -m server.topology.benchmarks.fanoutqa_run --questions 10 --rounds 5
    uv run python -m server.topology.benchmarks.fanoutqa_run --questions 3 --log
    uv run python -m server.topology.benchmarks.fanoutqa_run --start 10 --questions 11
    uv run python -m server.topology.benchmarks.fanoutqa_run \
        --start 10 --questions 11 --results-file results.json

Agent count is derived per question:
    n_agents = clamp(ceil(total_pages / max_pages_per_agent), 2, 8)

This ensures no agent holds more than max_pages_per_agent Wikipedia pages while
guaranteeing at least 2 agents for a meaningful consensus run. The swarm auction
filters takers naturally — not all agents are guaranteed to post.

Agents and files are created fresh per question and torn down afterwards, so the
canvas is left clean regardless of success or failure.

Task indices are always stable (1-based, matching the FanOutQA dev-set order).
--results-file writes per-task scores to JSON and re-computes the summary on each
run; re-running overlapping ranges merges by task index (later run wins).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

import httpx
from rouge_score.rouge_scorer import RougeScorer as _RougeScorer

DEFAULT_BASE_URL = "http://localhost:8000"
_MAX_PAGES_PER_AGENT = 5
_MIN_AGENTS = 4
_MAX_AGENTS = 8
_MAX_CONTENT = 490_000  # just under the 500 KB schema limit

_LOG_AUTO = "<auto>"
_BENCH_RESULT_DIR = Path("Benchmark-result")

_BENCH_SYSTEM_PROMPT = (
    "You are a research assistant working in a team to answer complex questions. "
    "You have access to a set of Wikipedia articles as your knowledge base. "
    "Read all your files with the `files` tool before contributing to the discussion. "
    "Post your findings and partial answers to the blackboard, and cite other agents' "
    "entries when they support your reasoning. "
    "Your goal is to help the team reach a well-supported consensus answer."
    "DO NOT ANSWER USING WORLD KNOWLEDGE."
    "ALL INFORMATION YOU CONTRIBUTE MUST BE CITED BY A SOURCE."
)
_BENCH_PROVIDER = "anthropic"
_BENCH_MODEL = "claude-sonnet-4-6"


# ── Output ────────────────────────────────────────────────────────────────────


class _Tee:
    """Mirror writes to stdout and optionally a log file."""

    def __init__(self, log_file: TextIO | None) -> None:
        self._log_file = log_file

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("file", sys.stdout)
        print(*args, **kwargs)
        if self._log_file is not None:
            kwargs["file"] = self._log_file
            print(*args, **kwargs)
            self._log_file.flush()


def _resolve_output_path(value: str) -> Path:
    """Resolve a user-supplied file path.

    A bare filename (no directory component) is placed inside
    ``_BENCH_RESULT_DIR``; an explicit relative or absolute path is used as-is.
    The parent directory is created if it does not exist.
    """
    p = Path(value).expanduser()
    if p.parent == Path("."):
        p = _BENCH_RESULT_DIR / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_log_path(value: str | None) -> Path | None:
    if value is None:
        return None
    if value == _LOG_AUTO:
        return _resolve_output_path(f"fanoutqa-benchmark-{datetime.now():%Y%m%d-%H%M}.log")
    return _resolve_output_path(value)


# ── Agent + file lifecycle ────────────────────────────────────────────────────


def _create_bench_agents(client: httpx.Client, count: int) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    for i in range(1, count + 1):
        body = {
            "name": f"FanOutQA Agent {i}",
            "description": "Temporary agent created by the FanOutQA benchmark runner.",
            "system_prompt": _BENCH_SYSTEM_PROMPT,
            "provider": _BENCH_PROVIDER,
            "model": _BENCH_MODEL,
            "tools": ["files"],
            "connections": [],
        }
        r = client.post("/api/agents", json=body)
        r.raise_for_status()
        created.append(r.json())
    return created


def _delete_bench_agents(client: httpx.Client, agents: list[dict[str, Any]]) -> None:
    for agent in agents:
        try:
            client.delete(f"/api/agents/{agent['id']}")
        except httpx.HTTPError as exc:
            print(
                f"Warning: failed to delete benchmark agent {agent.get('id')}: {exc}",
                file=sys.stderr,
            )


def _safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in name)
    return cleaned.strip().replace(" ", "_") or "agent"


def _attach_files(
    client: httpx.Client,
    agents: list[dict[str, Any]],
    chunks: dict[str, str],
    file_label: str,
) -> list[tuple[str, str]]:
    """Upload one knowledge file per agent and attach it. Returns [(agent_id, file_id)]."""
    created: list[tuple[str, str]] = []
    for i, agent in enumerate(agents):
        content = chunks[f"agent_{i + 1}"]
        if len(content) > _MAX_CONTENT:
            print(
                f"Warning: truncating file for agent {i + 1} "
                f"({len(content)} → {_MAX_CONTENT} chars)",
                file=sys.stderr,
            )
            content = content[:_MAX_CONTENT]

        file_name = f"{_safe_filename(agent['name'])}_{file_label}.txt"
        r = client.post(
            "/api/files", json={"name": file_name, "content": content, "skip_injection_check": True}
        )
        if not r.is_success:
            print(f"File upload failed ({r.status_code}): {r.text}", file=sys.stderr)
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
    for agent_id, file_id in created:
        try:
            client.delete(f"/api/agents/{agent_id}/files/{file_id}")
        except httpx.HTTPError as exc:
            print(
                f"Warning: failed to detach file {file_id} from agent {agent_id}: {exc}",
                file=sys.stderr,
            )
        try:
            client.delete(f"/api/files/{file_id}")
        except httpx.HTTPError as exc:
            print(
                f"Warning: failed to delete file {file_id}: {exc}",
                file=sys.stderr,
            )


# ── Evidence splitting ────────────────────────────────────────────────────────


def _compute_n_agents(
    n_pages: int,
    max_pages_per_agent: int,
) -> int:
    """Derive agent count: clamp(ceil(n_pages / max_pages_per_agent), 2, 8)."""
    if n_pages == 0:
        return _MIN_AGENTS
    return max(_MIN_AGENTS, min(_MAX_AGENTS, math.ceil(n_pages / max_pages_per_agent)))


def _split_pages(
    pages: list[str],
    n_agents: int,
) -> dict[str, str]:
    """Round-robin distribute pages across agents, joining multiple pages per agent."""
    buckets: dict[str, list[str]] = {f"agent_{k + 1}": [] for k in range(n_agents)}
    for i, page_text in enumerate(pages):
        buckets[f"agent_{i % n_agents + 1}"].append(page_text)
    return {key: "\n\n---\n\n".join(texts) for key, texts in buckets.items()}


# ── Simulation (SSE swarm) ────────────────────────────────────────────────────


def _run_swarm(
    client: httpx.Client,
    question: str,
    rounds: int,
    n_agents: int,
    out: _Tee | None = None,
) -> dict[str, Any]:
    """POST to the swarm engine and stream SSE until the convergence event."""
    final_answer: str | None = None
    termination_round: int | None = None
    termination_reason: str | None = None

    with client.stream(
        "POST",
        "/api/simulation/run",
        json={
            "engine": "swarm",
            "prompt": question,
            "rounds": rounds,
            "swarm_min_takers": n_agents,
            "swarm_max_takers": n_agents,
            "swarm_invite_floor": 0.0,
            "swarm_skip_auction": True,
        },
        timeout=600.0,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            step = json.loads(line[6:])
            print(f"  [swarm] {step.get('type'):20s} {step.get('msg', '')[:80]}", file=sys.stderr)
            if step.get("type") == "bb-post" and out is not None:
                data = step.get("data") or {}
                author = data.get("author_name", "?")
                entry_type = data.get("entry_type", "")
                content = (data.get("content") or "").strip()
                rnd = data.get("round", "?")
                out(f"    [{rnd}] {author} ({entry_type}): {content}")
            elif step.get("type") == "convergence":
                data = step.get("data") or {}
                final_answer = data.get("final_answer")
                termination_round = data.get("termination_round")
                termination_reason = data.get("termination_reason")
                break

    return {
        "final_answer": final_answer or "",
        "termination_round": termination_round,
        "termination_reason": termination_reason,
    }


# ── FanOutQA data loading ─────────────────────────────────────────────────────


def _load_questions_and_evidence(
    start: int,
    end: int,
) -> list[tuple[Any, list[str]]]:
    """Load FanOutQA dev questions and fetch their evidence pages.

    Returns [(question_obj, [page_markdown, ...])].

    start/end are 0-based indices into the dev set (end is exclusive).
    Questions are loaded from the JSON file bundled with the fanoutqa package
    (no network). Evidence pages are fetched via Wikipedia's Revisions API
    (pinned to the Nov 20 2023 dataset epoch) and cached to
    ~/.cache/fanoutqa/ — so only the first run for each page hits the network.

    The dev-set JSON is loaded in a fixed order so task indices are stable
    across runs; no randomness is involved.
    """
    try:
        from fanoutqa import load_dev, wiki_content
    except ImportError as exc:
        raise SystemExit("fanoutqa is not installed. Run: uv add fanoutqa") from exc

    questions = load_dev()[start:end]
    result: list[tuple[Any, list[str]]] = []
    for q in questions:
        pages: list[str] = []
        for ev in q.necessary_evidence:
            text = wiki_content(ev)
            if text and text.strip():
                pages.append(text)
        result.append((q, pages))
    return result


# ── Evaluation ────────────────────────────────────────────────────────────────

_ROUGE = _RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)


def _str_answer(ans: Any) -> str:
    if isinstance(ans, list):
        return "\n".join(_str_answer(a) for a in ans)
    if isinstance(ans, dict):
        return "\n".join(f"{k} - {_str_answer(v)}" for k, v in ans.items())
    if isinstance(ans, bool):
        return "yes" if ans else "no"
    if ans is None:
        return ""
    return str(ans)


def _evaluate_answer(
    question: Any,
    generated_answer: str,
) -> dict[str, Any]:
    """Score using fanoutqa's official accuracy (loose + strict) and ROUGE-1/2/L."""
    try:
        from fanoutqa.eval.string import answer_in_text
    except ImportError:
        answer_in_text = None

    try:
        if answer_in_text is not None:
            result = answer_in_text(question.answer, generated_answer)
            accuracy_loose = result.score
            accuracy_strict = float(result.found)
        else:
            # fallback: simple substring
            import re as _re

            def _norm(t: str) -> str:
                t = str(t).lower()
                t = _re.sub(r"[^\w\s]", " ", t)
                return _re.sub(r"\s+", " ", t).strip()

            def _in_text(ref: Any, cand: str) -> float:
                if isinstance(ref, list):
                    scores = [_in_text(a, cand) for a in ref]
                    return sum(scores) / len(scores) if scores else 0.0
                if isinstance(ref, dict):
                    items = list(ref.keys()) + list(ref.values())
                    scores = [_in_text(a, cand) for a in items]
                    return sum(scores) / len(scores) if scores else 0.0
                if isinstance(ref, bool):
                    ref = "yes" if ref else "no"
                nr, nc = _norm(str(ref)), _norm(cand)
                return 1.0 if _re.search(rf"\b{_re.escape(nr)}\b", nc) else 0.0

            accuracy_loose = _in_text(question.answer, generated_answer)
            accuracy_strict = 1.0 if accuracy_loose == 1.0 else 0.0

        rouge = _ROUGE.score(_str_answer(question.answer), _str_answer(generated_answer))
        return {
            "accuracy_loose": accuracy_loose,
            "accuracy_strict": accuracy_strict,
            "rouge1": rouge["rouge1"].fmeasure,
            "rouge2": rouge["rouge2"].fmeasure,
            "rougeL": rouge["rougeL"].fmeasure,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _ok(b: bool | None) -> str:
    if b is True:
        return "✓"
    if b is False:
        return "✗"
    return "—"


# ── Trial ─────────────────────────────────────────────────────────────────────


def _run_trial(
    client: httpx.Client,
    question: Any,
    pages: list[str],
    max_pages_per_agent: int,
    rounds: int,
    trial_idx: int,
    out: _Tee,
) -> dict[str, Any]:
    n_agents = _compute_n_agents(len(pages), max_pages_per_agent)
    chunks = _split_pages(pages, n_agents)

    out(f"\n── Question {trial_idx} ─────────────────────────────────────────")
    out(f"Question      : {question.question}")
    out(f"Expected      : {question.answer}")
    out(f"Evidence pages: {len(pages)}  →  {n_agents} agents ({max_pages_per_agent} max/agent)")

    agents = _create_bench_agents(client, n_agents)
    try:
        created = _attach_files(client, agents, chunks, file_label=f"q{trial_idx}")
        try:
            t0 = time.perf_counter()
            sim = _run_swarm(client, question.question, rounds, n_agents, out=out)
            elapsed = time.perf_counter() - t0
        finally:
            _detach_files(client, created)
    finally:
        _delete_bench_agents(client, agents)

    scores = _evaluate_answer(question, sim["final_answer"])
    accuracy_loose = scores.get("accuracy_loose", 0.0)
    accuracy_strict = bool(scores.get("accuracy_strict", 0.0))

    out(
        f"  strict {_ok(accuracy_strict)}  loose={accuracy_loose:.2f}  "
        f"rounds={sim['termination_round']}  "
        f"reason={sim['termination_reason']}  "
        f"{elapsed:5.1f}s"
    )
    out(f"  Generated : {(sim['final_answer'] or '(none)').strip()}")
    out(f"  Reference : {question.answer}")
    if "rouge1" in scores:
        out(
            f"  ROUGE-1={scores['rouge1']:.3f}"
            f"  ROUGE-2={scores.get('rouge2', 0):.3f}"
            f"  ROUGE-L={scores.get('rougeL', 0):.3f}"
        )

    return {
        "trial": trial_idx,
        "accuracy_loose": accuracy_loose,
        "accuracy_strict": accuracy_strict,
        "n_agents": n_agents,
        "n_pages": len(pages),
        "termination_round": sim["termination_round"],
        "termination_reason": sim["termination_reason"],
        "elapsed_s": elapsed,
        "rouge1": scores.get("rouge1"),
        "rouge2": scores.get("rouge2"),
        "rougeL": scores.get("rougeL"),
        "answer": sim["final_answer"],
    }


# ── Summary ───────────────────────────────────────────────────────────────────


def _compute_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    rouge1_vals = [r["rouge1"] for r in rows if r.get("rouge1") is not None]
    rouge2_vals = [r["rouge2"] for r in rows if r.get("rouge2") is not None]
    rougel_vals = [r["rougeL"] for r in rows if r.get("rougeL") is not None]
    return {
        "n_questions": len(rows),
        "accuracy_loose": statistics.mean(r["accuracy_loose"] for r in rows),
        "accuracy_strict": sum(1 for r in rows if r["accuracy_strict"]) / len(rows),
        "avg_rounds": statistics.mean(r["termination_round"] or 0 for r in rows),
        "avg_agents": statistics.mean(r["n_agents"] for r in rows),
        "avg_sources": statistics.mean(r["n_pages"] for r in rows),
        "avg_time_s": statistics.mean(r["elapsed_s"] for r in rows),
        "rouge1": statistics.mean(rouge1_vals) if rouge1_vals else None,
        "rouge2": statistics.mean(rouge2_vals) if rouge2_vals else None,
        "rougeL": statistics.mean(rougel_vals) if rougel_vals else None,
    }


def _summarise(rows: list[dict[str, Any]], out: _Tee) -> None:
    out("\n── Summary ──────────────────────────────────────────────────")
    if not rows:
        return
    s = _compute_summary(rows)
    out(f"{'metric':22s}  {'value':>10s}")
    out(f"{'accuracy (loose)':22s}  {s['accuracy_loose'] * 100:>9.1f}%")
    out(f"{'accuracy (strict)':22s}  {s['accuracy_strict'] * 100:>9.1f}%")
    out(f"{'avg rounds':22s}  {s['avg_rounds']:>10.2f}")
    out(f"{'avg agents/question':22s}  {s['avg_agents']:>10.2f}")
    out(f"{'avg sources/question':22s}  {s['avg_sources']:>10.2f}")
    out(f"{'avg time':22s}  {s['avg_time_s']:>9.1f}s")
    if s.get("rouge1") is not None:
        out(f"{'ROUGE-1':22s}  {s['rouge1']:>10.3f}")
    if s.get("rouge2") is not None:
        out(f"{'ROUGE-2':22s}  {s['rouge2']:>10.3f}")
    if s.get("rougeL") is not None:
        out(f"{'ROUGE-L':22s}  {s['rougeL']:>10.3f}")


# ── Results file ──────────────────────────────────────────────────────────────


def _update_results_file(path: Path, new_rows: list[dict[str, Any]]) -> None:
    """Merge new_rows into path (JSON), keyed by trial index, then rewrite summary."""
    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            existing = data.get("results", [])
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    by_trial: dict[int, dict[str, Any]] = {r["trial"]: r for r in existing}
    for row in new_rows:
        by_trial[row["trial"]] = row
    merged = sorted(by_trial.values(), key=lambda r: r["trial"])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"results": merged, "summary": _compute_summary(merged)},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ── Entry point ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the FanOutQA evidence-provided benchmark against the ECSAS swarm."
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="1-based index of the first task to run (default: 1).",
    )
    parser.add_argument(
        "--questions",
        type=int,
        default=5,
        help="Number of FanOutQA dev-set questions to evaluate (default: 5).",
    )
    parser.add_argument(
        "--max-pages-per-agent",
        type=int,
        default=_MAX_PAGES_PER_AGENT,
        dest="max_pages",
        help=(
            f"Max Wikipedia pages per agent; derives agent count (default: {_MAX_PAGES_PER_AGENT})."
        ),
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=10,
        help="Swarm discussion rounds per question (default: 10).",
    )
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
            "Mirror output to a log file. Omit value for auto-named "
            f"{_BENCH_RESULT_DIR}/fanoutqa-benchmark-YYYYMMDD-HHMM.log."
        ),
    )
    parser.add_argument(
        "--results-file",
        default=None,
        metavar="PATH",
        help=(
            "JSON file to write per-task scores and summary. "
            "A bare filename (e.g. results.json) is placed inside "
            f"{_BENCH_RESULT_DIR}/ automatically; an explicit path is used as-is. "
            "If the file already exists, new results are merged by task index "
            "and the summary is recalculated."
        ),
    )
    args = parser.parse_args(argv)

    if args.start < 1:
        parser.error("--start must be >= 1")

    # Convert 1-based --start to 0-based slice indices.
    q_start = args.start - 1
    q_end = q_start + args.questions

    log_path = _resolve_log_path(args.log)
    log_file = log_path.open("w", encoding="utf-8") if log_path else None
    out = _Tee(log_file)
    if log_path:
        out(f"# Logging to {log_path}")

    try:
        out(
            f"Loading FanOutQA dev question(s) {args.start}-{args.start + args.questions - 1} "
            f"with evidence…"
        )
        qa_pairs = _load_questions_and_evidence(q_start, q_end)
        out(
            f"Loaded {len(qa_pairs)} question(s).  "
            f"max_pages_per_agent={args.max_pages}  rounds={args.rounds}  "
            f"model={_BENCH_MODEL}"
        )

        all_rows: list[dict[str, Any]] = []
        with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
            for trial_idx, (question, pages) in enumerate(qa_pairs, start=args.start):
                try:
                    row = _run_trial(
                        client,
                        question,
                        pages,
                        max_pages_per_agent=args.max_pages,
                        rounds=args.rounds,
                        trial_idx=trial_idx,
                        out=out,
                    )
                    all_rows.append(row)
                except httpx.HTTPError as exc:
                    print(f"Question {trial_idx} failed: {exc}", file=sys.stderr)

        if all_rows:
            _summarise(all_rows, out)

        if all_rows and args.results_file is not None:
            results_path = _resolve_output_path(args.results_file)
            _update_results_file(results_path, all_rows)
            out(f"\nResults written to {results_path}")
    finally:
        if log_file is not None:
            log_file.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
