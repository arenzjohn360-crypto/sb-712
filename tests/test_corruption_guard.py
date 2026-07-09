"""Tests for sb_712.corruption_guard."""
import pytest

from sb_712.checkpoint import Checkpoint, CheckpointRegistry, CheckpointStatus
from sb_712.corruption_guard import CorruptionGuard, GuardResult
from sb_712.incident import (
    IncidentStudyRecord,
    IncidentType,
    IncidentStatus,
    SourceType,
    Severity,
)
from sb_712.lesson_store import LessonStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_healthy_registry(project_id: str) -> CheckpointRegistry:
    registry = CheckpointRegistry()
    registry.add_checkpoint(
        Checkpoint(
            project_id=project_id,
            status=CheckpointStatus.HEALTHY,
            certified=True,
        )
    )
    return registry


def make_incident(**kwargs) -> IncidentStudyRecord:
    defaults = dict(
        project_id="PRJ-GUARD-001",
        incident_type=IncidentType.FILE_CORRUPTION,
        source=SourceType.CLIENT_UPLOAD,
        severity=Severity.HIGH,
        repair_action="Restored from backup",
        truth_verified=True,
        certification_result="Cleared",
    )
    defaults.update(kwargs)
    return IncidentStudyRecord(**defaults)


@pytest.fixture
def guard(tmp_path):
    registry = make_healthy_registry("PRJ-GUARD-001")
    store = LessonStore(root_dir=str(tmp_path))
    return CorruptionGuard(checkpoint_registry=registry, lesson_store=store)


# ---------------------------------------------------------------------------
# Basic cycle
# ---------------------------------------------------------------------------

def test_intercept_returns_guard_result(guard):
    incident = make_incident()
    result = guard.intercept(incident)
    assert isinstance(result, GuardResult)
    assert result.incident_id == incident.incident_id


def test_intercept_marks_learned(guard):
    result = guard.intercept(make_incident())
    assert result.learned is True


def test_intercept_marks_immunised(guard):
    result = guard.intercept(make_incident())
    assert result.immunised is True


def test_intercept_recovery_succeeds_for_local_damage(guard):
    incident = make_incident(damage_is_spreading=False, truth_verified=True)
    result = guard.intercept(incident)
    assert result.recovery_success is True


def test_intercept_restores_to_healthy_when_recovery_succeeds(guard):
    incident = make_incident(truth_verified=True)
    result = guard.intercept(incident)
    assert result.restored_to_healthy is True
    assert incident.status == IncidentStatus.CLOSED


# ---------------------------------------------------------------------------
# Spread lock
# ---------------------------------------------------------------------------

def test_spread_lock_engaged_when_damage_spreading(guard):
    incident = make_incident(damage_is_spreading=True)
    result = guard.intercept(incident)
    assert result.spread_locked is True


def test_spread_lock_active_before_recovery(tmp_path):
    """If recovery fails, spread lock must stay active."""
    registry = CheckpointRegistry()  # No checkpoints → rollback will fail
    store = LessonStore(root_dir=str(tmp_path))
    guard = CorruptionGuard(checkpoint_registry=registry, lesson_store=store)

    incident = make_incident(damage_is_spreading=True, truth_verified=False)
    result = guard.intercept(incident)
    assert result.spread_locked is True
    assert guard.is_spread_locked(incident.project_id)


def test_spread_lock_lifted_after_successful_recovery(guard):
    incident = make_incident(damage_is_spreading=True, truth_verified=True)
    guard.intercept(incident)
    # Recovery succeeded (healthy checkpoint exists), lock should be lifted.
    assert not guard.is_spread_locked(incident.project_id)


def test_no_spread_lock_for_non_spreading_incident(guard):
    incident = make_incident(damage_is_spreading=False)
    result = guard.intercept(incident)
    assert result.spread_locked is False
    assert not guard.is_spread_locked(incident.project_id)


def test_manual_lift_spread_lock(guard):
    incident = make_incident(damage_is_spreading=True, truth_verified=False)
    registry = CheckpointRegistry()  # Force failed recovery so lock stays
    guard._recovery = guard._recovery  # keep as is
    guard._spread_locks.add(incident.project_id)
    assert guard.is_spread_locked(incident.project_id)
    guard.lift_spread_lock(incident.project_id)
    assert not guard.is_spread_locked(incident.project_id)


# ---------------------------------------------------------------------------
# Lesson persistence
# ---------------------------------------------------------------------------

def test_lesson_file_recorded(guard):
    incident = make_incident()
    result = guard.intercept(incident)
    assert result.lesson_file is not None
    assert result.lesson_file.endswith(f"{incident.incident_id}.txt")


def test_lesson_content_includes_report(guard):
    incident = make_incident()
    result = guard.intercept(incident)
    text = guard.lesson_store.load_lesson(incident.incident_id)
    assert text is not None
    assert "INCIDENT STUDY REPORT" in text


def test_multiple_incidents_all_persisted(guard):
    for _ in range(5):
        guard.intercept(make_incident())
    assert guard.lesson_store.count() == 5


# ---------------------------------------------------------------------------
# Prevention rules accumulate
# ---------------------------------------------------------------------------

def test_prevention_rules_added_after_intercept(guard):
    count_before = len(guard.prevention_registry.all_rules())
    guard.intercept(make_incident())
    assert len(guard.prevention_registry.all_rules()) > count_before


# ---------------------------------------------------------------------------
# Critical severity triggers containment even without spreading flag
# ---------------------------------------------------------------------------

def test_critical_non_local_triggers_spread_lock(guard):
    incident = make_incident(
        severity=Severity.CRITICAL,
        damage_is_local=False,
        damage_is_spreading=False,
    )
    result = guard.intercept(incident)
    assert result.spread_locked is True
