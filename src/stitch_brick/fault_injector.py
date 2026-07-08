"""
FaultInjector — deterministic, seed-driven fault injection for SB-712 validation.

Every method is reproducible: given the same seed, the same brick is targeted
and the same fault type is applied.  Seeds are recorded in every TestResult so
any run can be replayed exactly.

Supported fault scenarios
--------------------------
byte_corruption         Random byte flip in a brick's payload (seal mismatch)
ledger_hash_mismatch    Brick supplies wrong seal (hash mismatch, structural OK)
broken_brick            Brick raises RuntimeError on compute()
80_percent_brick_failure  80 % of healthy bricks are crashed simultaneously
message_tamper          Strand payload corrupted in transit
hallucination_containment Brick returns random garbage with a valid seal
network_delay           Strand introduces artificial latency
disk_write_interrupt    Checkpoint snapshot truncated mid-write
partial_checkpoint      Required field removed from checkpoint snapshot
dependency_failure      Brick A crashes; Brick B (which depends on A) degrades
recovery_loop_failure   All bricks fail; even the last one is degraded
ledger_drift            Alias for ledger_hash_mismatch
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from .brick import BrickState
from .braid import BraidOrchestrator


# Maps CLI scenario names → injector method keys
FAULT_SCENARIOS: Dict[str, str] = {
    "byte_corruption": "byte_corruption",
    "ledger_hash_mismatch": "ledger_hash_mismatch",
    "ledger_drift": "ledger_hash_mismatch",
    "broken_brick": "broken_brick",
    "80_percent_brick_failure": "mass_failure",
    "message_tamper": "message_tamper",
    "hallucination_containment": "hallucination",
    "network_delay": "network_delay",
    "disk_write_interrupt": "disk_write_interrupt",
    "partial_checkpoint": "partial_checkpoint",
    "dependency_failure": "dependency_failure",
    "recovery_loop_failure": "recovery_loop_failure",
}


class FaultInjector:
    """
    Stateless, seed-driven fault injector.

    Every public method records the injected fault in self.injected_faults
    for inclusion in reports.
    """

    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)
        self.seed = seed
        self.injected_faults: List[dict] = []

    # ------------------------------------------------------------------
    # Brick-level faults
    # ------------------------------------------------------------------

    def byte_corruption(self, braid: BraidOrchestrator) -> str:
        """Flip a byte in the output of a randomly-selected healthy brick."""
        target = self._pick_healthy(braid)
        if target:
            braid.brick(target).inject_fault("byte_corruption")
            self._record("byte_corruption", target)
        return target or "no-healthy-brick"

    def ledger_hash_mismatch(self, braid: BraidOrchestrator) -> str:
        """Make a brick produce correct payload but a wrong seal."""
        target = self._pick_healthy(braid)
        if target:
            braid.brick(target).inject_fault("hash_mismatch")
            self._record("ledger_hash_mismatch", target)
        return target or "no-healthy-brick"

    def broken_brick(self, braid: BraidOrchestrator) -> str:
        """Crash a randomly-selected healthy brick."""
        target = self._pick_healthy(braid)
        if target:
            braid.brick(target).inject_fault("crash")
            self._record("broken_brick", target)
        return target or "no-healthy-brick"

    def hallucination(self, braid: BraidOrchestrator) -> str:
        """Make a brick produce random garbage with a valid seal (passes hash, fails semantic)."""
        target = self._pick_healthy(braid)
        if target:
            braid.brick(target).inject_fault("hallucinate")
            self._record("hallucination", target)
        return target or "no-healthy-brick"

    def message_tamper(self, braid: BraidOrchestrator) -> str:
        """Corrupt the next message on a randomly-selected healthy brick's strand."""
        target = self._pick_healthy(braid)
        if target:
            braid.strand(target).inject_tamper()
            self._record("message_tamper", target)
        return target or "no-healthy-brick"

    def network_delay(self, braid: BraidOrchestrator, delay_ms: float = 5.0) -> str:
        """Add artificial latency to a randomly-selected brick's strand."""
        target = self._pick_healthy(braid)
        if target:
            braid.strand(target).set_delay(delay_ms)
            self._record("network_delay", target, extra={"delay_ms": delay_ms})
        return target or "no-healthy-brick"

    def mass_failure(
        self, braid: BraidOrchestrator, percent: float = 0.8
    ) -> List[str]:
        """Crash *percent* fraction of healthy bricks (default 80 %)."""
        healthy = [
            bid
            for bid in braid.brick_ids()
            if braid.brick(bid).state == BrickState.HEALTHY
        ]
        count = max(1, int(len(healthy) * percent))
        chosen = self._rng.sample(healthy, min(count, len(healthy)))
        for bid in chosen:
            braid.brick(bid).inject_fault("crash")
            self._record("mass_failure", bid, extra={"percent": percent})
        return chosen

    def dependency_failure(self, braid: BraidOrchestrator) -> Optional[str]:
        """
        Crash brick-000 (provider) and degrade brick-001 (consumer that depends on it).
        """
        ids = braid.brick_ids()
        if len(ids) < 2:
            return None
        braid.brick(ids[0]).inject_fault("crash")
        braid.brick(ids[1]).inject_fault("byte_corruption")
        self._record("dependency_failure", ids[0], extra={"dependent": ids[1]})
        return ids[0]

    def recovery_loop_failure(self, braid: BraidOrchestrator) -> List[str]:
        """
        Simulate a scenario where recovery keeps failing:
        all bricks except the last are crashed; the last is degraded.
        """
        ids = braid.brick_ids()
        failed: List[str] = []
        for bid in ids[:-1]:
            braid.brick(bid).inject_fault("crash")
            failed.append(bid)
        if ids:
            braid.brick(ids[-1]).inject_fault("byte_corruption")
            failed.append(ids[-1])
        self._record("recovery_loop_failure", "all-bricks", extra={"count": len(failed)})
        return failed

    # ------------------------------------------------------------------
    # Checkpoint / snapshot faults
    # ------------------------------------------------------------------

    def partial_checkpoint(self, snapshot: dict) -> dict:
        """Remove a random field from a checkpoint snapshot to simulate partial disk write."""
        if not snapshot:
            return snapshot
        corrupted = dict(snapshot)
        key = self._rng.choice(list(corrupted.keys()))
        del corrupted[key]
        self._record("partial_checkpoint", "snapshot", extra={"removed_key": key})
        return corrupted

    def disk_write_interrupt(self, snapshot: dict) -> dict:
        """Truncate the entries list to simulate a mid-write interruption."""
        entries = snapshot.get("entries", [])
        if len(entries) > 1:
            snapshot = dict(snapshot)
            snapshot["entries"] = entries[: len(entries) // 2]
        self._record("disk_write_interrupt", "snapshot")
        return snapshot

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pick_healthy(self, braid: BraidOrchestrator) -> Optional[str]:
        candidates = [
            bid
            for bid in braid.brick_ids()
            if braid.brick(bid).state == BrickState.HEALTHY
        ]
        if not candidates:
            return None
        return self._rng.choice(candidates)

    def _record(
        self, fault_type: str, target: str, extra: Optional[dict] = None
    ) -> None:
        entry: dict = {"fault_type": fault_type, "target": target, "seed": self.seed}
        if extra:
            entry.update(extra)
        self.injected_faults.append(entry)
