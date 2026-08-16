"""Load benchmark cases from the evaluation/cases directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_case(path: Path) -> dict[str, Any]:
    """Load a single JSON benchmark case."""

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_cases(case_dir: Path) -> list[dict[str, Any]]:
    """Load all JSON cases, sorted by case_id."""

    cases = [load_case(path) for path in sorted(case_dir.glob("*.json"))]
    return cases
