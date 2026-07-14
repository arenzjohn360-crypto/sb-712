"""
Braid — orchestration layer managing a set of BrickModules connected via Strands.

Responsibilities:
  - Route input data through all healthy bricks
  - Run each output through the VerificationGate (structural + hash + semantic)
  - Commit verified outputs to the ProtectedSpine
  - Track verification failures for downstream quarantine/recovery

VerificationGate implements the three-check protocol:
  1. Structural  — payload is non-empty bytes
  2. Hash        — seal == SHA-256(payload)
  3. Semantic    — payload matches expected deterministic computation
                   (a hallucinated payload will pass hash but fail semantic)
"""
from __future__ import annotations

import hashlib
import time
from typing import Dict, List, Optional, Tuple

from .brick import BrickModule, BrickOutput, BrickState
from .spine import ProtectedSpine, SpineVerificationError
from .strand import StrandChannel


class VerificationGate:
    """
    Three-pass output verifier.

    verify(output, expected_input) → (structural_ok, hash_ok, semantic_ok, reason)

    All three must be True before an output may touch the Spine.
    Hallucinated outputs pass hash but fail semantic when expected_input is supplied.
    """

    def verify(
        self,
        output: BrickOutput,
        expected_input: Optional[bytes] = None,
    ) -> Tuple[bool, bool, bool, str]:
        # --- Pass 1: Structural ---
        if not isinstance(output.payload, bytes) or len(output.payload) == 0:
            return False, False, False, "structural: empty or invalid payload"

        # --- Pass 2: Hash integrity ---
        hash_ok = output.verify_seal()
        if not hash_ok:
            return (
                True,
                False,
                False,
                f"hash: seal mismatch for brick {output.brick_id!r}",
            )

        # --- Pass 3: Semantic (deterministic reference check) ---
        if expected_input is not None:
            expected_payload = hashlib.sha256(
                expected_input + output.brick_id.encode()
            ).digest()
            if output.payload != expected_payload:
                return (
                    True,
                    True,
                    False,
                    f"semantic: output does not match expected computation "
                    f"for brick {output.brick_id!r} "
                    f"(expected {expected_payload[:4].hex()}…, "
                    f"got {output.payload[:4].hex()}…)",
                )

        return True, True, True, "ok"


class BraidOrchestrator:
    """
    Manages BRICK_COUNT BrickModules connected via StrandChannels.

    process_round(input_data):
      - Runs all healthy/recovering bricks
      - Verifies each output via VerificationGate
      - Commits verified outputs to ProtectedSpine
      - Returns a round-summary dict
    """

    def __init__(self, brick_count: int = 10, seed: int = 0) -> None:
        self._gate = VerificationGate()
        self._spine = ProtectedSpine()
        self._bricks: Dict[str, BrickModule] = {}
        self._strands: Dict[str, StrandChannel] = {}
        self._verification_failures: List[dict] = []
        self._committed_count: int = 0

        for i in range(brick_count):
            brick_id = f"brick-{i:03d}"
            self._bricks[brick_id] = BrickModule(brick_id=brick_id, seed=seed + i)
            self._strands[brick_id] = StrandChannel(
                sender_id=brick_id,
                receiver_id="braid-collector",
            )

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def process_round(self, input_data: bytes) -> dict:
        """
        Send *input_data* through every active brick, verify outputs,
        commit verified ones to the Spine.  Returns a summary dict.
        """
        results: dict = {
            "input_seal": hashlib.sha256(input_data).hexdigest(),
            "bricks_attempted": 0,
            "bricks_verified": 0,
            "bricks_failed": 0,
            "bricks_skipped": 0,   # bricks in FAILED/QUARANTINED state — a detectable fault
            "verification_failures": [],
            "spine_chain_seal": "",
        }

        for brick_id, brick in self._bricks.items():
            if brick.state in (BrickState.FAILED, BrickState.QUARANTINED):
                # Skipped bricks are recorded as a detectable availability fault
                results["bricks_skipped"] += 1
                failure = {
                    "brick_id": brick_id,
                    "reason": f"brick unavailable: state={brick.state.value}",
                }
                results["verification_failures"].append(failure)
                self._verification_failures.append(
                    {**failure, "timestamp": time.time()}
                )
                continue

            results["bricks_attempted"] += 1

            # --- Compute ---
            try:
                output = brick.compute(input_data)
            except RuntimeError as exc:
                results["bricks_failed"] += 1
                failure = {"brick_id": brick_id, "reason": f"compute error: {exc}"}
                results["verification_failures"].append(failure)
                self._verification_failures.append(
                    {**failure, "timestamp": time.time()}
                )
                continue

            # --- Strand transit ---
            strand = self._strands[brick_id]

            # Latency anomaly detection: flag active artificial delay as a fault
            if strand._delay_ms > 0:
                results["bricks_failed"] += 1
                failure = {
                    "brick_id": brick_id,
                    "reason": f"network_delay_detected: strand delay={strand._delay_ms:.1f}ms",
                }
                results["verification_failures"].append(failure)
                self._verification_failures.append(
                    {**failure, "timestamp": time.time()}
                )
                strand.send(output.payload)   # drain the queue
                strand.receive()
                continue

            strand.send(output.payload)
            msg = strand.receive()

            if msg is None or not msg.verify_seal():
                results["bricks_failed"] += 1
                failure = {
                    "brick_id": brick_id,
                    "reason": "strand message seal mismatch (message tampered in transit)",
                }
                results["verification_failures"].append(failure)
                self._verification_failures.append(
                    {**failure, "timestamp": time.time()}
                )
                continue

            # --- VerificationGate ---
            structural_ok, hash_ok, semantic_ok, reason = self._gate.verify(
                output, expected_input=input_data
            )
            all_ok = structural_ok and hash_ok and semantic_ok

            if not all_ok:
                results["bricks_failed"] += 1
                failure = {
                    "brick_id": brick_id,
                    "reason": reason,
                    "hash_ok": hash_ok,
                    "semantic_ok": semantic_ok,
                }
                results["verification_failures"].append(failure)
                self._verification_failures.append(
                    {**failure, "timestamp": time.time()}
                )
                continue

            # --- Spine commit (triple-verified) ---
            try:
                self._spine.propose_state(
                    state_key=f"{brick_id}.output",
                    state_data=output.payload,
                    structural_ok=structural_ok,
                    behavioral_ok=semantic_ok,
                )
                self._committed_count += 1
                results["bricks_verified"] += 1
            except SpineVerificationError as exc:
                results["bricks_failed"] += 1
                failure = {"brick_id": brick_id, "reason": f"spine rejection: {exc}"}
                results["verification_failures"].append(failure)
                self._verification_failures.append(
                    {**failure, "timestamp": time.time()}
                )

        results["spine_chain_seal"] = self._spine.chain_seal()
        return results

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def spine(self) -> ProtectedSpine:
        return self._spine

    def brick(self, brick_id: str) -> BrickModule:
        return self._bricks[brick_id]

    def strand(self, brick_id: str) -> StrandChannel:
        return self._strands[brick_id]

    def brick_ids(self) -> List[str]:
        return list(self._bricks.keys())

    def healthy_brick_count(self) -> int:
        return sum(
            1 for b in self._bricks.values() if b.state == BrickState.HEALTHY
        )

    def failed_brick_count(self) -> int:
        return sum(
            1
            for b in self._bricks.values()
            if b.state in (BrickState.FAILED, BrickState.DEGRADED, BrickState.QUARANTINED)
        )

    def verification_failures(self) -> List[dict]:
        return list(self._verification_failures)

    def committed_count(self) -> int:
        return self._committed_count
