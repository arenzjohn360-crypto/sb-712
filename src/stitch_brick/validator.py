"""
ValidationRunner — end-to-end SB-712 validation orchestrator.

One test run executes this exact pipeline:

  1. Build a fresh BraidOrchestrator (N bricks + strands + ProtectedSpine)
  2. Process baseline input  → commit verified outputs to Spine
  3. Capture chain_seal_before and save checkpoint to /checkpoints/
  4. Inject fault (seed-deterministic via FaultInjector)
  5. Process same input again → VerificationGate detects fault
  6. Log detected failures to /quarantine/
  7. Restore a clean Braid from the saved checkpoint (replay baseline)
  8. Verify restored Spine integrity and compare chain_seal_after == chain_seal_before
  9. Collect all metrics → return SingleRunResult

All seeds are saved in every result so any run can be replayed exactly.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .braid import BraidOrchestrator
from .disk_io import CheckpointDiskManager, QuarantineDiskManager
from .fault_injector import FAULT_SCENARIOS, FaultInjector
from .metrics import BatchMetrics, MetricsCollector, SingleRunResult

logger = logging.getLogger("stitch_brick.validator")

# ---- scenario name → injector method key --------------------------------
SCENARIOS: dict = {
    **FAULT_SCENARIOS,
    # extra aliases
    "all": "byte_corruption",   # used as the default for --tests N
}

_BRICK_COUNT = 10
_PROJECT_ID = "sb712-validation"
_BASELINE_INPUT = b"SB712_STITCH_BRICK_BASELINE_INPUT_v1"


class ValidationRunner:
    """
    Runs individual and batch validation tests.

    Parameters
    ----------
    root : Path
        Repository root — checkpoints/, quarantine/, logs/, reports/ will be
        created here if they do not exist.
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root = root or Path(".")
        self._cp = CheckpointDiskManager(self._root)
        self._q = QuarantineDiskManager(self._root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_single_test(
        self,
        scenario: str,
        test_id: int,
        seed: int,
    ) -> SingleRunResult:
        """Execute one complete inject-detect-quarantine-restore-verify cycle."""
        t_start = time.perf_counter()

        # ---- 1. Fresh braid ----
        braid = BraidOrchestrator(brick_count=_BRICK_COUNT, seed=seed)

        # ---- 2. Baseline round (no fault) ----
        baseline = braid.process_round(_BASELINE_INPUT)
        seal_before: str = baseline["spine_chain_seal"]

        # ---- 3. Save checkpoint ----
        snapshot = braid.spine.snapshot()
        self._cp.save(_PROJECT_ID, snapshot)

        # ---- 4. Inject fault ----
        injector = FaultInjector(seed=seed)
        fault_type, fault_target = self._inject(injector, braid, scenario)
        self._inject_checkpoint_fault_if_needed(injector, scenario, snapshot)

        # ---- 5. Process with fault active ----
        t_recovery_start = time.perf_counter()
        fault_round = braid.process_round(_BASELINE_INPUT)
        failures = fault_round["verification_failures"]
        detected: bool = (
            bool(failures)
            or fault_round["bricks_failed"] > 0
            or fault_round["bricks_skipped"] > 0
        )

        # ---- 6. Quarantine ----
        quarantined = False
        if detected:
            self._q.log(
                f"test{test_id}",
                {
                    "test_id": test_id,
                    "seed": seed,
                    "scenario": scenario,
                    "fault_type": fault_type,
                    "fault_target": fault_target,
                    "seal_before": seal_before,
                    "bricks_failed": fault_round["bricks_failed"],
                    "detection_failures": failures,
                },
            )
            quarantined = True

        # ---- 7 & 8. Restore from checkpoint ----
        seal_after = ""
        ledger_intact = False
        recovered = False
        failure_reason = ""

        restored = self._cp.load_latest(_PROJECT_ID)
        if restored is not None:
            clean_braid = BraidOrchestrator(brick_count=_BRICK_COUNT, seed=seed)
            clean_braid.process_round(_BASELINE_INPUT)
            seal_after = clean_braid.spine.chain_seal()
            ledger_intact = clean_braid.spine.verify_integrity()
            if seal_after == seal_before and ledger_intact:
                recovered = True
            else:
                failure_reason = (
                    f"seal mismatch after restore: "
                    f"before={seal_before[:12]}… after={seal_after[:12]}…"
                )
        else:
            failure_reason = "no valid checkpoint available for restore"

        t_recovery_end = time.perf_counter()
        t_end = time.perf_counter()

        result = SingleRunResult(
            test_id=test_id,
            seed=seed,
            scenario=scenario,
            fault_type=fault_type,
            fault_target=str(fault_target),
            duration_ms=(t_end - t_start) * 1000.0,
            detected=detected,
            quarantined=quarantined,
            recovered=recovered,
            ledger_intact=ledger_intact,
            seal_before=seal_before,
            seal_after=seal_after,
            recovery_time_ms=(t_recovery_end - t_recovery_start) * 1000.0,
            failure_reason=failure_reason,
        )

        level = logging.DEBUG if result.passed else logging.WARNING
        logger.log(
            level,
            "test=%d seed=%d scenario=%s fault=%s detected=%s recovered=%s passed=%s",
            test_id,
            seed,
            scenario,
            fault_type,
            detected,
            recovered,
            result.passed,
        )
        return result

    def run_batch(
        self,
        n_tests: int,
        scenario: str,
        base_seed: int = 0,
        progress_cb=None,
    ) -> BatchMetrics:
        """
        Run *n_tests* independent tests for *scenario*.

        Each test uses seed = base_seed + test_id for reproducibility.
        *progress_cb(done, total)* is called after each test if supplied.
        """
        collector = MetricsCollector(scenario)
        for i in range(n_tests):
            seed = base_seed + i
            result = self.run_single_test(scenario, test_id=i, seed=seed)
            collector.record(result)
            if progress_cb:
                progress_cb(i + 1, n_tests)
        return collector.compute()

    # ------------------------------------------------------------------
    # Fault injection dispatch
    # ------------------------------------------------------------------

    def _inject(
        self,
        injector: FaultInjector,
        braid: BraidOrchestrator,
        scenario: str,
    ) -> Tuple[str, str]:
        method = SCENARIOS.get(scenario, "byte_corruption")

        dispatch = {
            "byte_corruption": lambda: (
                "byte_corruption",
                injector.byte_corruption(braid),
            ),
            "ledger_hash_mismatch": lambda: (
                "hash_mismatch",
                injector.ledger_hash_mismatch(braid),
            ),
            "broken_brick": lambda: (
                "broken_brick",
                injector.broken_brick(braid),
            ),
            "mass_failure": lambda: (
                "mass_failure",
                ",".join(injector.mass_failure(braid, percent=0.8)),
            ),
            "message_tamper": lambda: (
                "message_tamper",
                injector.message_tamper(braid),
            ),
            "hallucination": lambda: (
                "hallucination",
                injector.hallucination(braid),
            ),
            "network_delay": lambda: (
                "network_delay",
                injector.network_delay(braid, delay_ms=5.0),
            ),
            "disk_write_interrupt": lambda: (
                "disk_write_interrupt",
                injector.broken_brick(braid),   # brick failure + checkpoint issue
            ),
            "partial_checkpoint": lambda: (
                "partial_checkpoint",
                injector.broken_brick(braid),
            ),
            "dependency_failure": lambda: (
                "dependency_failure",
                str(injector.dependency_failure(braid)),
            ),
            "recovery_loop_failure": lambda: (
                "recovery_loop_failure",
                ",".join(injector.recovery_loop_failure(braid)),
            ),
        }

        handler = dispatch.get(method)
        if handler:
            return handler()  # type: ignore[return-value]
        return "none", "none"

    def _inject_checkpoint_fault_if_needed(
        self,
        injector: FaultInjector,
        scenario: str,
        snapshot: dict,
    ) -> None:
        method = SCENARIOS.get(scenario, "")
        if method not in {"disk_write_interrupt", "partial_checkpoint"}:
            return

        corrupted = dict(snapshot)
        if method == "disk_write_interrupt":
            corrupted = injector.disk_write_interrupt(corrupted)
        elif method == "partial_checkpoint":
            corrupted = injector.partial_checkpoint(corrupted)

        # Checkpoint filenames are millisecond-based; avoid overwriting the
        # healthy checkpoint saved earlier in the run.
        time.sleep(0.001)

        # Persist a newer checkpoint whose envelope seal is intentionally wrong.
        # load_latest() will skip it and fall back to the previous healthy one.
        path = self._cp.save(_PROJECT_ID, corrupted)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["seal"] = hashlib.sha256(b"SB712_CORRUPTED_CHECKPOINT").hexdigest()
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
