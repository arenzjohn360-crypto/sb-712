"""
phoenix_triangle.py — SB-712 IronBraid Radiant Core

The Phoenix Triangle is a three-node recovery cluster (Phoenix A, B, C).
Nodes stay dormant during normal operation and wake only when a heartbeat
threshold is crossed or corruption is confirmed.

Phoenix nodes do NOT trust the newest checkpoint by default.  They run a
seven-step lineage check before restoring any state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PhoenixState(str, Enum):
    DORMANT = "DORMANT"
    SCANNING = "SCANNING"
    RESTORING = "RESTORING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


@dataclass
class CheckpointCandidate:
    """Represents a checkpoint being evaluated by Phoenix."""

    checkpoint_id: str
    hash: str
    ledger_seq: int
    timestamp: float
    mutation_distance: int
    vera_certified: bool
    lineage_ok: bool
    replica_agreement: bool


@dataclass
class PhoenixResult:
    """Outcome returned after a Phoenix recovery attempt."""

    node_id: str
    state: PhoenixState
    restored_checkpoint: Optional[str]
    message: str
    steps_passed: List[str] = field(default_factory=list)
    steps_failed: List[str] = field(default_factory=list)
    completed_at: float = field(default_factory=time.time)


class PhoenixNode:
    """
    A single Phoenix recovery node.

    Usage::

        node = PhoenixNode("phoenix-a")
        candidate = CheckpointCandidate(
            checkpoint_id="ckpt-007",
            hash="abc123",
            ledger_seq=42,
            timestamp=time.time(),
            mutation_distance=2,
            vera_certified=True,
            lineage_ok=True,
            replica_agreement=True,
        )
        result = node.evaluate_and_restore(candidate)
    """

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.state = PhoenixState.DORMANT

    def _run_lineage_checks(self, candidate: CheckpointCandidate) -> tuple[List[str], List[str]]:
        """Run the seven-step lineage check.  Returns (passed, failed)."""
        passed: List[str] = []
        failed: List[str] = []

        checks: List[tuple[str, bool]] = [
            ("checkpoint_hash_present", bool(candidate.hash)),
            ("ledger_continuity", candidate.ledger_seq > 0),
            ("replica_agreement", candidate.replica_agreement),
            ("timestamp_sanity", candidate.timestamp > 0 and candidate.timestamp <= time.time() + 60),
            ("mutation_distance_acceptable", candidate.mutation_distance < 100),
            ("vera_certification_mark", candidate.vera_certified),
            ("lineage_chain_ok", candidate.lineage_ok),
        ]

        for name, result in checks:
            if result:
                passed.append(name)
            else:
                failed.append(name)

        return passed, failed

    def evaluate_and_restore(self, candidate: CheckpointCandidate) -> PhoenixResult:
        """
        Evaluate *candidate* and restore system state if all checks pass.

        Returns a :class:`PhoenixResult` regardless of outcome.
        """
        self.state = PhoenixState.SCANNING
        passed, failed = self._run_lineage_checks(candidate)

        if failed:
            self.state = PhoenixState.FAILED
            return PhoenixResult(
                node_id=self.node_id,
                state=self.state,
                restored_checkpoint=None,
                message=f"Lineage check failed. Rejected checkpoint '{candidate.checkpoint_id}'.",
                steps_passed=passed,
                steps_failed=failed,
            )

        self.state = PhoenixState.RESTORING
        # Stub: actual restore logic would copy data from checkpoint store here.
        self.state = PhoenixState.VERIFIED
        return PhoenixResult(
            node_id=self.node_id,
            state=self.state,
            restored_checkpoint=candidate.checkpoint_id,
            message=f"Checkpoint '{candidate.checkpoint_id}' restored and verified.",
            steps_passed=passed,
            steps_failed=failed,
        )

    def go_dormant(self) -> None:
        """Return node to dormant state after recovery."""
        self.state = PhoenixState.DORMANT


class PhoenixTriangle:
    """
    Manages all three Phoenix nodes (A, B, C) as a coordinated cluster.

    Usage::

        cluster = PhoenixTriangle()
        results = cluster.recover(candidate)
    """

    def __init__(self) -> None:
        self.nodes = {
            "phoenix-a": PhoenixNode("phoenix-a"),
            "phoenix-b": PhoenixNode("phoenix-b"),
            "phoenix-c": PhoenixNode("phoenix-c"),
        }

    def recover(self, candidate: CheckpointCandidate) -> List[PhoenixResult]:
        """
        Attempt recovery using all three nodes.

        Returns results from all nodes; at least two must reach
        :attr:`PhoenixState.VERIFIED` for the recovery to be considered
        a majority success.
        """
        results = [node.evaluate_and_restore(candidate) for node in self.nodes.values()]
        verified = sum(1 for r in results if r.state == PhoenixState.VERIFIED)
        # Majority rule: 2-of-3 required.
        if verified >= 2:
            for node in self.nodes.values():
                node.go_dormant()
        return results

    def majority_verified(self, results: List[PhoenixResult]) -> bool:
        """Return True when at least 2 of 3 nodes returned VERIFIED."""
        return sum(1 for r in results if r.state == PhoenixState.VERIFIED) >= 2
