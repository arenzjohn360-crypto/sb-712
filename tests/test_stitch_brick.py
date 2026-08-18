"""
tests/test_stitch_brick.py
==========================
Fault-injection pytest suite for SB-712 Stitch Brick.

Each test exercises one end-to-end cycle:
  inject → detect → quarantine → restore → verify ledger

Tests are fully deterministic (fixed seeds) so they produce identical results
on any machine.  Rerunning a failing test with the same seed will reproduce the
exact failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make src/ importable when pytest is run from the repo root
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from stitch_brick import (
    BraidOrchestrator,
    BrickState,
    FaultInjector,
    ProofGenerator,
    ProtectedSpine,
    SpineVerificationError,
    StrandChannel,
    ValidationRunner,
    VerificationGate,
)
from stitch_brick.brick import BrickModule, BrickOutput
from stitch_brick.disk_io import CheckpointDiskManager
from stitch_brick.metrics import MetricsCollector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_runner(tmp_path: Path) -> ValidationRunner:
    """ValidationRunner isolated to a temp directory."""
    return ValidationRunner(root=tmp_path)


@pytest.fixture()
def tmp_proof(tmp_path: Path) -> ProofGenerator:
    return ProofGenerator(root=tmp_path)


# ---------------------------------------------------------------------------
# BrickModule unit tests
# ---------------------------------------------------------------------------

class TestBrickModule:
    def test_healthy_output_seal_valid(self) -> None:
        brick = BrickModule("b-001", seed=1)
        out = brick.compute(b"test_input")
        assert out.verify_seal(), "Healthy brick must produce a valid seal"

    def test_byte_corruption_seal_mismatch(self) -> None:
        brick = BrickModule("b-002", seed=2)
        brick.inject_fault("byte_corruption")
        out = brick.compute(b"test_input")
        assert not out.verify_seal(), "Corrupted output must have a bad seal"
        assert out.fault_injected

    def test_hash_mismatch_seal_fails(self) -> None:
        brick = BrickModule("b-003", seed=3)
        brick.inject_fault("hash_mismatch")
        out = brick.compute(b"test_input")
        assert not out.verify_seal(), "Hash-mismatch fault must produce invalid seal"

    def test_crash_raises_on_compute(self) -> None:
        brick = BrickModule("b-004", seed=4)
        brick.inject_fault("crash")
        with pytest.raises(RuntimeError):
            brick.compute(b"test_input")
        assert brick.state == BrickState.FAILED

    def test_hallucinate_seal_valid_but_semantically_wrong(self) -> None:
        brick = BrickModule("b-005", seed=5)
        brick.inject_fault("hallucinate")
        out = brick.compute(b"test_input")
        # Hallucinated seal is self-consistent (hash passes)
        assert out.verify_seal(), "Hallucinated output should have a valid seal"
        # But the payload doesn't match the deterministic computation
        import hashlib
        expected = hashlib.sha256(b"test_input" + b"b-005").digest()
        assert out.payload != expected, "Hallucinated payload must differ from expected"

    def test_clear_fault_restores_to_recovering(self) -> None:
        brick = BrickModule("b-006", seed=6)
        brick.inject_fault("byte_corruption")
        brick.clear_fault()
        assert brick.state == BrickState.RECOVERING

    def test_mark_healthy_after_recovery(self) -> None:
        brick = BrickModule("b-007", seed=7)
        brick.inject_fault("byte_corruption")
        brick.clear_fault()
        brick.mark_healthy()
        assert brick.state == BrickState.HEALTHY
        out = brick.compute(b"check")
        assert out.verify_seal()


# ---------------------------------------------------------------------------
# StrandChannel unit tests
# ---------------------------------------------------------------------------

class TestStrandChannel:
    def test_clean_message_seal_valid(self) -> None:
        strand = StrandChannel("brick-0", "collector")
        strand.send(b"hello")
        msg = strand.receive()
        assert msg is not None
        assert msg.verify_seal()

    def test_tampered_message_seal_invalid(self) -> None:
        strand = StrandChannel("brick-0", "collector")
        strand.inject_tamper()
        strand.send(b"hello")
        msg = strand.receive()
        assert msg is not None
        assert not msg.verify_seal(), "Tampered message must fail seal check"
        assert msg.tampered

    def test_empty_queue_returns_none(self) -> None:
        strand = StrandChannel("a", "b")
        assert strand.receive() is None


# ---------------------------------------------------------------------------
# ProtectedSpine unit tests
# ---------------------------------------------------------------------------

class TestProtectedSpine:
    def test_propose_valid_state_commits(self) -> None:
        spine = ProtectedSpine()
        entry = spine.propose_state("k1", b"data", structural_ok=True, behavioral_ok=True)
        assert entry.sequence == 1
        assert spine.entry_count() == 1

    def test_structural_failure_rejected(self) -> None:
        spine = ProtectedSpine()
        with pytest.raises(SpineVerificationError, match="structural"):
            spine.propose_state("k1", b"data", structural_ok=False, behavioral_ok=True)

    def test_behavioral_failure_rejected(self) -> None:
        spine = ProtectedSpine()
        with pytest.raises(SpineVerificationError, match="behavioral"):
            spine.propose_state("k1", b"data", structural_ok=True, behavioral_ok=False)

    def test_chain_integrity_after_multiple_entries(self) -> None:
        spine = ProtectedSpine()
        for i in range(5):
            spine.propose_state(f"k{i}", f"data{i}".encode(), True, True)
        assert spine.verify_integrity()

    def test_chain_seal_changes_with_each_commit(self) -> None:
        spine = ProtectedSpine()
        seal0 = spine.chain_seal()
        spine.propose_state("k1", b"first", True, True)
        seal1 = spine.chain_seal()
        spine.propose_state("k2", b"second", True, True)
        seal2 = spine.chain_seal()
        assert seal0 != seal1 != seal2


# ---------------------------------------------------------------------------
# VerificationGate unit tests
# ---------------------------------------------------------------------------

class TestVerificationGate:
    def test_valid_output_passes(self) -> None:
        brick = BrickModule("g-001", seed=0)
        out = brick.compute(b"input")
        gate = VerificationGate()
        s, h, sem, reason = gate.verify(out, expected_input=b"input")
        assert s and h and sem, f"Expected all gates to pass, reason: {reason}"

    def test_corrupted_output_fails_hash(self) -> None:
        brick = BrickModule("g-002", seed=0)
        brick.inject_fault("byte_corruption")
        out = brick.compute(b"input")
        gate = VerificationGate()
        _, hash_ok, _, _ = gate.verify(out, expected_input=b"input")
        assert not hash_ok

    def test_hallucinated_output_fails_semantic(self) -> None:
        brick = BrickModule("g-003", seed=99)
        brick.inject_fault("hallucinate")
        out = brick.compute(b"input")
        gate = VerificationGate()
        s, h, sem, reason = gate.verify(out, expected_input=b"input")
        assert s and h           # structural + hash pass for hallucination
        assert not sem, f"Semantic check should fail: {reason}"


# ---------------------------------------------------------------------------
# BraidOrchestrator unit tests
# ---------------------------------------------------------------------------

class TestBraidOrchestrator:
    def test_healthy_round_commits_all_bricks(self) -> None:
        braid = BraidOrchestrator(brick_count=5, seed=0)
        result = braid.process_round(b"input")
        assert result["bricks_verified"] == 5
        assert result["bricks_failed"] == 0
        assert braid.spine.verify_integrity()

    def test_failed_brick_is_skipped(self) -> None:
        braid = BraidOrchestrator(brick_count=5, seed=0)
        braid.brick("brick-002").inject_fault("crash")
        result = braid.process_round(b"input")
        # Failed brick is skipped, not counted as attempted
        assert result["bricks_verified"] == 4

    def test_corrupt_brick_detected_not_committed(self) -> None:
        braid = BraidOrchestrator(brick_count=5, seed=0)
        braid.brick("brick-001").inject_fault("byte_corruption")
        result = braid.process_round(b"input")
        assert result["bricks_failed"] >= 1
        assert result["bricks_verified"] == 4

    def test_hallucinated_brick_caught_by_semantic_check(self) -> None:
        braid = BraidOrchestrator(brick_count=5, seed=42)
        braid.brick("brick-003").inject_fault("hallucinate")
        result = braid.process_round(b"data")
        assert result["bricks_failed"] >= 1, (
            "Hallucinated output must fail the semantic check"
        )
        failures = result["verification_failures"]
        reasons = " ".join(f.get("reason", "") for f in failures)
        assert "semantic" in reasons, f"Expected 'semantic' in failure reason, got: {reasons}"


# ---------------------------------------------------------------------------
# FaultInjector unit tests
# ---------------------------------------------------------------------------

class TestFaultInjector:
    def test_mass_failure_80_percent(self) -> None:
        braid = BraidOrchestrator(brick_count=10, seed=0)
        injector = FaultInjector(seed=0)
        failed_ids = injector.mass_failure(braid, percent=0.8)
        assert len(failed_ids) == 8
        # Verify bricks are actually failed
        for bid in failed_ids:
            assert braid.brick(bid).state == BrickState.FAILED

    def test_dependency_failure_cascade(self) -> None:
        braid = BraidOrchestrator(brick_count=5, seed=0)
        injector = FaultInjector(seed=0)
        injector.dependency_failure(braid)
        assert braid.brick("brick-000").state == BrickState.FAILED
        assert braid.brick("brick-001").state == BrickState.DEGRADED

    def test_partial_checkpoint_removes_key(self) -> None:
        snapshot = {"sequence": 1, "chain_seal": "abc", "entries": []}
        injector = FaultInjector(seed=0)
        corrupted = injector.partial_checkpoint(snapshot)
        assert len(corrupted) < len(snapshot)

    def test_disk_write_interrupt_truncates_entries(self) -> None:
        snapshot = {"entries": [{"seq": i} for i in range(10)]}
        injector = FaultInjector(seed=0)
        truncated = injector.disk_write_interrupt(snapshot)
        assert len(truncated["entries"]) < 10

    def test_same_seed_same_target(self) -> None:
        """Identical seeds must produce identical fault targets."""
        braid_a = BraidOrchestrator(brick_count=10, seed=7)
        braid_b = BraidOrchestrator(brick_count=10, seed=7)
        t_a = FaultInjector(seed=42).byte_corruption(braid_a)
        t_b = FaultInjector(seed=42).byte_corruption(braid_b)
        assert t_a == t_b, "Same seed must select same target"


# ---------------------------------------------------------------------------
# End-to-end scenario tests (ValidationRunner)
# ---------------------------------------------------------------------------

class TestValidationRunner:
    """
    These are the core evidence tests.  Each one runs one complete
    inject → detect → quarantine → restore → verify cycle.
    """

    # Helper: assert a result is fully passing
    @staticmethod
    def _assert_pass(result, scenario: str) -> None:
        assert result.detected, (
            f"{scenario}: fault was not detected. reason={result.failure_reason!r}"
        )
        assert result.quarantined, f"{scenario}: fault was not quarantined"
        assert result.recovered, (
            f"{scenario}: did not recover. reason={result.failure_reason!r}"
        )
        assert result.ledger_intact, f"{scenario}: ledger chain not intact after recovery"
        assert result.seal_before == result.seal_after, (
            f"{scenario}: seal mismatch: before={result.seal_before[:16]}… "
            f"after={result.seal_after[:16]}…"
        )

    def test_byte_corruption(self, tmp_runner: ValidationRunner) -> None:
        result = tmp_runner.run_single_test("byte_corruption", test_id=0, seed=0)
        self._assert_pass(result, "byte_corruption")

    def test_ledger_hash_mismatch(self, tmp_runner: ValidationRunner) -> None:
        result = tmp_runner.run_single_test("ledger_hash_mismatch", test_id=0, seed=1)
        self._assert_pass(result, "ledger_hash_mismatch")

    def test_ledger_drift_alias(self, tmp_runner: ValidationRunner) -> None:
        result = tmp_runner.run_single_test("ledger_drift", test_id=0, seed=2)
        self._assert_pass(result, "ledger_drift")

    def test_broken_brick(self, tmp_runner: ValidationRunner) -> None:
        result = tmp_runner.run_single_test("broken_brick", test_id=0, seed=3)
        self._assert_pass(result, "broken_brick")

    def test_80_percent_brick_failure(self, tmp_runner: ValidationRunner) -> None:
        result = tmp_runner.run_single_test(
            "80_percent_brick_failure", test_id=0, seed=4
        )
        self._assert_pass(result, "80_percent_brick_failure")

    def test_message_tamper(self, tmp_runner: ValidationRunner) -> None:
        result = tmp_runner.run_single_test("message_tamper", test_id=0, seed=5)
        self._assert_pass(result, "message_tamper")

    def test_hallucination_containment(self, tmp_runner: ValidationRunner) -> None:
        result = tmp_runner.run_single_test(
            "hallucination_containment", test_id=0, seed=6
        )
        self._assert_pass(result, "hallucination_containment")

    def test_network_delay(self, tmp_runner: ValidationRunner) -> None:
        result = tmp_runner.run_single_test("network_delay", test_id=0, seed=7)
        self._assert_pass(result, "network_delay")

    @pytest.mark.parametrize("scenario", ["disk_write_interrupt", "partial_checkpoint"])
    def test_checkpoint_faults_use_fallback_checkpoint(
        self, tmp_path: Path, scenario: str
    ) -> None:
        runner = ValidationRunner(root=tmp_path)
        result = runner.run_single_test(scenario, test_id=0, seed=21)
        self._assert_pass(result, scenario)

        cp = CheckpointDiskManager(tmp_path)
        files = sorted((tmp_path / "checkpoints").glob("sb712-validation_*.json"))
        assert len(files) >= 2, f"{scenario}: expected healthy + corrupted checkpoints"

        latest_raw = cp.load_latest_raw("sb712-validation")
        latest_verified = cp.load_latest("sb712-validation")
        assert latest_raw is not None
        assert latest_verified is not None
        assert latest_raw != latest_verified, (
            f"{scenario}: latest checkpoint should be corrupted and skipped"
        )

    def test_dependency_failure(self, tmp_runner: ValidationRunner) -> None:
        result = tmp_runner.run_single_test("dependency_failure", test_id=0, seed=8)
        self._assert_pass(result, "dependency_failure")

    def test_recovery_loop_failure(self, tmp_runner: ValidationRunner) -> None:
        # This scenario is intentionally severe — all bricks fail.
        # Detection and quarantine must still occur even if recovery is partial.
        result = tmp_runner.run_single_test(
            "recovery_loop_failure", test_id=0, seed=9
        )
        assert result.detected, "recovery_loop_failure: fault must be detected"
        assert result.quarantined, "recovery_loop_failure: fault must be quarantined"
        # Recovery succeeds because we restore from checkpoint to a clean braid
        assert result.recovered, (
            f"recovery_loop_failure: expected recovery via checkpoint, "
            f"got failure_reason={result.failure_reason!r}"
        )
        assert result.ledger_intact

    def test_reproducibility_same_seed(self, tmp_path: Path) -> None:
        """Two runs with identical seeds must produce identical seals."""
        r1 = ValidationRunner(root=tmp_path / "run1").run_single_test(
            "byte_corruption", test_id=0, seed=99
        )
        r2 = ValidationRunner(root=tmp_path / "run2").run_single_test(
            "byte_corruption", test_id=0, seed=99
        )
        assert r1.seal_before == r2.seal_before
        assert r1.seal_after == r2.seal_after
        assert r1.fault_target == r2.fault_target

    def test_batch_100_byte_corruption(self, tmp_runner: ValidationRunner) -> None:
        metrics = tmp_runner.run_batch(100, "byte_corruption", base_seed=0)
        assert metrics.total_tests == 100
        assert metrics.passed == 100, (
            f"Expected 100/100 pass, got {metrics.passed}/100. "
            f"First failure: "
            + (
                metrics.run_results[
                    next(i for i, r in enumerate(metrics.run_results) if not r.passed)
                ].failure_reason
                if any(not r.passed for r in metrics.run_results)
                else "none"
            )
        )
        assert metrics.false_negatives == 0
        assert metrics.ledger_seal_mismatches == 0


# ---------------------------------------------------------------------------
# ProofGenerator integration test
# ---------------------------------------------------------------------------

class TestProofGenerator:
    def test_generates_all_report_files(
        self, tmp_runner: ValidationRunner, tmp_proof: ProofGenerator
    ) -> None:
        metrics = tmp_runner.run_batch(5, "byte_corruption", base_seed=0)
        artefacts = tmp_proof.generate_all(metrics)

        for label, path in artefacts.items():
            assert path.exists(), f"{label} file not created: {path}"
            assert path.stat().st_size > 0, f"{label} file is empty"

    def test_json_report_structure(
        self, tmp_runner: ValidationRunner, tmp_proof: ProofGenerator
    ) -> None:
        import json
        metrics = tmp_runner.run_batch(3, "broken_brick", base_seed=10)
        artefacts = tmp_proof.generate_all(metrics)
        data = json.loads(artefacts["json_report"].read_text())
        assert "summary" in data
        assert "run_results" in data
        assert data["summary"]["total_tests"] == 3

    def test_failure_analysis_only_contains_failures(
        self, tmp_runner: ValidationRunner, tmp_proof: ProofGenerator
    ) -> None:
        import json
        metrics = tmp_runner.run_batch(5, "byte_corruption", base_seed=20)
        artefacts = tmp_proof.generate_all(metrics)
        data = json.loads(artefacts["failure_analysis"].read_text())
        for f in data["failures"]:
            assert not f["passed"], "failure_analysis must only contain failed runs"
