"""Benchmark generators and evaluators."""

from api.benchmarks.needlehaystack import BENCHMARKS
from api.benchmarks.needlehaystack import router as benchmark_router

__all__ = ["BENCHMARKS", "benchmark_router"]
