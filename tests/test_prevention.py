from sb_712.prevention import PreventionRegistry, PreventionRule
from sb_712.incident import IncidentType


def test_default_rules_seeded():
    registry = PreventionRegistry()
    assert len(registry.all_rules()) > 0


def test_add_rule_increases_count():
    registry = PreventionRegistry()
    count_before = len(registry.all_rules())
    rule = PreventionRule(
        rule_id="test-001",
        incident_type=IncidentType.MISSING_RECORD,
        trigger_condition="record missing state tag",
        action="Block archive until jurisdiction tag exists",
    )
    registry.add_rule(rule)
    assert len(registry.all_rules()) == count_before + 1


def test_get_rules_for_type_returns_only_matching():
    registry = PreventionRegistry()
    rules = registry.get_rules_for_type(IncidentType.BAD_UPLOAD)
    assert len(rules) >= 1
    for r in rules:
        assert r.incident_type == IncidentType.BAD_UPLOAD


def test_get_rules_for_type_excludes_inactive():
    registry = PreventionRegistry()
    rule = PreventionRule(
        rule_id="test-inactive",
        incident_type=IncidentType.RAM_PRESSURE,
        trigger_condition="RAM overload",
        action="Slow refresh",
    )
    registry.add_rule(rule)
    registry.deactivate_rule("test-inactive")
    active = registry.get_rules_for_type(IncidentType.RAM_PRESSURE)
    assert not any(r.rule_id == "test-inactive" for r in active)


def test_block_pattern():
    registry = PreventionRegistry()
    assert not registry.is_blocked("REPEATED_ATTACK")
    registry.block_pattern("REPEATED_ATTACK")
    assert registry.is_blocked("REPEATED_ATTACK")


def test_block_pattern_multiple():
    registry = PreventionRegistry()
    registry.block_pattern("LEDGER_DRIFT")
    registry.block_pattern("PAYMENT_MISMATCH")
    assert registry.is_blocked("LEDGER_DRIFT")
    assert registry.is_blocked("PAYMENT_MISMATCH")
    assert not registry.is_blocked("UNKNOWN_CHANGE")


def test_deactivate_rule_returns_true():
    registry = PreventionRegistry()
    rule = PreventionRule(
        rule_id="test-deact",
        incident_type=IncidentType.RAM_PRESSURE,
        trigger_condition="RAM overload",
        action="Slow refresh",
    )
    registry.add_rule(rule)
    assert registry.deactivate_rule("test-deact") is True


def test_deactivate_nonexistent_rule_returns_false():
    registry = PreventionRegistry()
    assert registry.deactivate_rule("does-not-exist") is False


def test_all_rules_returns_copy():
    registry = PreventionRegistry()
    rules = registry.all_rules()
    rules.clear()
    assert len(registry.all_rules()) > 0
