"""Phase 7: Decision-stack E2E eval gates.

Full path: Intent → Entity → Planner → ThinRouter.
Required before flipping ``DECISION_PLANNER_ROUTING`` default to ``on``.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.application.services.decision_e2e_eval import (
    REQUIRED_E2E_SLICES,
    evaluate_e2e_suite,
)

GOLDENS_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "e2e_decision_goldens.json"
)
SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "e2e_decision_baseline_snapshot.json"
)

MIN_CASE_COUNT = 18
OVERALL_ACCURACY_THRESHOLD = 0.95
CRITICAL_ACCURACY = 1.0
MIN_CASES_PER_SLICE = 1


def _load_fixture() -> dict[str, Any]:
    return json.loads(GOLDENS_PATH.read_text(encoding="utf-8"))


def load_e2e_cases() -> list[dict[str, Any]]:
    payload = _load_fixture()
    cases = payload["cases"] if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise AssertionError(f"e2e goldens must be a list: {GOLDENS_PATH}")
    return cases


@pytest.fixture(scope="module")
def e2e_cases() -> list[dict[str, Any]]:
    return load_e2e_cases()


@pytest.fixture(scope="module")
def e2e_report(e2e_cases: list[dict[str, Any]]) -> dict[str, Any]:
    return evaluate_e2e_suite(e2e_cases)


class TestE2EGoldensMeta:
    def test_min_case_count(self, e2e_cases: list[dict[str, Any]]) -> None:
        assert len(e2e_cases) >= MIN_CASE_COUNT

    def test_required_slices_covered(self, e2e_cases: list[dict[str, Any]]) -> None:
        counts = Counter(str(c.get("slice") or "") for c in e2e_cases)
        missing = sorted(s for s in REQUIRED_E2E_SLICES if counts.get(s, 0) < MIN_CASES_PER_SLICE)
        assert not missing, f"missing e2e slices: {missing}"

    def test_dual_pairs(self, e2e_cases: list[dict[str, Any]]) -> None:
        by_id = {c["id"]: c for c in e2e_cases}
        pairs = [
            ("e2e_follow_up_ops_advice", "e2e_ca_with_prior_still_deep"),
            ("e2e_listing_only", "e2e_multi_listing_then_analyze"),
            ("e2e_invalid_deixis_with_prior", "e2e_invalid_deixis_bad_memory"),
        ]
        for a, b in pairs:
            assert by_id[a]["pair_with"] == b
            assert by_id[b]["pair_with"] == a

    def test_every_case_has_slice_and_tags(self, e2e_cases: list[dict[str, Any]]) -> None:
        bad = [
            c["id"]
            for c in e2e_cases
            if not c.get("slice") or not isinstance(c.get("tags"), list) or not c["tags"]
        ]
        assert not bad, f"cases missing slice/tags: {bad}"


class TestE2EGates:
    def test_critical_accuracy(self, e2e_report: dict[str, Any]) -> None:
        assert e2e_report["critical_accuracy"] >= CRITICAL_ACCURACY, (
            f"critical accuracy {e2e_report['critical_accuracy']:.2%} < 100%\n"
            + json.dumps(e2e_report["failures"], ensure_ascii=False, indent=2)
        )

    def test_overall_accuracy(self, e2e_report: dict[str, Any]) -> None:
        assert e2e_report["overall_accuracy"] >= OVERALL_ACCURACY_THRESHOLD, (
            f"overall {e2e_report['overall_accuracy']:.2%} "
            f"< {OVERALL_ACCURACY_THRESHOLD:.0%}\n"
            + json.dumps(e2e_report["failures"], ensure_ascii=False, indent=2)
        )

    def test_no_implicit_deep_on_forbid_cases(
        self,
        e2e_cases: list[dict[str, Any]],
        e2e_report: dict[str, Any],
    ) -> None:
        by_id = {r["id"]: r for r in e2e_report["results"]}
        for case in e2e_cases:
            if not case.get("forbid_deep"):
                continue
            r = by_id[case["id"]]
            assert r["execution_mode"] not in ("deep_fast", "deep_full"), case["id"]


class TestE2ESnapshot:
    def test_snapshot_matches_or_refresh_note(self, e2e_report: dict[str, Any]) -> None:
        """Freeze Phase 7 baseline numbers; update snapshot intentionally if suite grows."""
        snapshot = {
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "phase": 7,
            "fixture": "tests/fixtures/e2e_decision_goldens.json",
            "case_count": e2e_report["case_count"],
            "critical_count": e2e_report["critical_count"],
            "critical_accuracy": e2e_report["critical_accuracy"],
            "overall_accuracy": e2e_report["overall_accuracy"],
            "overall_threshold": OVERALL_ACCURACY_THRESHOLD,
            "gates_ok": (
                e2e_report["critical_accuracy"] >= CRITICAL_ACCURACY
                and e2e_report["overall_accuracy"] >= OVERALL_ACCURACY_THRESHOLD
            ),
            "by_slice": e2e_report["by_slice"],
            "critical_ids": [
                r["id"] for r in e2e_report["results"] if r["critical"]
            ],
        }
        if not SNAPSHOT_PATH.exists():
            SNAPSHOT_PATH.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return

        frozen = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        assert frozen.get("case_count") == e2e_report["case_count"]
        assert frozen.get("critical_count") == e2e_report["critical_count"]
        assert float(frozen.get("critical_accuracy") or 0) >= CRITICAL_ACCURACY
        assert float(frozen.get("overall_accuracy") or 0) >= OVERALL_ACCURACY_THRESHOLD
        assert frozen.get("gates_ok") is True
