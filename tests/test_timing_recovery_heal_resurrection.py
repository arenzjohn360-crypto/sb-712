"""
SB-712 Timing tests: recovery, heal, and resurrection — fast and slow paths.

Fast time  = single/minimal workload; must finish well under 1 second.
Slow time  = bulk/stress workload; must finish within a generous but bounded SLA.

These tests assert *correctness* (the operations succeed) AND *time bounds*
(the operations do not hang or degrade unexpectedly).
"""

import os
import time
import pytest

from sb_712.checkpoint import Checkpoint, CheckpointRegistry, CheckpointStatus
from sb_712.incident import IncidentStudyRecord, IncidentType, SourceType, Severity
from sb_712.recovery import (
    RecoveryOrchestrator,
    RecoveryMethod,
    MAX_CONVOY_ATTEMPTS,
)
from sb688 import BlockStore, IntegrityChecker

# ---------------------------------------------------------------------------
# SLA constants (seconds)
# ---------------------------------------------------------------------------

# A single clean recovery convoy must complete in well under 1 s.
RECOVERY_FAST_SLA_S = 1.0

# A worst-case convoy (3 retries → rollback with 50-checkpoint registry) must
# complete in under 5 s.
RECOVERY_SLOW_SLA_S = 5.0

# Healing a single corrupt block must be near-instant (< 0.5 s).
HEAL_FAST_SLA_S = 0.5

# Healing 500 corrupt blocks (bulk scan-and-heal) must finish in under 10 s.
HEAL_SLOW_SLA_S = 10.0

# Rolling back from a single-checkpoint registry must be near-instant.
RESURRECTION_FAST_SLA_S = 0.5

# Rolling back from a 100-checkpoint registry must finish in under 3 s.
RESURRECTION_SLOW_SLA_S = 3.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry(project_id: str = "PRJ-001", n_checkpoints: int = 1) -> CheckpointRegistry:
    registry = CheckpointRegistry()
    for _ in range(n_checkpoints):
        registry.add_checkpoint(
            Checkpoint(
                project_id=project_id,
                status=CheckpointStatus.HEALTHY,
                certified=True,
            )
        )
    return registry


def _make_incident(**kwargs) -> IncidentStudyRecord:
    """Return a clean incident (all convoy stages pass) by default."""
    defaults = dict(
        project_id="PRJ-001",
        incident_type=IncidentType.FILE_CORRUPTION,
        source=SourceType.CLIENT_UPLOAD,
        severity=Severity.LOW,
        repair_action="Replaced corrupted file",
        truth_verified=True,
        certification_result="Clean",
        return_check_result="Stable",
        damage_is_local=True,
    )
    defaults.update(kwargs)
    return IncidentStudyRecord(**defaults)


# ---------------------------------------------------------------------------
# Recovery timing — fast path
# ---------------------------------------------------------------------------

class TestRecoveryTimingFast:
    """A single convoy with a clean incident must complete quickly."""

    def test_recovery_fast_succeeds(self):
        orch = RecoveryOrchestrator(_make_registry())
        result = orch.recover(_make_incident())
        assert result.success is True
        assert result.method_used == RecoveryMethod.CONVOY

    def test_recovery_fast_within_sla(self):
        orch = RecoveryOrchestrator(_make_registry())
        incident = _make_incident()
        start = time.perf_counter()
        result = orch.recover(incident)
        elapsed = time.perf_counter() - start
        assert result.success is True
        assert elapsed < RECOVERY_FAST_SLA_S, (
            f"Fast recovery took {elapsed:.3f}s, expected < {RECOVERY_FAST_SLA_S}s"
        )

    def test_recovery_fast_convoy_stages_all_pass(self):
        orch = RecoveryOrchestrator(_make_registry())
        result = orch.recover(_make_incident())
        assert result.convoy_result is not None
        for stage_result in result.convoy_result.forward_stages:
            assert stage_result.success is True

    def test_recovery_fast_return_check_closes(self):
        orch = RecoveryOrchestrator(_make_registry())
        result = orch.recover(_make_incident())
        rc = result.convoy_result.return_check
        assert rc is not None
        assert rc.success is True

    def test_recovery_fast_single_attempt(self):
        orch = RecoveryOrchestrator(_make_registry())
        result = orch.recover(_make_incident())
        assert result.convoy_result.convoy_attempts == 1


