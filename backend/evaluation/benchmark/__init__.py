"""Analysis Quality Memory & Regression Benchmark V1.

Offline tooling for persisting evaluation snapshots, running benchmark cases,
detecting version regressions, and tracking quality trends. No agents, no
workflow nodes, no LLM calls, no production generation changes.
"""

from evaluation.benchmark.benchmark_runner import (
    calculate_quality_trend,
    load_cases,
    run_benchmark,
)
from evaluation.benchmark.models import (
    BenchmarkResult,
    EvaluationSnapshot,
    QualityTrend,
    RegressionFinding,
)
from evaluation.benchmark.regression import detect_regression
from evaluation.benchmark.repository import (
    DEFAULT_HISTORY_PATH,
    load_snapshots,
    save_snapshot,
)

__all__ = [
    "EvaluationSnapshot",
    "RegressionFinding",
    "BenchmarkResult",
    "QualityTrend",
    "detect_regression",
    "run_benchmark",
    "load_cases",
    "calculate_quality_trend",
    "load_snapshots",
    "save_snapshot",
    "DEFAULT_HISTORY_PATH",
]
