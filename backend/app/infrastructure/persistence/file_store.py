"""File-based persistence for reports and tasks.

Survives server restarts by writing JSON snapshots to disk.
Replaces the purely in-memory _reports and _tasks dicts in the API layer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.config.settings import settings

# Unified with settings.data_dir (mounted volume /app/data in docker,
# repo-root data/ in local dev) so persisted tasks/reports survive
# container rebuilds instead of being written to the container layer.
DATA_DIR = settings.data_dir / "persistence"


def _ensure_dir() -> None:
    os.makedirs(str(DATA_DIR), exist_ok=True)


def load_reports() -> dict[str, dict[str, Any]]:
    """Load persisted reports from disk."""
    _ensure_dir()
    path = DATA_DIR / "reports.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_reports(reports: dict[str, dict[str, Any]]) -> None:
    """Persist reports dict to disk (atomic write)."""
    _ensure_dir()
    tmp = DATA_DIR / "reports.json.tmp"
    dst = DATA_DIR / "reports.json"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(reports, f, ensure_ascii=False, default=str)
        os.replace(tmp, dst)
    except OSError:
        pass


def load_tasks() -> dict[str, dict[str, Any]]:
    """Load persisted tasks from disk."""
    _ensure_dir()
    path = DATA_DIR / "tasks.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_tasks(tasks: dict[str, dict[str, Any]]) -> None:
    """Persist tasks dict to disk (atomic write)."""
    _ensure_dir()
    tmp = DATA_DIR / "tasks.json.tmp"
    dst = DATA_DIR / "tasks.json"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, default=str)
        os.replace(tmp, dst)
    except OSError:
        pass
