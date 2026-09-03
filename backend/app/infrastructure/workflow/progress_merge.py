"""Merge workflow progress — never regress fine-grained mid-node values."""


def merge_progress(existing: float | None, new: float) -> float:
    """Return the higher of two progress values (0–100)."""
    current = float(existing or 0.0)
    incoming = float(new or 0.0)
    return max(current, incoming)
