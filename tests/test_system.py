import pytest

from sb_712.system import (
    ClassificationStage,
    HeartbeatLevel,
    HeartbeatMonitor,
    ProofLedger,
    QuarantineState,
    SystemConfig,
    TrustGatePipeline,
    TrustStatus,
)


def test_system_config_requires_three_verification_passes():
    cfg = SystemConfig(verify_passes_required=2)
    with pytest.raises(ValueError):
        cfg.validate()


def test_system_config_threshold_order_must_be_valid():
    cfg = SystemConfig(phoenix_alert_threshold=99.7, self_heal_threshold=99.8)
    with pytest.raises(ValueError):
        cfg.validate()


def test_trust_gate_success_path_reaches_law():
    pipeline = TrustGatePipeline()
    result = pipeline.process(
        object_id="OBJ-1",
        source="trusted_feed",
        structural_ok=True,
        behavioral_ok=True,
        proof_ledger_ok=True,
        clip_policy_ok=True,
    )
    assert result.status == TrustStatus.TRUSTED
    assert result.certified is True
    assert result.clip_approved is True
    assert result.classification_path[-1] == ClassificationStage.LAW


def test_trust_gate_verification_failure_is_quarantined():
    pipeline = TrustGatePipeline()
    result = pipeline.process(
        object_id="OBJ-2",
        source="trusted_feed",
        structural_ok=False,
        behavioral_ok=True,
        proof_ledger_ok=True,
        clip_policy_ok=True,
    )
    assert result.status == TrustStatus.QUARANTINED
    assert result.quarantine_record is not None
    assert result.quarantine_record.state == QuarantineState.ISOLATED


def test_trust_gate_unknown_source_is_quarantined_by_default():
    pipeline = TrustGatePipeline()
    result = pipeline.process(
        object_id="OBJ-3",
        source="unknown",
        structural_ok=True,
        behavioral_ok=True,
        proof_ledger_ok=True,
        clip_policy_ok=True,
    )
    assert result.status == TrustStatus.QUARANTINED
    assert "Unknown source" in result.message


def test_trust_gate_clip_rejection_stays_untrusted():
    pipeline = TrustGatePipeline()
    result = pipeline.process(
        object_id="OBJ-4",
        source="trusted_feed",
        structural_ok=True,
        behavioral_ok=True,
        proof_ledger_ok=True,
        clip_policy_ok=False,
    )
    assert result.status == TrustStatus.REJECTED
    assert result.certified is True
    assert result.clip_approved is False


def test_quarantine_transition_rules_enforced():
    pipeline = TrustGatePipeline()
    result = pipeline.process(
        object_id="OBJ-5",
        source="trusted_feed",
        structural_ok=False,
        behavioral_ok=True,
        proof_ledger_ok=True,
        clip_policy_ok=True,
    )
    q = result.quarantine_record
    q.transition(QuarantineState.STUDYING, note="studied")
    q.transition(QuarantineState.REPAIRING, note="repairing")
    q.transition(QuarantineState.RELEASED, note="released")
    assert q.state == QuarantineState.RELEASED
    with pytest.raises(ValueError):
        q.transition(QuarantineState.STUDYING)


def test_proof_ledger_integrity_detects_tampering():
    pipeline = TrustGatePipeline()
    pipeline.process(
        object_id="OBJ-6",
        source="trusted_feed",
        structural_ok=True,
        behavioral_ok=True,
        proof_ledger_ok=True,
        clip_policy_ok=True,
    )
    ledger = pipeline.ledger
    assert ledger.verify_integrity() is True
    ledger.entries()[0].after_state = "TAMPERED"
    assert ledger.verify_integrity() is False


def test_heartbeat_monitor_levels():
    monitor = HeartbeatMonitor(SystemConfig())
    assert monitor.evaluate(100.0, 1.0, 1.0, 1.0).heartbeat_level == HeartbeatLevel.HEALTHY
    assert monitor.evaluate(99.9, 1.0, 1.0, 1.0).heartbeat_level == HeartbeatLevel.PHOENIX_ALERT
    assert monitor.evaluate(99.8, 1.0, 1.0, 1.0).heartbeat_level == HeartbeatLevel.SELF_HEALING
    assert monitor.evaluate(80.0, 1.0, 1.0, 1.0).heartbeat_level == HeartbeatLevel.DEGRADED


def test_proof_ledger_links_previous_hash_chain():
    ledger = ProofLedger()
    pipeline = TrustGatePipeline(ledger=ledger)
    pipeline.process("OBJ-7", "trusted_feed", True, True, True, True)
    pipeline.process("OBJ-8", "trusted_feed", True, True, True, False)
    entries = ledger.entries()
    assert len(entries) == 2
    assert entries[0].previous_hash == "GENESIS"
    assert entries[1].previous_hash == entries[0].entry_hash