# ---------------------------------------------------------------------------
# Recovery timing — slow path
# ---------------------------------------------------------------------------

class TestRecoveryTimingSlow:
    """
    Worst-case: convoy retries MAX_CONVOY_ATTEMPTS times (hunter rescan keeps
    reopening) then falls back to rollback against a 50-checkpoint registry.
    """

    def _slow_incident(self) -> IncidentStudyRecord:
        return _make_incident(hunter_rescan_outcome="problem_still_active")

    def test_recovery_slow_exhausts_convoy_then_rollbacks(self):
        orch = RecoveryOrchestrator(_make_registry(n_checkpoints=50))
        result = orch.recover(self._slow_incident())
        assert result.method_used == RecoveryMethod.ROLLBACK
        assert result.convoy_result is not None
        assert result.convoy_result.convoy_attempts == MAX_CONVOY_ATTEMPTS

    def test_recovery_slow_rollback_succeeds_with_large_registry(self):
        orch = RecoveryOrchestrator(_make_registry(n_checkpoints=50))
        result = orch.recover(self._slow_incident())
        assert result.rollback_result is not None
        assert result.rollback_result.success is True

    def test_recovery_slow_within_sla(self):
        orch = RecoveryOrchestrator(_make_registry(n_checkpoints=50))
        incident = self._slow_incident()
        start = time.perf_counter()
        result = orch.recover(incident)
        elapsed = time.perf_counter() - start
        assert result.method_used == RecoveryMethod.ROLLBACK
        assert elapsed < RECOVERY_SLOW_SLA_S, (
            f"Slow recovery took {elapsed:.3f}s, expected < {RECOVERY_SLOW_SLA_S}s"
        )

    @pytest.mark.parametrize("outcome", [
        "problem_still_active",
        "new_damage_found",
        "repeat_attack",
    ])
    def test_recovery_slow_all_reopen_outcomes_exhaust_within_sla(self, outcome):
        orch = RecoveryOrchestrator(_make_registry(n_checkpoints=10))
        incident = _make_incident(hunter_rescan_outcome=outcome)
        start = time.perf_counter()
        result = orch.recover(incident)
        elapsed = time.perf_counter() - start
        assert result.method_used == RecoveryMethod.ROLLBACK
        assert elapsed < RECOVERY_SLOW_SLA_S, (
            f"Slow recovery ({outcome}) took {elapsed:.3f}s, expected < {RECOVERY_SLOW_SLA_S}s"
        )


# ---------------------------------------------------------------------------
# Heal timing — fast path
# ---------------------------------------------------------------------------

class TestHealTimingFast:
    """Healing a single corrupt block must complete near-instantly."""

    def _stores_with_single_corrupt(self):
        primary = BlockStore()
        backup = BlockStore()
        data = os.urandom(64)
        primary.put("k0", data)
        backup.put("k0", data)
        primary.inject_bit_flip("k0", 0)
        return primary, backup

    def test_heal_fast_removes_corruption(self):
        primary, backup = self._stores_with_single_corrupt()
        checker = IntegrityChecker(primary, repair_source=backup)
        checker.scan_and_heal()
        assert primary.corrupt_keys() == []

    def test_heal_fast_within_sla(self):
        primary, backup = self._stores_with_single_corrupt()
        checker = IntegrityChecker(primary, repair_source=backup)
        start = time.perf_counter()
        checker.scan_and_heal()
        elapsed = time.perf_counter() - start
        assert elapsed < HEAL_FAST_SLA_S, (
            f"Fast heal took {elapsed:.3f}s, expected < {HEAL_FAST_SLA_S}s"
        )

    def test_heal_fast_does_not_corrupt_data(self):
        primary = BlockStore()
        backup = BlockStore()
        original = os.urandom(64)
        primary.put("k0", original)
        backup.put("k0", original)
        primary.inject_bit_flip("k0", 0)
        checker = IntegrityChecker(primary, repair_source=backup)
        checker.scan_and_heal()
        assert primary.get("k0") == original

    def test_heal_fast_audit_trail_present(self):
        primary, backup = self._stores_with_single_corrupt()
        checker = IntegrityChecker(primary, repair_source=backup)
        checker.scan_and_heal()
        event_types = {e.event_type for e in checker.audit_log}
        assert "corruption_detected" in event_types
        assert "repair_success" in event_types


