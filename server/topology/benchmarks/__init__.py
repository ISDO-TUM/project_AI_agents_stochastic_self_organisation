"""Benchmark generators and evaluators."""

from server.topology.benchmarks.needlehaystack import BENCHMARKS
from server.topology.benchmarks.needlehaystack import router as benchmark_router

__all__ = ["BENCHMARKS", "benchmark_router"]
