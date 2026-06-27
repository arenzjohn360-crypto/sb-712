"""
Phoenix Resurrection Node & Self-Healing Benchmark Tests
=========================================================

Measures and reports the exact percentages and timings for:

1. Corruption detection rate (across 5 / 20 / 40 / 100 % corruption loads)
2. Self-heal success rate (across 5 / 20 / 40 % corruption loads)
3. Phoenix convoy stage timing — how fast each stage of the Recovery Convoy
   completes under a clean-pass incident.
4. ReplicaSet sync heal speed — time for replica sync to restore all corrupt
   blocks after 5 / 20 / 40 % of keys on one replica are corrupted.
5. HeartbeatMonitor threshold boundaries — verifies the exact 99.8 % (self-heal
   trigger) and 99.9 % (Phoenix alert) thresholds documented in README § 18-19.
6. Recovery success rate — convoy vs. rollback outcomes across all incident
   types, all rollback-trigger flags, all convoy failure modes, reopen-loop
   exhaustion, and a mixed-batch overall success rate summary.

All parametrized cases use print() output so the exact numbers appear in the
captured stdout when running:  pytest tests/test_phoenix_benchmarks.py -v -s
"""
import os
import time

import pytest
from sb688 import BlockStore, IntegrityChecker, ReplicaSet

from sb_712.incident import (
    IncidentStudyRecord,
    IncidentType,
    SourceType,
    Severity,
    HUNTER_RESCAN_REOPEN_OUTCOMES,
)
from sb_712.checkpoint import Checkpoint, CheckpointRegistry, CheckpointStatus
from sb_712.recovery import (
    ConvoyRecovery,
    ConvoyStage,
    ReturnCheckStage,
    RecoveryMethod,
    RecoveryOrchestrator,
    MAX_CONVOY_ATTEMPTS,
)
from sb_712.system import HeartbeatLevel, HeartbeatMonitor, SystemConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry(project_id: str = "PRJ-BENCH") -> CheckpointRegistry:
    reg = CheckpointRegistry()
    reg.add_checkpoint(
        Checkpoint(project_id=project_id, status=CheckpointStatus.HEALTHY, certified=True)
    )
    return reg


def _make_incident(**kwargs) -> IncidentStudyRecord:
    defaults = dict(
        project_id="PRJ-BENCH",
        incident_type=IncidentType.FILE_CORRUPTION,
        source=SourceType.CLIENT_UPLOAD,
        severity=Severity.LOW,
        repair_action="Replaced corrupted block",
        truth_verified=True,
        certification_result="Clean",
        return_check_result="Stable",
        damage_is_local=True,
    )
    defaults.update(kwargs)
    return IncidentStudyRecord(**defaults)


# ---------------------------------------------------------------------------
# 1. Corruption detection rate
# ---------------------------------------------------------------------------

