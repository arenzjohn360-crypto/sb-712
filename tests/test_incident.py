from datetime import datetime
from sb_712.incident import (
    IncidentStudyRecord,
    IncidentType,
    IncidentStatus,
    SourceType,
    Severity,
    HUNTER_RESCAN_OUTCOMES,
    HUNTER_RESCAN_REOPEN_OUTCOMES,
)


def make_record(**kwargs):
    defaults = dict(
        project_id="PRJ-001",
        incident_type=IncidentType.FILE_CORRUPTION,
        source=SourceType.CLIENT_UPLOAD,
        severity=Severity.MEDIUM,
    )
    defaults.update(kwargs)
    return IncidentStudyRecord(**defaults)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def test_record_defaults():
    r = make_record()
    assert r.status == IncidentStatus.OPEN
    assert r.repeat_risk is False
    assert r.what_it_touched == []
    assert r.hunter_rescan_outcome is None
    assert r.incident_id  # auto-generated UUID
    assert isinstance(r.date, datetime)


def test_record_has_unique_ids():
    r1 = make_record()
    r2 = make_record()
    assert r1.incident_id != r2.incident_id


# ---------------------------------------------------------------------------
# Field assignment
# ---------------------------------------------------------------------------

def test_record_custom_fields():
    r = make_record(
        what_happened="Client uploaded wrong file",
        damage_found="Project folder partially overwritten",
        severity=Severity.HIGH,
        hunter_rescan_outcome="problem_gone",
    )
    assert r.what_happened == "Client uploaded wrong file"
    assert r.severity == Severity.HIGH
    assert r.hunter_rescan_outcome == "problem_gone"


# ---------------------------------------------------------------------------
# Enum completeness
# ---------------------------------------------------------------------------

def test_incident_types_complete():
    expected = {
        "FILE_CORRUPTION", "MISSING_RECORD", "BAD_UPLOAD", "PAYMENT_MISMATCH",
        "PROOF_MISSING", "REVISION_ERROR", "FINAL_RELEASE_BLOCK",
        "CONTRACTOR_PAYOUT_MISMATCH", "COMPLIANCE_RECORD_ERROR", "LEDGER_DRIFT",
        "CHECKPOINT_DAMAGE", "DUPLICATE_PROCESS", "RAM_PRESSURE",
        "UNKNOWN_CHANGE", "REPEATED_ATTACK", "USER_ERROR", "SYSTEM_ERROR",
    }
    assert {t.value for t in IncidentType} == expected


def test_source_types_include_unknown():
    assert SourceType.UNKNOWN_SOURCE in list(SourceType)


def test_severity_levels_ordered():
    assert [s.value for s in Severity] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


# ---------------------------------------------------------------------------
# Rescan outcome constants
# ---------------------------------------------------------------------------

def test_hunter_rescan_outcomes_defined():
    assert "problem_gone" in HUNTER_RESCAN_OUTCOMES
    assert "false_alarm" in HUNTER_RESCAN_OUTCOMES


def test_reopen_outcomes_subset_of_all_outcomes():
    assert HUNTER_RESCAN_REOPEN_OUTCOMES.issubset(HUNTER_RESCAN_OUTCOMES)


def test_reopen_outcomes_content():
    assert "problem_still_active" in HUNTER_RESCAN_REOPEN_OUTCOMES
    assert "new_damage_found" in HUNTER_RESCAN_REOPEN_OUTCOMES
    assert "repeat_attack" in HUNTER_RESCAN_REOPEN_OUTCOMES
    assert "problem_gone" not in HUNTER_RESCAN_REOPEN_OUTCOMES
    assert "false_alarm" not in HUNTER_RESCAN_REOPEN_OUTCOMES
