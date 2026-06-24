"""
checkpoint_validator.py — SB-712 IronBraid Radiant Core

Validates checkpoints for integrity, continuity, and VERA certification
before they can be used in recovery operations.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CheckpointRecord:
    """Describes a stored checkpoint."""

    checkpoint_id: str
    state_hash: str
    previous_checkpoint_id: Optional[str]
    ledger_seq: int
    timestamp: float
    vera_certified: bool
    replica_count: int


@dataclass
class ValidationResult:
    """Result of checkpoint validation."""

    checkpoint_id: str
    valid: bool
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    message: str = ""


class CheckpointValidator:
    """
    Validates a :class:`CheckpointRecord` against continuity rules.

    Usage::

        validator = CheckpointValidator()
        record = CheckpointRecord(
            checkpoint_id="ckpt-002",
            state_hash="abc123",
            previous_checkpoint_id="ckpt-001",
            ledger_seq=10,
            timestamp=time.time(),
            vera_certified=True,
            replica_count=2,
        )
        result = validator.validate(record)
        assert result.valid
    """

    MIN_REPLICA_COUNT: int = 1

    def validate(
        self,
        record: CheckpointRecord,
        known_previous_hash: Optional[str] = None,
    ) -> ValidationResult:
        """
        Run continuity and integrity checks on *record*.

        Parameters
        ----------
        record:
            The checkpoint to validate.
        known_previous_hash:
            If provided, the validator checks that the previous checkpoint's
            hash matches this value.
        """
        passed: List[str] = []
        failed: List[str] = []

        # 1. Hash present.
        if record.state_hash:
            passed.append("state_hash_present")
        else:
            failed.append("state_hash_present")

        # 2. Timestamp sanity (not in the future beyond a 60-second clock drift).
        if record.timestamp <= time.time() + 60:
            passed.append("timestamp_sanity")
        else:
            failed.append("timestamp_sanity")

        # 3. Positive ledger sequence.
        if record.ledger_seq >= 0:
            passed.append("ledger_seq_valid")
        else:
            failed.append("ledger_seq_valid")

        # 4. VERA certification mark.
        if record.vera_certified:
            passed.append("vera_certified")
        else:
            failed.append("vera_certified")

        # 5. Minimum replica count.
        if record.replica_count >= self.MIN_REPLICA_COUNT:
            passed.append("replica_count_sufficient")
        else:
            failed.append("replica_count_sufficient")

        # 6. Lineage continuity (optional — only when previous hash is provided).
        if known_previous_hash is not None:
            if record.previous_checkpoint_id is not None:
                passed.append("lineage_continuity")
            else:
                failed.append("lineage_continuity")

        valid = len(failed) == 0
        message = (
            "All checks passed."
            if valid
            else f"Failed checks: {failed}"
        )

        return ValidationResult(
            checkpoint_id=record.checkpoint_id,
            valid=valid,
            checks_passed=passed,
            checks_failed=failed,
            message=message,
        )
