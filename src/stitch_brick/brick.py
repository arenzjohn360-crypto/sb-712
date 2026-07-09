"""
Brick module — fundamental computational unit of SB-712 Stitch Brick.

Each brick:
  - Has a unique ID and current health state
  - Computes a deterministic SHA-256-based output given input bytes
  - Seals its output with SHA-256(payload) so tampering is detectable
  - Accepts fault injection for validation testing
"""
from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class BrickState(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"
    RECOVERING = "RECOVERING"


@dataclass
class BrickOutput:
    """Signed output produced by a brick computation."""

    brick_id: str
    payload: bytes
    seal: str          # hex SHA-256(payload) at time of production
    timestamp: float
    fault_injected: bool = False

    def verify_seal(self) -> bool:
        """Return True if the seal matches SHA-256(payload)."""
        return hashlib.sha256(self.payload).hexdigest() == self.seal

    def as_dict(self) -> dict:
        return {
            "brick_id": self.brick_id,
            "payload_hex": self.payload.hex(),
            "seal": self.seal,
            "timestamp": self.timestamp,
            "seal_valid": self.verify_seal(),
            "fault_injected": self.fault_injected,
        }


# All valid fault modes that can be injected into a brick.
FAULT_TYPES = frozenset(
    {
        "none",
        "byte_corruption",   # flip a byte in payload, keep original seal → mismatch
        "hash_mismatch",     # produce valid payload but wrong seal
        "crash",             # raise RuntimeError on compute()
        "hallucinate",       # random payload with a valid seal (semantically garbage)
        "degraded_slow",     # add simulated latency
    }
)


class BrickModule:
    """
    A SB-712 Stitch Brick computational unit.

    compute(input_data) → BrickOutput (deterministic, SHA-256 sealed)
    inject_fault(fault_type) → activate a failure mode
    clear_fault() → remove active fault and enter RECOVERING state
    mark_healthy() → reset to HEALTHY
    mark_quarantined() → isolate brick
    """

    def __init__(self, brick_id: str, seed: int = 0) -> None:
        self.brick_id = brick_id
        self.state = BrickState.HEALTHY
        self._rng = random.Random(seed)
        self._active_fault: str = "none"

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------

    def compute(self, input_data: bytes) -> BrickOutput:
        if self.state == BrickState.FAILED:
            raise RuntimeError(
                f"Brick {self.brick_id!r} is in FAILED state — cannot compute."
            )

        if self._active_fault == "degraded_slow":
            time.sleep(0.001)

        # Deterministic honest output: sha256(input || brick_id)
        raw: bytes = hashlib.sha256(input_data + self.brick_id.encode()).digest()
        honest_seal: str = hashlib.sha256(raw).hexdigest()

        if self._active_fault == "byte_corruption":
            # Corrupt a byte in payload, keep the original seal → seal mismatch
            mutated = bytearray(raw)
            idx = self._rng.randrange(len(mutated))
            mutated[idx] ^= 0xFF
            return BrickOutput(
                brick_id=self.brick_id,
                payload=bytes(mutated),
                seal=honest_seal,   # seal still covers original raw
                timestamp=time.time(),
                fault_injected=True,
            )

        if self._active_fault == "hash_mismatch":
            # Produce correct payload but supply a fabricated seal
            wrong_seal = hashlib.sha256(b"WRONG_SEED" + raw).hexdigest()
            return BrickOutput(
                brick_id=self.brick_id,
                payload=raw,
                seal=wrong_seal,
                timestamp=time.time(),
                fault_injected=True,
            )

        if self._active_fault == "hallucinate":
            # Fully random payload with a seal that matches it (hash passes),
            # but the semantic content bears no relation to the input.
            hallucinated = bytes(self._rng.getrandbits(8) for _ in range(32))
            hall_seal = hashlib.sha256(hallucinated).hexdigest()
            return BrickOutput(
                brick_id=self.brick_id,
                payload=hallucinated,
                seal=hall_seal,
                timestamp=time.time(),
                fault_injected=True,
            )

        # Healthy / degraded_slow path
        return BrickOutput(
            brick_id=self.brick_id,
            payload=raw,
            seal=honest_seal,
            timestamp=time.time(),
            fault_injected=False,
        )

    # ------------------------------------------------------------------
    # Fault management
    # ------------------------------------------------------------------

    def inject_fault(self, fault_type: str) -> None:
        if fault_type not in FAULT_TYPES:
            raise ValueError(
                f"Unknown fault type {fault_type!r}. Valid: {sorted(FAULT_TYPES)}"
            )
        self._active_fault = fault_type
        if fault_type == "crash":
            self.state = BrickState.FAILED
        elif fault_type in ("byte_corruption", "hash_mismatch", "hallucinate", "degraded_slow"):
            self.state = BrickState.DEGRADED
        # "none" leaves state unchanged

    def clear_fault(self) -> None:
        self._active_fault = "none"
        if self.state != BrickState.QUARANTINED:
            self.state = BrickState.RECOVERING

    def mark_healthy(self) -> None:
        self._active_fault = "none"
        self.state = BrickState.HEALTHY

    def mark_quarantined(self) -> None:
        self.state = BrickState.QUARANTINED

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"BrickModule(id={self.brick_id!r}, "
            f"state={self.state.value}, fault={self._active_fault!r})"
        )
