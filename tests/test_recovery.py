import pytest
from sb_712.incident import IncidentStudyRecord, IncidentType, SourceType, Severity
from sb_712.checkpoint import Checkpoint, CheckpointRegistry, CheckpointStatus
from sb_712.recovery import (
    RecoveryOrchestrator,
    RecoveryMethod,
    ConvoyRecovery,
    ConvoyStage,
    ReturnCheckStage,
    PhoenixDecision,
    MAX_CONVOY_ATTEMPTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_registry(project_id="PRJ-001"):
    registry = CheckpointRegistry()
    registry.add_checkpoint(
        Checkpoint(project_id=project_id, status=CheckpointStatus.HEALTHY, certified=True)
    )
    return registry


def make_incident(**kwargs):
    """Return a healthy incident that passes all convoy stages by default."""
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
# decide_method
# ---------------------------------------------------------------------------

def test_convoy_chosen_for_local_damage():
    orch = RecoveryOrchestrator(make_registry())
    assert orch.decide_method(make_incident()) == RecoveryMethod.CONVOY


@pytest.mark.parametrize("flag,value", [
    ("spine_threatened", True),
    ("ledger_corrupted", True),
    ("nodes_disagree", True),
    ("checkpoint_lineage_unclear", True),
    ("master_phoenix_confidence", False),
])
def test_rollback_chosen_for_trigger_flags(flag, value):
    orch = RecoveryOrchestrator(make_registry())
    incident = make_incident(**{flag: value})
    assert orch.decide_method(incident) == RecoveryMethod.ROLLBACK


def test_rollback_chosen_for_repeated_attack():
    orch = RecoveryOrchestrator(make_registry())
    incident = make_incident(incident_type=IncidentType.REPEATED_ATTACK)
    assert orch.decide_method(incident) == RecoveryMethod.ROLLBACK


# ---------------------------------------------------------------------------
# Full convoy — happy path
# ---------------------------------------------------------------------------

def test_convoy_recovery_success():
    orch = RecoveryOrchestrator(make_registry())
    result = orch.recover(make_incident())
    assert result.success is True
    assert result.method_used == RecoveryMethod.CONVOY


def test_convoy_result_has_forward_and_return_check():
    orch = RecoveryOrchestrator(make_registry())
    result = orch.recover(make_incident())
    assert result.convoy_result is not None
    assert len(result.convoy_result.forward_stages) == len(ConvoyStage)
    rc = result.convoy_result.return_check
    assert rc is not None
    assert len(rc.stages) == len(ReturnCheckStage)


def test_convoy_return_check_phoenix_closed():
    orch = RecoveryOrchestrator(make_registry())
    result = orch.recover(make_incident())
    rc = result.convoy_result.return_check
    assert rc.phoenix_decision == PhoenixDecision.CLOSED


# ---------------------------------------------------------------------------
# Forward-pass failures trigger rollback
# ---------------------------------------------------------------------------

def test_convoy_falls_back_when_repair_missing():
    orch = RecoveryOrchestrator(make_registry())
    incident = make_incident(repair_action="")
    result = orch.recover(incident)
    assert result.method_used == RecoveryMethod.ROLLBACK
    assert result.rollback_result.success is True


def test_convoy_falls_back_when_truth_not_verified():
    orch = RecoveryOrchestrator(make_registry())
    incident = make_incident(truth_verified=False)
    result = orch.recover(incident)
    assert result.method_used == RecoveryMethod.ROLLBACK
    assert result.rollback_result.success is True


def test_convoy_falls_back_when_certification_missing():
    orch = RecoveryOrchestrator(make_registry())
    incident = make_incident(certification_result="")
    result = orch.recover(incident)
    assert result.method_used == RecoveryMethod.ROLLBACK


# ---------------------------------------------------------------------------
# Return-check failures trigger convoy reopen then rollback
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("outcome", [
    "problem_still_active",
    "new_damage_found",
    "repeat_attack",
])
def test_return_check_reopen_outcomes_exhaust_and_rollback(outcome):
    orch = RecoveryOrchestrator(make_registry())
    incident = make_incident(hunter_rescan_outcome=outcome)
    result = orch.recover(incident)
    # After exhausting MAX_CONVOY_ATTEMPTS, falls back to rollback.
    assert result.method_used == RecoveryMethod.ROLLBACK
    assert result.convoy_result is not None
    assert result.convoy_result.convoy_attempts == MAX_CONVOY_ATTEMPTS


def test_return_check_false_alarm_passes():
    orch = RecoveryOrchestrator(make_registry())
    incident = make_incident(hunter_rescan_outcome="false_alarm")
    result = orch.recover(incident)
    assert result.success is True
    assert result.method_used == RecoveryMethod.CONVOY


def test_return_check_problem_gone_passes():
    orch = RecoveryOrchestrator(make_registry())
    incident = make_incident(hunter_rescan_outcome="problem_gone")
    result = orch.recover(incident)
    assert result.success is True


def test_return_check_none_outcome_passes():
    orch = RecoveryOrchestrator(make_registry())
    incident = make_incident(hunter_rescan_outcome=None)
    result = orch.recover(incident)
    assert result.success is True


def test_return_check_warrior_holds_when_spreading():
    orch = RecoveryOrchestrator(make_registry())
    incident = make_incident(damage_is_spreading=True)
    result = orch.recover(incident)
    # Warrior release fails → convoy loops then rolls back.
    assert result.method_used == RecoveryMethod.ROLLBACK


# ---------------------------------------------------------------------------
# Pre-flight rollback
# ---------------------------------------------------------------------------

def test_rollback_fails_gracefully_no_checkpoint():
    orch = RecoveryOrchestrator(CheckpointRegistry())  # empty
    incident = make_incident(spine_threatened=True)
    result = orch.recover(incident)
    assert result.method_used == RecoveryMethod.ROLLBACK
    assert result.success is False


def test_rollback_used_directly_for_trigger():
    orch = RecoveryOrchestrator(make_registry())
    incident = make_incident(ledger_corrupted=True)
    result = orch.recover(incident)
    assert result.method_used == RecoveryMethod.ROLLBACK
    assert result.convoy_result is None  # no convoy was attempted
    assert result.rollback_result is not None


# ---------------------------------------------------------------------------
# ConvoyRecovery standalone
# ---------------------------------------------------------------------------

def test_convoy_standalone_success():
    convoy = ConvoyRecovery()
    incident = make_incident()
    result = convoy.run(incident)
    assert result.success is True
    assert result.convoy_attempts == 1


def test_convoy_standalone_forward_fail():
    convoy = ConvoyRecovery()
    incident = make_incident(repair_action="")
    result = convoy.run(incident)
    assert result.success is False
    assert result.failed_stage == ConvoyStage.REPAIR