class TestCorruptionDetectionRate:
    """
    Verify that 100 % of intentionally corrupted blocks are detected,
    across multiple corruption-load levels.
    """

    @pytest.mark.parametrize("corruption_pct", [5, 20, 40, 100])
    def test_detection_rate(self, corruption_pct: int) -> None:
        n = 100
        store = BlockStore()
        for i in range(n):
            store.put(f"k{i}", os.urandom(64))

        corrupt_count = max(1, n * corruption_pct // 100)
        corrupt_keys = {f"k{i}" for i in range(corrupt_count)}
        for k in corrupt_keys:
            store.inject_bit_flip(k, 0)

        detected = set(store.corrupt_keys())
        missed = corrupt_keys - detected
        false_positives = detected - corrupt_keys

        detection_rate = len(detected & corrupt_keys) / len(corrupt_keys) * 100
        fp_rate = len(false_positives) / (n - len(corrupt_keys)) * 100 if n > len(corrupt_keys) else 0.0

        print(
            f"\n[detection] corruption={corruption_pct}% | "
            f"injected={len(corrupt_keys)} | detected={len(detected & corrupt_keys)} | "
            f"missed={len(missed)} | false_positives={len(false_positives)} | "
            f"detection_rate={detection_rate:.2f}% | fp_rate={fp_rate:.2f}%"
        )

        assert detection_rate == 100.0, (
            f"Detection rate was {detection_rate:.2f}% at {corruption_pct}% corruption. "
            f"Missed keys: {missed}"
        )
        assert false_positives == set(), (
            f"False positives detected: {false_positives}"
        )


# ---------------------------------------------------------------------------
# 2. Self-heal success rate
# ---------------------------------------------------------------------------

class TestSelfHealRate:
    """
    Corrupt a primary store and heal from a backup replica.
    Reports the exact self-heal success rate for each corruption level.
    """

    @pytest.mark.parametrize("corruption_pct", [5, 20, 40])
    def test_self_heal_success_rate(self, corruption_pct: int) -> None:
        n = 100
        primary = BlockStore()
        backup = BlockStore()
        data = {f"blk_{i}": os.urandom(64) for i in range(n)}

        for k, v in data.items():
            primary.put(k, v)
            backup.put(k, v)

        corrupt_count = max(1, n * corruption_pct // 100)
        corrupt_keys = [f"blk_{i}" for i in range(corrupt_count)]
        for k in corrupt_keys:
            primary.inject_bit_flip(k, 0)

        checker = IntegrityChecker(primary, repair_source=backup)

        t_start = time.perf_counter()
        results = checker.scan_and_heal()
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000

        healed_count = sum(1 for ok in results.values() if ok)
        failed_count = len(results) - healed_count
        heal_rate = healed_count / len(corrupt_keys) * 100 if corrupt_keys else 100.0
        remaining_corrupt = primary.corrupt_keys()

        print(
            f"\n[self-heal] corruption={corruption_pct}% | "
            f"corrupt_blocks={len(corrupt_keys)} | healed={healed_count} | "
            f"failed={failed_count} | heal_rate={heal_rate:.2f}% | "
            f"remaining_corrupt={len(remaining_corrupt)} | "
            f"elapsed={elapsed_ms:.3f}ms"
        )

        assert heal_rate == 100.0, (
            f"Self-heal rate was {heal_rate:.2f}% at {corruption_pct}% corruption. "
            f"Failed keys: {[k for k, ok in results.items() if not ok]}"
        )
        assert remaining_corrupt == [], (
            f"Blocks still corrupt after heal: {remaining_corrupt}"
        )


# ---------------------------------------------------------------------------
# 3. Phoenix convoy stage timing
# ---------------------------------------------------------------------------

class TestPhoenixConvoyTiming:
    """
    Runs the full Recovery Convoy (forward + return-check loop) and reports
    the wall-clock time for the entire round-trip.

    The Phoenix Resurrection Node documentation (README § 18) states the
    target restore is "under a millisecond conceptually in simulation."
    """

    def test_convoy_completes_and_reports_timing(self) -> None:
        convoy = ConvoyRecovery()
        incident = _make_incident()

        t_start = time.perf_counter()
        result = convoy.run(incident)
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000

        forward_stage_names = [s.stage.value for s in result.forward_stages]
        return_stage_names = (
            [s.stage.value for s in result.return_check.stages]
            if result.return_check else []
        )

        print(
            f"\n[phoenix-convoy] success={result.success} | "
            f"attempts={result.convoy_attempts} | "
            f"elapsed={elapsed_ms:.4f}ms"
        )
        print(f"  forward stages : {forward_stage_names}")
        print(f"  return stages  : {return_stage_names}")
        print(f"  phoenix decision: {result.return_check.phoenix_decision.value if result.return_check else 'N/A'}")

        assert result.success is True
        assert result.convoy_attempts == 1
        assert len(result.forward_stages) == len(ConvoyStage)
        assert result.return_check is not None
        assert len(result.return_check.stages) == len(ReturnCheckStage)

    def test_convoy_per_stage_timing(self) -> None:
        """Run the full orchestrator and confirm timing for all stages."""
        orch = RecoveryOrchestrator(_make_registry())
        incident = _make_incident()

        t_start = time.perf_counter()
        result = orch.recover(incident)
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000

        print(
            f"\n[phoenix-orchestrator] method={result.method_used.value} | "
            f"success={result.success} | "
            f"elapsed={elapsed_ms:.4f}ms"
        )
        for stage in result.convoy_result.forward_stages:
            print(f"  FORWARD  {stage.stage.value:12s}: {stage.message}")
        for stage in result.convoy_result.return_check.stages:
            print(f"  RETURN   {stage.stage.value:20s}: {stage.message}")

        assert result.success is True


# ---------------------------------------------------------------------------
# 4. ReplicaSet sync heal speed (Phoenix node replica sync)
# ---------------------------------------------------------------------------

class TestReplicaSetSyncSpeed:
    """
    Measures how quickly ReplicaSet.sync() restores corrupted blocks
    on a degraded replica — this models the Phoenix node sync cycle.
    """

    @pytest.mark.parametrize("corruption_pct", [5, 20, 40])
    def test_replica_sync_heal_speed(self, corruption_pct: int) -> None:
        n = 100
        replicas = ReplicaSet(n=3, quorum=2)
        data = {f"k{i}": os.urandom(32) for i in range(n)}
        for k, v in data.items():
            replicas.put(k, v)

        corrupt_count = max(1, n * corruption_pct // 100)
        for i in range(corrupt_count):
            replicas.corrupt_replica(0, f"k{i}", 0)

        t_start = time.perf_counter()
        healed = replicas.sync()
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000

        total_repaired = sum(healed.values())
        heal_rate = len(healed) / corrupt_count * 100 if corrupt_count else 100.0

        # Verify all keys on replica 0 are now clean
        still_corrupt = replicas.get_replica(0).corrupt_keys()

        print(
            f"\n[replica-sync] corruption={corruption_pct}% | "
            f"corrupt_blocks={corrupt_count} | "
            f"keys_healed={len(healed)} | total_replica_repairs={total_repaired} | "
            f"heal_rate={heal_rate:.2f}% | remaining_corrupt={len(still_corrupt)} | "
            f"elapsed={elapsed_ms:.3f}ms"
        )

        assert heal_rate == 100.0, (
            f"Replica sync heal rate was {heal_rate:.2f}% at {corruption_pct}% corruption"
        )
        assert still_corrupt == [], (
            f"Replica 0 still has corrupt blocks after sync: {still_corrupt}"
        )
        for k, v in data.items():
            assert replicas.get_replica(0).get(k) == v


# ---------------------------------------------------------------------------
# 5. HeartbeatMonitor threshold boundaries
# ---------------------------------------------------------------------------

class TestHeartbeatThresholds:
    """
    Verifies the exact documented threshold percentages:
      - 100.0  → HEALTHY
      - 99.9   → PHOENIX_ALERT  (first Phoenix node wakes)
      - 99.8   → SELF_HEALING   (self-heal trigger)
      - below  → DEGRADED
    """

    _CASES = [
        (100.0,  HeartbeatLevel.HEALTHY),
        (99.95,  HeartbeatLevel.PHOENIX_ALERT),
        (99.9,   HeartbeatLevel.PHOENIX_ALERT),
        (99.85,  HeartbeatLevel.SELF_HEALING),
        (99.8,   HeartbeatLevel.SELF_HEALING),
        (99.79,  HeartbeatLevel.DEGRADED),
        (80.0,   HeartbeatLevel.DEGRADED),
        (0.0,    HeartbeatLevel.DEGRADED),
    ]

    @pytest.mark.parametrize("score,expected_level", _CASES)
    def test_threshold_boundary(self, score: float, expected_level: HeartbeatLevel) -> None:
        monitor = HeartbeatMonitor(SystemConfig())
        health = monitor.evaluate(score, 1.0, 1.0, 1.0)

        print(
            f"\n[heartbeat] score={score:.4f}% → level={health.heartbeat_level.value} "
            f"(expected {expected_level.value})"
        )

        assert health.heartbeat_level == expected_level, (
            f"At score={score}%: expected {expected_level.value}, "
            f"got {health.heartbeat_level.value}"
        )

    def test_all_thresholds_summary(self) -> None:
        """Print a full threshold summary table."""
        monitor = HeartbeatMonitor(SystemConfig())
        cfg = monitor.config

        print("\n[heartbeat-thresholds] Summary")
        print(f"  phoenix_alert_threshold : {cfg.phoenix_alert_threshold}%")
        print(f"  self_heal_threshold     : {cfg.self_heal_threshold}%")
        print()
        print(f"  {'Score':>8}  {'Level':<20}")
        print(f"  {'-'*8}  {'-'*20}")
        for score, _ in self._CASES:
            h = monitor.evaluate(score, 1.0, 1.0, 1.0)
            print(f"  {score:>8.4f}  {h.heartbeat_level.value:<20}")


# ---------------------------------------------------------------------------
# 6. Recovery success rate
# ---------------------------------------------------------------------------

class TestRecoverySuccessRate:
    """
    Measures the end-to-end recovery success rate across every meaningful
    incident scenario.

    Four sub-dimensions are reported separately, then a mixed-batch summary
    rolls them into a single overall success %.

    Sub-dimensions:
      A) Clean convoy — all convoy-eligible incident types; expect 100 % success
         via CONVOY method.
      B) Pre-flight rollback triggers — flag combinations that mandate immediate
         rollback; success depends on having a healthy checkpoint.
      C) Convoy failure paths — missing repair/truth/certification; convoy fails
         and falls back to rollback, which succeeds because registry has a
         healthy checkpoint.
      D) Reopen-loop exhaustion — hunter rescan outcomes that reopen the convoy;
         after MAX_CONVOY_ATTEMPTS the orchestrator rolls back; success because
         registry has a checkpoint.
    """

    # -- Convoy-eligible incident types (no rollback pre-flight triggers) -----
    _CONVOY_INCIDENT_TYPES = [
        IncidentType.FILE_CORRUPTION,
        IncidentType.MISSING_RECORD,
        IncidentType.BAD_UPLOAD,
        IncidentType.PAYMENT_MISMATCH,
        IncidentType.PROOF_MISSING,
        IncidentType.REVISION_ERROR,
        IncidentType.FINAL_RELEASE_BLOCK,
        IncidentType.CONTRACTOR_PAYOUT_MISMATCH,
        IncidentType.COMPLIANCE_RECORD_ERROR,
        IncidentType.LEDGER_DRIFT,
        IncidentType.CHECKPOINT_DAMAGE,
        IncidentType.DUPLICATE_PROCESS,
        IncidentType.RAM_PRESSURE,
        IncidentType.UNKNOWN_CHANGE,
        IncidentType.USER_ERROR,
        IncidentType.SYSTEM_ERROR,
    ]

    # -- Pre-flight rollback trigger flags ------------------------------------
    _ROLLBACK_TRIGGERS = [
        {"spine_threatened": True},
        {"ledger_corrupted": True},
        {"nodes_disagree": True},
        {"checkpoint_lineage_unclear": True},
        {"master_phoenix_confidence": False},
        {"incident_type": IncidentType.REPEATED_ATTACK},
    ]

    # -- Convoy forward-pass failure modes ------------------------------------
    _CONVOY_FAIL_MODES = [
        {"repair_action": ""},           # REPAIR stage fails
        {"truth_verified": False},       # VERIFY stage fails
        {"certification_result": ""},    # CERTIFY stage fails
    ]

    # -- Hunter rescan outcomes that reopen the convoy -----------------------
    _REOPEN_OUTCOMES = list(HUNTER_RESCAN_REOPEN_OUTCOMES)

    # -------------------------------------------------------------------------

    @pytest.mark.parametrize("incident_type", _CONVOY_INCIDENT_TYPES)
    def test_convoy_success_rate_per_incident_type(
        self, incident_type: IncidentType
    ) -> None:
        """Each clean incident type should recover 100 % via convoy."""
        orch = RecoveryOrchestrator(_make_registry())
        incident = _make_incident(incident_type=incident_type)

        t_start = time.perf_counter()
        result = orch.recover(incident)
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000

        print(
            f"\n[recovery-convoy] incident={incident_type.value} | "
            f"method={result.method_used.value} | success={result.success} | "
            f"elapsed={elapsed_ms:.4f}ms"
        )

        assert result.method_used == RecoveryMethod.CONVOY
        assert result.success is True

    @pytest.mark.parametrize("trigger", _ROLLBACK_TRIGGERS)
    def test_rollback_trigger_success_rate(self, trigger: dict) -> None:
        """
        Pre-flight rollback triggers always route to ROLLBACK.
        With a healthy checkpoint the rollback succeeds (100 % success rate).
        """
        orch = RecoveryOrchestrator(_make_registry())
        incident = _make_incident(**trigger)

        t_start = time.perf_counter()
        result = orch.recover(incident)
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000

        trigger_desc = ", ".join(f"{k}={v}" for k, v in trigger.items())
        print(
            f"\n[recovery-rollback-trigger] trigger=({trigger_desc}) | "
            f"method={result.method_used.value} | success={result.success} | "
            f"elapsed={elapsed_ms:.4f}ms"
        )

        assert result.method_used == RecoveryMethod.ROLLBACK
        assert result.success is True

    @pytest.mark.parametrize("fail_kwargs", _CONVOY_FAIL_MODES)
    def test_convoy_failure_fallback_success_rate(self, fail_kwargs: dict) -> None:
        """
        When the convoy forward pass cannot complete, the orchestrator falls
        back to rollback.  With a healthy checkpoint the overall recovery
        still succeeds — keeping the fallback success rate at 100 %.
        """
        orch = RecoveryOrchestrator(_make_registry())
        incident = _make_incident(**fail_kwargs)

        t_start = time.perf_counter()
        result = orch.recover(incident)
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000

        fail_desc = ", ".join(f"{k}={v!r}" for k, v in fail_kwargs.items())
        print(
            f"\n[recovery-convoy-fail] failure=({fail_desc}) | "
            f"method={result.method_used.value} | success={result.success} | "
            f"elapsed={elapsed_ms:.4f}ms"
        )

        assert result.method_used == RecoveryMethod.ROLLBACK
        assert result.success is True

    @pytest.mark.parametrize("outcome", _REOPEN_OUTCOMES)
    def test_reopen_loop_exhaustion_success_rate(self, outcome: str) -> None:
        """
        Hunter rescan outcomes that reopen the convoy exhaust MAX_CONVOY_ATTEMPTS
        and then fall back to rollback.  With a healthy checkpoint the overall
        recovery succeeds at 100 %.
        """
        orch = RecoveryOrchestrator(_make_registry())
        incident = _make_incident(hunter_rescan_outcome=outcome)

        t_start = time.perf_counter()
        result = orch.recover(incident)
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000

        print(
            f"\n[recovery-reopen] outcome={outcome!r} | "
            f"method={result.method_used.value} | "
            f"convoy_attempts={result.convoy_result.convoy_attempts if result.convoy_result else 'N/A'} | "
            f"success={result.success} | elapsed={elapsed_ms:.4f}ms"
        )

        assert result.method_used == RecoveryMethod.ROLLBACK
        assert result.convoy_result is not None
        assert result.convoy_result.convoy_attempts == MAX_CONVOY_ATTEMPTS
        assert result.success is True

    def test_overall_recovery_success_rate_summary(self) -> None:
        """
        Runs ALL scenarios in a single batch and prints the overall
        recovery success rate, convoy rate, and rollback rate.
        """
        orch = RecoveryOrchestrator(_make_registry())
        scenarios = []

        # A) All clean convoy incidents
        for itype in self._CONVOY_INCIDENT_TYPES:
            scenarios.append(_make_incident(incident_type=itype))

        # B) All pre-flight rollback triggers
        for trigger in self._ROLLBACK_TRIGGERS:
            scenarios.append(_make_incident(**trigger))

        # C) All convoy failure modes (fallback to rollback)
        for fail_kwargs in self._CONVOY_FAIL_MODES:
            scenarios.append(_make_incident(**fail_kwargs))

        # D) All reopen outcomes (exhaust convoy then rollback)
        for outcome in self._REOPEN_OUTCOMES:
            scenarios.append(_make_incident(hunter_rescan_outcome=outcome))

        total = len(scenarios)
        succeeded = 0
        convoy_success = 0
        rollback_success = 0
        rollback_fail = 0

        t_batch_start = time.perf_counter()
        for incident in scenarios:
            result = orch.recover(incident)
            if result.success:
                succeeded += 1
            if result.method_used == RecoveryMethod.CONVOY and result.success:
                convoy_success += 1
            elif result.method_used == RecoveryMethod.ROLLBACK and result.success:
                rollback_success += 1
            elif result.method_used == RecoveryMethod.ROLLBACK and not result.success:
                rollback_fail += 1
        t_batch_end = time.perf_counter()
        batch_ms = (t_batch_end - t_batch_start) * 1000

        overall_rate = succeeded / total * 100
        convoy_rate = convoy_success / total * 100
        rollback_rate = rollback_success / total * 100

        print("\n[recovery-summary] ══════════════════════════════════════")
        print(f"  Total scenarios          : {total}")
        print(f"  Succeeded                : {succeeded}  ({overall_rate:.2f}%)")
        print(f"  ├─ Via CONVOY (success)  : {convoy_success}  ({convoy_rate:.2f}%)")
        print(f"  ├─ Via ROLLBACK (success): {rollback_success}  ({rollback_rate:.2f}%)")
        print(f"  └─ ROLLBACK (no checkpoint): {rollback_fail}")
        print(f"  Batch elapsed            : {batch_ms:.3f}ms")
        print("  ════════════════════════════════════════════════════")

        assert overall_rate == 100.0, (
            f"Overall recovery success rate was {overall_rate:.2f}% "
            f"({total - succeeded} scenario(s) failed)"
        )
