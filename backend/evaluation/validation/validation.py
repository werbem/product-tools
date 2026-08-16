"""Production Quality Validation V1 core logic (offline)."""

from __future__ import annotations

from evaluation.benchmark.regression import detect_regression
from evaluation.quality_evaluator import evaluate, normalize_report_input


METRICS = [
    "overall_score",
    "temporal_compliance",
    "evidence_integrity",
    "reasoning_quality",
    "strategy_traceability",
]


def _as_dict(obj) -> dict:
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return obj


def evaluate_state(state: dict) -> dict:
    """Run the quality evaluation layer over a persisted workflow state."""
    return _as_dict(evaluate(normalize_report_input(state)))


def _metric_value(result: dict, metric: str):
    if metric == "overall_score":
        return result.get("overall_score")
    m = result.get("metrics", {}).get(metric, {})
    if isinstance(m, dict):
        return m.get("score")
    return m


def has_quality_score(state: dict) -> bool:
    """Whether the state contains the Evidence Quality Evaluation artifacts."""
    evidence_items = (state.get("evidence_bundle") or {}).get("evidence_items") or []
    return any(e.get("quality_score") for e in evidence_items)


def _input_key(input_data: dict) -> tuple:
    return (
        input_data.get("our_company"),
        input_data.get("competitor_company"),
        input_data.get("product"),
        input_data.get("objective"),
    )


def _has_report(state: dict) -> bool:
    rd = state.get("report_document") or {}
    return bool(rd and (rd.get("formats") or rd.get("markdown")))


def discover_cases(tasks: dict, before_boundary: str = "2026-08-04") -> list[dict]:
    """Pair pre-boundary (before) with post-boundary (after) reports.

    Only same-input pairs are produced. The boundary separates the earlier
    generation era (before the quality-control work) from the later era.
    Reports are ordered by ``updated_at`` and zipped, so the resulting case
    count is bounded by the smaller side.
    """
    groups: dict[tuple, dict] = {}
    for tid, task in tasks.items():
        state = task.get("state", {})
        if not _has_report(state):
            continue
        ui = state.get("user_input") or state.get("validated_input") or {}
        key = _input_key(ui)
        bucket = "after" if (state.get("updated_at") or "") >= before_boundary else "before"
        group = groups.setdefault(key, {"before": [], "after": [], "input": ui})
        group[bucket].append((state.get("updated_at") or "", tid))

    cases: list[dict] = []
    for group in groups.values():
        group["before"].sort()
        group["after"].sort()
        for before, after in zip(group["before"], group["after"]):
            cases.append(
                {
                    "id": f"case_{len(cases) + 1:03d}",
                    "input": group["input"],
                    "before_report_id": before[1],
                    "after_report_id": after[1],
                    "evaluation_result": None,
                }
            )
    return cases


def compare_before_after(before_state: dict, after_state: dict) -> dict:
    before = evaluate_state(before_state)
    after = evaluate_state(after_state)
    metrics = {}
    for metric in METRICS:
        bv = _metric_value(before, metric)
        av = _metric_value(after, metric)
        metrics[metric] = {
            "before": bv,
            "after": av,
            "delta": round((av or 0.0) - (bv or 0.0), 2),
        }
    # "after" is current, "before" is baseline: a drop means a regression.
    regressions = [f.to_dict() for f in detect_regression(after, before)]
    return {"metrics": metrics, "regressions": regressions}


def build_summary(cases: list[dict]) -> dict:
    deltas: dict[str, list[float]] = {m: [] for m in METRICS}
    regressions: list[dict] = []
    for case in cases:
        ev = case.get("evaluation_result") or {}
        for metric in METRICS:
            delta = (ev.get("metrics") or {}).get(metric, {}).get("delta")
            if delta is not None:
                deltas[metric].append(delta)
        for finding in ev.get("regressions", []):
            regressions.append({"case_id": case["id"], **finding})

    average_improvement = {}
    for metric in METRICS:
        values = deltas[metric]
        average_improvement[metric] = round(sum(values) / len(values), 2) if values else 0.0

    improved_metrics = [m for m in METRICS if average_improvement[m] > 0]

    return {
        "cases": len(cases),
        "average_improvement": average_improvement,
        "improved_metrics": improved_metrics,
        "regressions": regressions,
    }


def run_validation(tasks: dict, cases=None) -> dict:
    if cases is None:
        cases = discover_cases(tasks)
    for case in cases:
        before = tasks[case["before_report_id"]]["state"]
        after = tasks[case["after_report_id"]]["state"]
        case["evaluation_result"] = compare_before_after(before, after)

    summary = build_summary(cases)
    before_after_quality_report = [
        {
            "id": c["id"],
            "input": c["input"],
            "before_report_id": c["before_report_id"],
            "after_report_id": c["after_report_id"],
            "metrics": c["evaluation_result"]["metrics"],
            "regressions": c["evaluation_result"]["regressions"],
        }
        for c in cases
    ]
    return {
        "cases": cases,
        "before_after_quality_report": before_after_quality_report,
        "summary": summary,
    }
