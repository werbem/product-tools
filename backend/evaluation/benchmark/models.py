"""Data models for the offline quality benchmark (V1)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


def result_as_dict(obj) -> dict:
    """Normalize a dataclass result or plain dict into a plain dict."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return obj


def metric_score(value):
    """Read a flat numeric score from either ``95`` or ``{"score": 95}``."""
    if isinstance(value, dict):
        return value.get("score")
    return value


def _flatten_metrics(metrics: dict) -> dict:
    flat: dict = {}
    for key, value in (metrics or {}).items():
        if isinstance(value, dict) and "score" in value:
            flat[key] = value["score"]
        elif isinstance(value, (int, float)):
            flat[key] = value
    return flat


@dataclass
class EvaluationSnapshot:
    """A persisted evaluation result for one analysis run."""

    analysis_version: str
    report_id: str
    overall_score: float
    metrics: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "EvaluationSnapshot":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_evaluation(
        cls,
        result,
        analysis_version: str,
        report_id: str,
        issues=None,
    ) -> "EvaluationSnapshot":
        data = result_as_dict(result)
        return cls(
            analysis_version=analysis_version,
            report_id=report_id,
            overall_score=data.get("overall_score", 0.0) or 0.0,
            metrics=_flatten_metrics(data.get("metrics", {}) or {}),
            issues=list(issues or []),
        )


@dataclass
class RegressionFinding:
    type: str
    metric: str
    change: float
    severity: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BenchmarkResult:
    total: int
    passed: int
    failed: int
    regression_detected: bool
    findings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QualityTrend:
    trend: str
    average_score: float
    metric_trends: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {"trend": self.trend, "average_score": self.average_score}
        data.update(self.metric_trends)
        return data
