"""Shared helpers for workflow node timeout handling."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def log_node_timeout(node: str, timeout_s: float, *, mode: str | None = None) -> None:
    """Emit a structured warning when a workflow node hits its hard budget."""
    if mode:
        logger.warning(
            "workflow node timeout: node=%s mode=%s budget_s=%.1f",
            node,
            mode,
            timeout_s,
        )
    else:
        logger.warning(
            "workflow node timeout: node=%s budget_s=%.1f",
            node,
            timeout_s,
        )
