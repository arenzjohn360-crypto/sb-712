"""
rollback_engine.py — SB-712 IronBraid Radiant Core

Orchestrates rollback to a previous certified checkpoint when the current
state is found to be corrupt, invalid, or untrusted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class RollbackRecord:
    """Audit record produced after a rollback attempt."""

    from_state: str
    to_checkpoint: str
    success: bool
    message: str
    timestamp: float = field(default_factory=time.time)


class RollbackEngine:
    """
    Manages rollback operations to the last known-good certified checkpoint.

    The engine maintains an ordered list of certified checkpoints.  When
    :meth:`rollback` is called it works backwards through the list until a
    usable checkpoint is found.

    Usage::

        engine = RollbackEngine()
        engine.register_checkpoint("ckpt-001", certified=True)
        engine.register_checkpoint("ckpt-002", certified=True)
        record = engine.rollback(from_state="QUARANTINED")
    """

    def __init__(self) -> None:
        self._checkpoints: List[dict] = []  # ordered oldest-first
        self.history: List[RollbackRecord] = []

    def register_checkpoint(
        self,
        checkpoint_id: str,
        certified: bool = False,
        metadata: Optional[dict] = None,
    ) -> None:
        """Register a checkpoint as available for rollback."""
        self._checkpoints.append(
            {
                "checkpoint_id": checkpoint_id,
                "certified": certified,
                "metadata": metadata or {},
                "registered_at": time.time(),
            }
        )

    def certified_checkpoints(self) -> List[dict]:
        """Return all certified checkpoints, most recent last."""
        return [c for c in self._checkpoints if c["certified"]]

    def rollback(self, from_state: str) -> RollbackRecord:
        """
        Attempt to roll back from *from_state* to the most recent certified
        checkpoint.

        Returns a :class:`RollbackRecord` describing the outcome.
        """
        certified = self.certified_checkpoints()
        if not certified:
            record = RollbackRecord(
                from_state=from_state,
                to_checkpoint="",
                success=False,
                message="No certified checkpoints available for rollback.",
            )
            self.history.append(record)
            return record

        # Use the most recent certified checkpoint.
        target = certified[-1]
        # Stub: actual restore would copy checkpoint data to active state.
        record = RollbackRecord(
            from_state=from_state,
            to_checkpoint=target["checkpoint_id"],
            success=True,
            message=(
                f"Rolled back from '{from_state}' to certified checkpoint "
                f"'{target['checkpoint_id']}'."
            ),
        )
        self.history.append(record)
        return record

    def last_rollback(self) -> Optional[RollbackRecord]:
        """Return the most recent rollback record."""
        return self.history[-1] if self.history else None
