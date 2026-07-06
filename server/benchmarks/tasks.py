"""Benchmark task schema + suite loading.

A ``BenchmarkTask`` bundles a prompt, an agent roster + source files (the
demo-canvas shape used elsewhere in the app), and a gold rubric of findings a
good answer should cover. ``load_suite`` globs a directory of ``*.json`` task
files into validated ``BenchmarkTask`` objects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]


class GoldFinding(BaseModel):
    """One item in a task's gold rubric — a defect a good answer should surface."""

    id: str
    description: str
    must_cite: str  # doc section that grounds it, e.g. "§4.2"
    severity: Literal["high", "medium", "low"]


class BenchmarkTask(BaseModel):
    id: str
    prompt: str
    agents: list[dict[str, Any]]  # demo-file agent shape
    sources: list[dict[str, Any]]  # demo-file source shape
    rubric: list[GoldFinding]
    tier: Literal["single-domain", "cross-domain", "multi-turn"]


def load_suite(path: Path) -> list[BenchmarkTask]:
    """Load every ``*.json`` task file in ``path`` as a validated ``BenchmarkTask``."""
    tasks = []
    for file_path in sorted(path.glob("*.json")):
        raw = json.loads(file_path.read_text())
        tasks.append(BenchmarkTask.model_validate(raw))
    return tasks
