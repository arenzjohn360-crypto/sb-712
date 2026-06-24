from sb_712.incident import IncidentStudyRecord, IncidentType, SourceType, Severity
from sb_712.prevention import PreventionRegistry
from sb_712.learning_node import LearningNode
from sb_712.immunity_node import ImmunityNode


def make_incident(**kwargs):
    defaults = dict(
        project_id="PRJ-001",
        incident_type=IncidentType.LEDGER_DRIFT,
        source=SourceType.SCRIPT_ACTION,
        severity=Severity.CRITICAL,
        repair_action="Reconciled ledger",
        root_cause="Script drift",
        repeat_risk=True,
    )
    defaults.update(kwargs)
    return IncidentStudyRecord(**defaults)


def get_studied_incident(**kwargs):
    registry = PreventionRegistry()
    node = LearningNode(registry)
    incident = make_incident(**kwargs)
    node.process(incident)
    return incident, registry


# ---------------------------------------------------------------------------
# apply_immunity — tightened gates
# ---------------------------------------------------------------------------

def test_apply_immunity_tightens_gate_for_source():
    incident, registry = get_studied_incident()
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert f"intake_gate:{SourceType.SCRIPT_ACTION.value}" in immunity.tightened_gates


def test_apply_immunity_tightens_all_unknown_gate_for_unknown_source():
    incident, registry = get_studied_incident(source=SourceType.UNKNOWN_SOURCE)
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert "intake_gate:all_unknown" in immunity.tightened_gates


# ---------------------------------------------------------------------------
# apply_immunity — blocked patterns
# ---------------------------------------------------------------------------

def test_apply_immunity_blocks_repeated_pattern_when_repeat_risk():
    incident, registry = get_studied_incident()
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert registry.is_blocked("LEDGER_DRIFT")


def test_apply_immunity_does_not_block_when_no_repeat_risk():
    incident, registry = get_studied_incident(
        incident_type=IncidentType.BAD_UPLOAD, repeat_risk=False
    )
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert not registry.is_blocked("BAD_UPLOAD")


# ---------------------------------------------------------------------------
# apply_immunity — quarantine triggers
# ---------------------------------------------------------------------------

def test_apply_immunity_adds_quarantine_trigger():
    incident, registry = get_studied_incident()
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert any("LEDGER_DRIFT" in t for t in immunity.quarantine_triggers)
    assert any("script_action" in t for t in immunity.quarantine_triggers)


# ---------------------------------------------------------------------------
# apply_immunity — hunter detection
# ---------------------------------------------------------------------------

def test_apply_immunity_updates_hunter_detection():
    incident, registry = get_studied_incident()
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert "hunt:LEDGER_DRIFT" in immunity.hunter_detection_updates


def test_hunter_detection_deduplicates():
    registry = PreventionRegistry()
    immunity = ImmunityNode(registry)
    immunity.update_hunter_detection("hunt:FILE_CORRUPTION")
    immunity.update_hunter_detection("hunt:FILE_CORRUPTION")
    assert immunity.hunter_detection_updates.count("hunt:FILE_CORRUPTION") == 1


# ---------------------------------------------------------------------------
# apply_immunity — verification + certification
# ---------------------------------------------------------------------------

def test_apply_immunity_adds_verification_question():
    incident, registry = get_studied_incident()
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert len(immunity.verification_questions) >= 1
    assert any("LEDGER_DRIFT" in q for q in immunity.verification_questions)


def test_apply_immunity_adds_certification_requirement():
    incident, registry = get_studied_incident()
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert len(immunity.certification_requirements) >= 1
    assert any("LEDGER_DRIFT" in r for r in immunity.certification_requirements)


def test_verification_questions_deduplicate():
    registry = PreventionRegistry()
    immunity = ImmunityNode(registry)
    immunity.update_verification_questions("Was file quarantined?")
    immunity.update_verification_questions("Was file quarantined?")
    assert immunity.verification_questions.count("Was file quarantined?") == 1


# ---------------------------------------------------------------------------
# apply_immunity — owner warnings
# ---------------------------------------------------------------------------

def test_owner_warning_added_for_critical():
    incident, registry = get_studied_incident(severity=Severity.CRITICAL)
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert len(immunity.owner_warnings) >= 1
    assert any(
        "CRITICAL" in w or "LEDGER_DRIFT" in w
        for w in immunity.owner_warnings
    )


def test_owner_warning_added_for_high():
    incident, registry = get_studied_incident(severity=Severity.HIGH)
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert len(immunity.owner_warnings) >= 1


def test_no_owner_warning_for_low_severity():
    incident, registry = get_studied_incident(severity=Severity.LOW)
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert len(immunity.owner_warnings) == 0


def test_no_owner_warning_for_medium_severity():
    incident, registry = get_studied_incident(severity=Severity.MEDIUM)
    immunity = ImmunityNode(registry)
    immunity.apply_immunity(incident)
    assert len(immunity.owner_warnings) == 0


# ---------------------------------------------------------------------------
# convert_to_rule
# ---------------------------------------------------------------------------

def test_convert_to_rule_registers_when_not_present():
    incident, registry = get_studied_incident()
    count_before = len(registry.all_rules())
    # Simulate ImmunityNode receiving a record whose rule came from LearningNode.
    # Since LearningNode already added with source_incident_id, it should NOT double-add.
    immunity = ImmunityNode(registry)
    immunity.convert_to_rule(incident)
    # Rule from learning node already exists for this incident_id — no duplicate.
    rules_for_type = registry.get_rules_for_type(IncidentType.LEDGER_DRIFT)
    matching = [r for r in rules_for_type if r.source_incident_id == incident.incident_id]
    assert len(matching) == 1


def test_convert_to_rule_no_op_when_prevention_rule_empty():
    registry = PreventionRegistry()
    immunity = ImmunityNode(registry)
    incident = make_incident(prevention_rule_added="")
    count_before = len(registry.all_rules())
    immunity.convert_to_rule(incident)
    assert len(registry.all_rules()) == count_before
