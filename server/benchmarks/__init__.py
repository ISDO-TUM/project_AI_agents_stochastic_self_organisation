"""Benchmark generators and evaluators."""

from server.benchmarks.needlehaystack import BENCHMARKS
from server.benchmarks.needlehaystack import router as benchmark_router

__all__ = ["BENCHMARKS", "benchmark_router"]
