from sb_712.incident import IncidentStudyRecord, IncidentType, SourceType, Severity
from sb_712.prevention import PreventionRegistry
from sb_712.learning_node import LearningNode


def make_incident(**kwargs):
    defaults = dict(
        project_id="PRJ-001",
        incident_type=IncidentType.PAYMENT_MISMATCH,
        source=SourceType.PAYMENT_SYSTEM,
        severity=Severity.HIGH,
        repair_action="Recalculated payout from cleared deposit",
        truth_verified=True,
        verification_result="Match confirmed",
        certification_result="Cleared",
        return_check_result="Stable",
    )
    defaults.update(kwargs)
    return IncidentStudyRecord(**defaults)


def test_process_derives_root_cause():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    incident = make_incident()
    node.process(incident)
    assert "PAYMENT_MISMATCH" in incident.root_cause
    assert "payment_system" in incident.root_cause


def test_process_does_not_overwrite_existing_root_cause():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    incident = make_incident(root_cause="Manual analysis")
    node.process(incident)
    assert incident.root_cause == "Manual analysis"


def test_process_creates_prevention_rule():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    count_before = len(registry.all_rules())
    incident = make_incident()
    node.process(incident)
    assert len(registry.all_rules()) > count_before
    assert incident.prevention_rule_added != ""


def test_process_does_not_overwrite_manual_prevention_rule():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    count_before = len(registry.all_rules())
    incident = make_incident(prevention_rule_added="Manual rule: block this")
    node.process(incident)
    assert incident.prevention_rule_added == "Manual rule: block this"
    assert len(registry.all_rules()) == count_before


def test_process_flags_hunter_and_verification_updated():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    incident = make_incident()
    node.process(incident)
    assert incident.hunter_pattern_updated is True
    assert incident.verification_rule_updated is True


def test_process_sets_checkpoint_created():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    incident = make_incident()
    node.process(incident)
    assert incident.checkpoint_created is True


def test_repeat_risk_flagged_for_payment_mismatch():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    incident = make_incident(incident_type=IncidentType.PAYMENT_MISMATCH)
    node.process(incident)
    assert incident.repeat_risk is True


def test_repeat_risk_flagged_for_ledger_drift():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    incident = make_incident(incident_type=IncidentType.LEDGER_DRIFT)
    node.process(incident)
    assert incident.repeat_risk is True


def test_repeat_risk_not_flagged_for_low_risk():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    incident = make_incident(incident_type=IncidentType.BAD_UPLOAD)
    node.process(incident)
    assert incident.repeat_risk is False


def test_process_returns_report_string():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    incident = make_incident()
    report = node.process(incident)
    assert "INCIDENT STUDY REPORT" in report
    assert incident.incident_id in report


def test_all_lesson_reports_accumulate():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    for _ in range(3):
        node.process(make_incident())
    assert len(node.all_lesson_reports()) == 3


def test_all_lesson_reports_returns_copy():
    registry = PreventionRegistry()
    node = LearningNode(registry)
    node.process(make_incident())
    reports = node.all_lesson_reports()
    reports.clear()
    assert len(node.all_lesson_reports()) == 1
