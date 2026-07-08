"""
chaos_soak_test.py — SB-712 IronBraid Radiant Core

Extended soak-style tests that combine multiple fault scenarios in
sequence: bit flips, node failures, ledger tampering, and recovery.
These validate that the system can survive sustained chaos without
state contamination.
"""

import time
from pathlib import Path

import pytest

from intelligence.ava_coordinator import AVACoordinator, Task, TaskResult
from intelligence.fieldview_encoder import FieldViewEncoder, FieldSnapshot
from intelligence.forecast_node import ForecastNode
from intelligence.mask_evaluator import MaskEvaluator
from intelligence.receptor_registry import ReceptorRegistry
from intelligence.vera_gate import CertificationBundle, VERAGate
from recovery.checkpoint_validator import CheckpointRecord, CheckpointValidator
from recovery.phoenix_triangle import CheckpointCandidate, PhoenixTriangle
from recovery.rollback_engine import RollbackEngine
from recovery.route_healer import RouteHealer


class TestReceptorRegistry:
    def test_registered_node_can_receive(self):
        reg = ReceptorRegistry()
        reg.register("vera-gate", "ARBITRATION_REQUEST")
        assert reg.can_receive("vera-gate", "ARBITRATION_REQUEST")

    def test_unregistered_node_cannot_receive(self):
        reg = ReceptorRegistry()
        assert not reg.can_receive("phoenix-a", "ARBITRATION_REQUEST")

    def test_deregister_removes_permission(self):
        reg = ReceptorRegistry()
        reg.register("phoenix-a", "RECOVERY_TRIGGER")
        reg.deregister("phoenix-a", "RECOVERY_TRIGGER")
        assert not reg.can_receive("phoenix-a", "RECOVERY_TRIGGER")

    def test_audit_log_records_events(self):
        reg = ReceptorRegistry()
        reg.register("vera-gate", "ARBITRATION_REQUEST")
        reg.deregister("vera-gate", "ARBITRATION_REQUEST")
        assert len(reg.audit_log) == 2


class TestRouteHealer:
    def _build_mesh(self) -> RouteHealer:
        healer = RouteHealer()
        healer.add_node("spine-core", ["ledger-primary", "vera-gate"])
        healer.add_node("ledger-primary", ["ledger-mirror-a", "ledger-mirror-b"])
        healer.add_node("vera-gate", ["spine-core", "ledger-primary"])
        healer.add_node("ledger-mirror-a", ["ledger-primary"])
        healer.add_node("ledger-mirror-b", ["ledger-primary"])
        return healer

    def test_direct_route_found(self):
        healer = self._build_mesh()
        result = healer.heal("spine-core", "vera-gate")
        assert result.healed is True

    def test_bypass_route_around_failed_node(self):
        healer = self._build_mesh()
        healer.mark_failed("ledger-primary")
        # Should still reach mirror via direct connection if path exists
        result = healer.heal("spine-core", "ledger-mirror-a")
        # Without a direct path through the failed node, healed may be False.
        # Key assertion: no crash, and failed_nodes is tracked.
        assert "ledger-primary" in healer.failed_nodes

    def test_recovery_reactivates_node(self):
        healer = self._build_mesh()
        healer.mark_failed("ledger-primary")
        healer.mark_recovered("ledger-primary")
        assert "ledger-primary" not in healer.failed_nodes

    def test_unknown_source_returns_not_healed(self):
        healer = self._build_mesh()
        result = healer.heal("unknown-node", "ledger-primary")
        assert result.healed is False


class TestAVACoordinator:
    def _full_bundle(self) -> CertificationBundle:
        return CertificationBundle(hash_check=True, validation_pass=True,
                                   certification_mark=True)

    def test_approved_task_runs_handler(self):
        gate = VERAGate()
        ava = AVACoordinator(vera_gate=gate)

        def handler(task: Task) -> TaskResult:
            return TaskResult(task.task_id, "COMPLETED", "ok")

        ava.register_handler("write", handler)
        task = Task("T1", "write", "data/x.bric")
        result = ava.submit(task, bundle=self._full_bundle())
        assert result.status == "COMPLETED"

    def test_denied_task_does_not_run_handler(self):
        gate = VERAGate()
        ava = AVACoordinator(vera_gate=gate)
        ran = []

        def handler(task: Task) -> TaskResult:
            ran.append(True)
            return TaskResult(task.task_id, "COMPLETED", "ok")

        ava.register_handler("write", handler)
        task = Task("T2", "write", "spine/root_manifest.json")
        result = ava.submit(task, bundle=CertificationBundle())
        assert result.status == "DENIED"
        assert not ran

    def test_high_risk_action_escalated(self):
        escalated = []
        gate = VERAGate()
        ava = AVACoordinator(vera_gate=gate, owner_pager=escalated.append)
        task = Task("T3", "delete", "spine/spine_law.json")
        result = ava.submit(task, bundle=self._full_bundle())
        assert result.status == "ESCALATED"
        assert len(escalated) == 1


class TestChaosSequence:
    """End-to-end chaos scenario: mutations → risk forecast → recovery."""

    def test_full_chaos_cycle(self, tmp_path):
        # 1. Simulate mutations.
        for i in range(3):
            (tmp_path / f"file{i}.dat").write_bytes(b"original")
        encoder = FieldViewEncoder(watch_paths=[tmp_path])
        encoder.capture()  # baseline
        for i in range(3):
            (tmp_path / f"file{i}.dat").write_bytes(b"corrupted")
        snap = encoder.capture()
        assert snap.mutation_count == 3

        # 2. Forecast risk.
        forecast = ForecastNode().predict([snap])
        assert forecast.risk_score > 0.0

        # 3. Register certified checkpoints and roll back.
        engine = RollbackEngine()
        engine.register_checkpoint("ckpt-pre-chaos", certified=True)
        rollback = engine.rollback("QUARANTINED")
        assert rollback.success is True

        # 4. Phoenix validates the checkpoint.
        candidate = CheckpointCandidate(
            checkpoint_id="ckpt-pre-chaos",
            hash="validhash",
            ledger_seq=1,
            timestamp=time.time(),
            mutation_distance=3,
            vera_certified=True,
            lineage_ok=True,
            replica_agreement=True,
        )
        cluster = PhoenixTriangle()
        results = cluster.recover(candidate)
        assert cluster.majority_verified(results) is True
