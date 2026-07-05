"""Pure dict-list → markdown comparison report. No I/O, no DB, no LLM calls —
just formatting, so it stays trivially testable."""

from __future__ import annotations

import statistics
from typing import Any


def build_report(rows: list[dict[str, Any]]) -> str:
    """``rows`` is a flat list of ``{"result": BenchmarkResult dict, "score":
    AnswerScore dict}`` — one per mode x task x trial. Never single-run
    numbers: every mode row is a mean ± spread across its trials."""
    by_mode: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_mode.setdefault(row["result"]["mode"], []).append(row)

    lines = [
        "# Benchmark Report",
        "",
        "## Mode Comparison",
        "",
        "| Mode | Coverage (mean ± sd) | Grounded % | Contradictions (mean) "
        "| Tokens (mean) | Wall s (mean) | Trials |",
        "|---|---|---|---|---|---|---|",
    ]
    for mode, mode_rows in sorted(by_mode.items()):
        coverages = [r["score"]["coverage_score"] for r in mode_rows]
        mean_cov = statistics.mean(coverages) if coverages else 0.0
        sd_cov = statistics.stdev(coverages) if len(coverages) > 1 else 0.0
        grounded_flags = [f["grounded"] for r in mode_rows for f in r["score"]["rubric"]]
        grounded_pct = (100 * sum(grounded_flags) / len(grounded_flags)) if grounded_flags else 0.0
        contradictions = [r["score"]["contradictions"] for r in mode_rows]
        tokens = [r["result"]["tokens"] for r in mode_rows]
        wall = [r["result"]["wall_seconds"] for r in mode_rows]
        lines.append(
            f"| {mode} | {mean_cov:.3f} ± {sd_cov:.3f} | {grounded_pct:.1f}% | "
            f"{statistics.mean(contradictions):.2f} | {statistics.mean(tokens):.1f} | "
            f"{statistics.mean(wall):.2f} | {len(mode_rows)} |"
        )

    lines += ["", "## Per-Task Breakdown", ""]
    by_task: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_task.setdefault(row["result"]["task_id"], []).append(row)
    for task_id, task_rows in sorted(by_task.items()):
        lines.append(f"### {task_id}")
        lines.append("")
        for row in sorted(task_rows, key=lambda r: (r["result"]["mode"], r["result"]["trial"])):
            r, s = row["result"], row["score"]
            flag = (
                " (judge parse failed)"
                if row["score"].get("metadata", {}).get("judge_parse_failed")
                else ""
            )
            lines.append(
                f"- {r['mode']} trial {r['trial']}: coverage={s['coverage_score']:.3f}, "
                f"contradictions={s['contradictions']}{flag}"
            )
        lines.append("")

    ablated_rows = [r for r in rows if r["result"]["metadata"].get("lost_subtasks")]
    if ablated_rows:
        lines += ["## Ablation", ""]
        for row in ablated_rows:
            r = row["result"]
            lost = r["metadata"]["lost_subtasks"]
            lines.append(f"- {r['mode']} / {r['task_id']}: lost subtasks: {lost}")
        lines.append("")

    return "\n".join(lines)