# ---------------------------------------------------------------------------
# Heal timing — slow path
# ---------------------------------------------------------------------------

class TestHealTimingSlow:
    """Healing 500 corrupt blocks (bulk scan-and-heal) must finish within SLA."""

    _N_BLOCKS = 500
    _CORRUPT_STEP = 5  # every 5th block is corrupted

    def _stores_with_bulk_corrupt(self):
        primary = BlockStore()
        backup = BlockStore()
        for i in range(self._N_BLOCKS):
            data = os.urandom(32)
            primary.put(f"k{i}", data)
            backup.put(f"k{i}", data)
        for i in range(0, self._N_BLOCKS, self._CORRUPT_STEP):
            primary.inject_bit_flip(f"k{i}", 0)
        return primary, backup

    def test_heal_slow_removes_all_corruption(self):
        primary, backup = self._stores_with_bulk_corrupt()
        checker = IntegrityChecker(primary, repair_source=backup)
        checker.scan_and_heal()
        assert primary.corrupt_keys() == []

    def test_heal_slow_within_sla(self):
        primary, backup = self._stores_with_bulk_corrupt()
        checker = IntegrityChecker(primary, repair_source=backup)
        start = time.perf_counter()
        checker.scan_and_heal()
        elapsed = time.perf_counter() - start
        assert elapsed < HEAL_SLOW_SLA_S, (
            f"Slow heal took {elapsed:.3f}s, expected < {HEAL_SLOW_SLA_S}s"
        )

    def test_heal_slow_healthy_blocks_unchanged(self):
        primary = BlockStore()
        backup = BlockStore()
        originals = {}
        for i in range(self._N_BLOCKS):
            data = os.urandom(32)
            originals[f"k{i}"] = data
            primary.put(f"k{i}", data)
            backup.put(f"k{i}", data)
        for i in range(0, self._N_BLOCKS, self._CORRUPT_STEP):
            primary.inject_bit_flip(f"k{i}", 0)
        checker = IntegrityChecker(primary, repair_source=backup)
        checker.scan_and_heal()
        # Every block must equal the original after bulk heal.
        for k, v in originals.items():
            assert primary.get(k) == v

    def test_heal_slow_audit_chain_valid_after_bulk(self):
        primary, backup = self._stores_with_bulk_corrupt()
        checker = IntegrityChecker(primary, repair_source=backup)
        checker.scan_and_heal()
        assert checker.verify_audit_chain()


# ---------------------------------------------------------------------------
# Resurrection (rollback) timing — fast path
# ---------------------------------------------------------------------------

