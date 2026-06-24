from datetime import datetime
from sb_712.incident import (
    IncidentStudyRecord,
    IncidentType,
    IncidentStatus,
    SourceType,
    Severity,
)
from sb_712.report import generate_report


def make_full_incident():
    return IncidentStudyRecord(
        project_id="PRJ-999",
        incident_type=IncidentType.PAYMENT_MISMATCH,
        source=SourceType.PAYMENT_SYSTEM,
        severity=Severity.HIGH,
        what_happened="Payment did not clear",
        location="payment-module",
        when_started=datetime(2024, 3, 15, 10, 0),
        where_it_came_from="External payment gateway",
        how_it_got_in="Webhook mismatch",
        what_it_touched=["payment-record", "contractor-payout"],
        damage_found="Payout record shows incorrect amount",
        containment_action="Froze contractor payout",
        repair_action="Recalculated from cleared deposit",
        verification_result="Amounts match",
        certification_result="Cleared by finance module",
        return_check_result="Stable after 24 hours",
        hunter_rescan_outcome="problem_gone",
        root_cause="Webhook delivered partial amount",
        repeat_risk=True,
        prevention_rule_added="Recalculate payout from cleared deposit only",
        hunter_pattern_updated=True,
        verification_rule_updated=True,
        checkpoint_created=True,
        status=IncidentStatus.CLOSED,
    )


# ---------------------------------------------------------------------------
# Required fields present
# ---------------------------------------------------------------------------

def test_report_contains_incident_id():
    incident = make_full_incident()
    assert incident.incident_id in generate_report(incident)


def test_report_contains_project_id():
    assert "PRJ-999" in generate_report(make_full_incident())


def test_report_contains_incident_type():
    assert "PAYMENT_MISMATCH" in generate_report(make_full_incident())


def test_report_contains_source():
    assert "payment_system" in generate_report(make_full_incident())


def test_report_contains_severity():
    assert "HIGH" in generate_report(make_full_incident())


def test_report_contains_header():
    assert "INCIDENT STUDY REPORT" in generate_report(make_full_incident())


# ---------------------------------------------------------------------------
# Damage + repair fields
# ---------------------------------------------------------------------------

def test_report_contains_what_it_touched():
    report = generate_report(make_full_incident())
    assert "payment-record" in report
    assert "contractor-payout" in report


def test_report_contains_repair_action():
    assert "Recalculated from cleared deposit" in generate_report(make_full_incident())


def test_report_contains_prevention_rule():
    assert "cleared deposit" in generate_report(make_full_incident())


# ---------------------------------------------------------------------------
# Return-check fields
# ---------------------------------------------------------------------------

def test_report_contains_hunter_rescan_outcome():
    assert "problem_gone" in generate_report(make_full_incident())


def test_report_shows_not_yet_performed_when_no_rescan():
    incident = IncidentStudyRecord(
        project_id="PRJ-001",
        incident_type=IncidentType.BAD_UPLOAD,
        source=SourceType.CLIENT_UPLOAD,
        severity=Severity.LOW,
    )
    assert "NOT YET PERFORMED" in generate_report(incident)


# ---------------------------------------------------------------------------
# Boolean flags
# ---------------------------------------------------------------------------

def test_report_shows_yes_for_repeat_risk():
    assert "YES" in generate_report(make_full_incident())


def test_report_shows_no_for_false_flags():
    incident = IncidentStudyRecord(
        project_id="PRJ-001",
        incident_type=IncidentType.BAD_UPLOAD,
        source=SourceType.CLIENT_UPLOAD,
        severity=Severity.LOW,
    )
    assert "NO" in generate_report(incident)


def test_report_shows_status_closed():
    assert "CLOSED" in generate_report(make_full_incident())


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_report_handles_empty_what_it_touched():
    incident = IncidentStudyRecord(
        project_id="PRJ-001",
        incident_type=IncidentType.BAD_UPLOAD,
        source=SourceType.CLIENT_UPLOAD,
        severity=Severity.LOW,
    )
    assert "NONE" in generate_report(incident)


def test_report_handles_missing_optional_fields():
    incident = IncidentStudyRecord(
        project_id="PRJ-001",
        incident_type=IncidentType.SYSTEM_ERROR,
        source=SourceType.UNKNOWN_SOURCE,
        severity=Severity.MEDIUM,
    )
    report = generate_report(incident)
    assert "UNKNOWN" in report
    assert "PENDING" in report
    assert "NOT RECORDED" in report
