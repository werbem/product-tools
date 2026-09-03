"""Atomic JSON file store with process-level locking."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable

from app.infrastructure.persistence.copilot.exceptions import CorruptPersistenceError


class JsonFileStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self._path.exists():
                return {}
            try:
                text = self._path.read_text(encoding="utf-8")
                if not text.strip():
                    raise CorruptPersistenceError(f"empty file: {self._path}")
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise CorruptPersistenceError(f"invalid root type: {self._path}")
                return data
            except json.JSONDecodeError as exc:
                raise CorruptPersistenceError(str(exc)) from exc

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)

    def mutate(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        with self._lock:
            data = self.load()
            result = fn(data)
            self.save(data)
            return result
