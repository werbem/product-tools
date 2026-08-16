"""Persist benchmark results to evaluation/results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ResultStore:
    def __init__(self, result_dir: Path) -> None:
        self.result_dir = result_dir
        self.result_dir.mkdir(parents=True, exist_ok=True)

    def save(self, case_id: str, result: dict[str, Any]) -> Path:
        target = self.result_dir / f"{case_id}.json"
        target.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target
