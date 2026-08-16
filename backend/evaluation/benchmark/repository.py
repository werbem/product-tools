"""Local JSON snapshot storage (V1)."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.benchmark.models import EvaluationSnapshot


DEFAULT_HISTORY_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "evaluation" / "history.json"
)


def _snapshot_dict(snapshot) -> dict:
    if isinstance(snapshot, EvaluationSnapshot):
        return snapshot.to_dict()
    if isinstance(snapshot, dict):
        return snapshot
    raise TypeError("snapshot must be an EvaluationSnapshot or dict")


def load_snapshots(path=None) -> list[dict]:
    target = Path(path) if path is not None else DEFAULT_HISTORY_PATH
    if not target.exists():
        return []
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return data


def save_snapshot(snapshot, path=None) -> dict:
    target = Path(path) if path is not None else DEFAULT_HISTORY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    snapshots = load_snapshots(target)
    snapshots.append(_snapshot_dict(snapshot))
    with open(target, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)
    return snapshots[-1]
