"""Baseline benchmark harness — compares B-01 single-agent, B-02 topology,
B-03 minimal supervisor, and B-04 ECSAS swarm on the same tasks, blind-judged
against a gold rubric (2026-07-04-baseline-benchmark-harness).

Not wired into the running app — this is an offline research/evaluation tool
invoked via ``uv run python -m server.benchmarks.run``. It shares the app's
models and DB layer but adds no HTTP routes of its own.
"""