class TestResurrectionTimingFast:
    """Rolling back from a single-checkpoint registry must be near-instant."""

    def test_resurrection_fast_succeeds(self):
        registry = _make_registry(n_checkpoints=1)
        result = registry.rollback("PRJ-001", reason="Fast resurrection test")
        assert result.success is True
        assert result.checkpoint_id is not None

    def test_resurrection_fast_within_sla(self):
        registry = _make_registry(n_checkpoints=1)
        start = time.perf_counter()
        result = registry.rollback("PRJ-001", reason="Fast resurrection test")
        elapsed = time.perf_counter() - start
        assert result.success is True
        assert elapsed < RESURRECTION_FAST_SLA_S, (
            f"Fast resurrection took {elapsed:.3f}s, expected < {RESURRECTION_FAST_SLA_S}s"
        )

    def test_resurrection_fast_returns_latest_healthy_checkpoint(self):
        registry = _make_registry(n_checkpoints=1)
        latest = registry.get_last_healthy_certified("PRJ-001")
        result = registry.rollback("PRJ-001")
        assert result.checkpoint_id == latest.checkpoint_id

    def test_resurrection_fast_fails_gracefully_when_no_checkpoint(self):
        empty_registry = CheckpointRegistry()
        result = empty_registry.rollback("PRJ-MISSING", reason="Should fail gracefully")
        assert result.success is False
        assert result.checkpoint_id is None

    def test_resurrection_fast_via_orchestrator(self):
        """Orchestrator-driven rollback on a trigger incident completes quickly."""
        registry = _make_registry(n_checkpoints=1)
        orch = RecoveryOrchestrator(registry)
        incident = _make_incident(ledger_corrupted=True)
        start = time.perf_counter()
        result = orch.recover(incident)
        elapsed = time.perf_counter() - start
        assert result.method_used == RecoveryMethod.ROLLBACK
        assert result.success is True
        assert elapsed < RESURRECTION_FAST_SLA_S, (
            f"Fast orchestrator resurrection took {elapsed:.3f}s, "
            f"expected < {RESURRECTION_FAST_SLA_S}s"
        )


# ---------------------------------------------------------------------------
# Resurrection (rollback) timing — slow path
# ---------------------------------------------------------------------------

class TestResurrectionTimingSlow:
    """Rolling back from a 100-checkpoint registry must finish within SLA."""

    _N_CHECKPOINTS = 100

    def test_resurrection_slow_picks_latest_healthy(self):
        registry = _make_registry(n_checkpoints=self._N_CHECKPOINTS)
        latest = registry.get_last_healthy_certified("PRJ-001")
        result = registry.rollback("PRJ-001")
        assert result.success is True
        assert result.checkpoint_id == latest.checkpoint_id

    def test_resurrection_slow_within_sla(self):
        registry = _make_registry(n_checkpoints=self._N_CHECKPOINTS)
        start = time.perf_counter()
        result = registry.rollback("PRJ-001")
        elapsed = time.perf_counter() - start
        assert result.success is True
        assert elapsed < RESURRECTION_SLOW_SLA_S, (
            f"Slow resurrection took {elapsed:.3f}s, expected < {RESURRECTION_SLOW_SLA_S}s"
        )

    def test_resurrection_slow_repeated_rollbacks_all_within_sla(self):
        """Ten consecutive rollbacks on the same 100-checkpoint registry must all be fast."""
        registry = _make_registry(n_checkpoints=self._N_CHECKPOINTS)
        for i in range(10):
            start = time.perf_counter()
            result = registry.rollback("PRJ-001", reason=f"Repeated rollback #{i}")
            elapsed = time.perf_counter() - start
            assert result.success is True
            assert elapsed < RESURRECTION_SLOW_SLA_S, (
                f"Rollback #{i} took {elapsed:.3f}s, expected < {RESURRECTION_SLOW_SLA_S}s"
            )

    @pytest.mark.parametrize("trigger_flag,value", [
        ("spine_threatened", True),
        ("ledger_corrupted", True),
        ("nodes_disagree", True),
        ("checkpoint_lineage_unclear", True),
        ("master_phoenix_confidence", False),
    ])
    def test_resurrection_slow_all_trigger_flags_within_sla(self, trigger_flag, value):
        registry = _make_registry(n_checkpoints=self._N_CHECKPOINTS)
        orch = RecoveryOrchestrator(registry)
        incident = _make_incident(**{trigger_flag: value})
        start = time.perf_counter()
        result = orch.recover(incident)
        elapsed = time.perf_counter() - start
        assert result.method_used == RecoveryMethod.ROLLBACK
        assert result.success is True
        assert elapsed < RESURRECTION_SLOW_SLA_S, (
            f"Slow resurrection ({trigger_flag}) took {elapsed:.3f}s, "
            f"expected < {RESURRECTION_SLOW_SLA_S}s"
        )
