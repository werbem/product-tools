"""Baseline score report loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_score_report(path: Path) -> dict[str, Any]:
    """Load a score_report.json file."""

    return json.loads(path.read_text(encoding="utf-8"))
