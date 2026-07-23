"""
Tests for SB-712 Agentive Intelligence Layer.
"""
import pytest

from sb_712 import AgentiveClassifier, CalibrationRecord, ThreatAssessment
from sb_712.incident import (
    IncidentStudyRecord,
    IncidentType,
    Severity,
    SourceType,
)


def _make_incident(
    incident_type: IncidentType = IncidentType.FILE_CORRUPTION,
    severity: Severity = Severity.LOW,
    source: SourceType = SourceType.CLIENT_UPLOAD,
    repeat_risk: bool = False,
    damage_is_spreading: bool = False,
    spine_threatened: bool = False,
    ledger_corrupted: bool = False,
) -> IncidentStudyRecord:
    return IncidentStudyRecord(
        project_id="test-project",
        incident_type=incident_type,
        source=source,
        severity=severity,
        repeat_risk=repeat_risk,
        damage_is_spreading=damage_is_spreading,
        spine_threatened=spine_threatened,
        ledger_corrupted=ledger_corrupted,
    )


class TestAssessmentScoring:
    def test_low_severity_low_score(self):
        classifier = AgentiveClassifier()
        incident = _make_incident(severity=Severity.LOW)
        assessment = classifier.assess(incident)
        assert assessment.confidence_score < 0.5

    def test_critical_severity_high_score(self):
        classifier = AgentiveClassifier()
        incident = _make_incident(severity=Severity.CRITICAL)
        assessment = classifier.assess(incident)
        assert assessment.confidence_score >= 0.80

    def test_spreading_damage_raises_score(self):
        classifier = AgentiveClassifier()
        baseline = classifier.assess(_make_incident(severity=Severity.MEDIUM))
        spreading = classifier.assess(
            _make_incident(severity=Severity.MEDIUM, damage_is_spreading=True)
        )
        assert spreading.confidence_score > baseline.confidence_score

    def test_repeat_risk_raises_score(self):
        classifier = AgentiveClassifier()
        baseline = classifier.assess(_make_incident(severity=Severity.LOW))
        repeated = classifier.assess(
            _make_incident(severity=Severity.LOW, repeat_risk=True)
        )
        assert repeated.confidence_score > baseline.confidence_score

    def test_spine_threatened_raises_score(self):
        classifier = AgentiveClassifier()
        baseline = classifier.assess(_make_incident(severity=Severity.MEDIUM))
        spine = classifier.assess(
            _make_incident(severity=Severity.MEDIUM, spine_threatened=True)
        )
        assert spine.confidence_score > baseline.confidence_score

    def test_score_capped_at_one(self):
        classifier = AgentiveClassifier()
        incident = _make_incident(
            severity=Severity.CRITICAL,
            damage_is_spreading=True,
            repeat_risk=True,
            spine_threatened=True,
            ledger_corrupted=True,
        )
        assessment = classifier.assess(incident)
        assert assessment.confidence_score <= 1.0


class TestSuggestedSeverity:
    def test_high_score_suggests_critical(self):
        classifier = AgentiveClassifier()
        incident = _make_incident(
            severity=Severity.CRITICAL,
            damage_is_spreading=True,
        )
        assessment = classifier.assess(incident)
        assert assessment.suggested_severity == Severity.CRITICAL

    def test_low_score_suggests_low(self):
        classifier = AgentiveClassifier()
        incident = _make_incident(severity=Severity.LOW)
        assessment = classifier.assess(incident)
        assert assessment.suggested_severity in (Severity.LOW, Severity.MEDIUM)


class TestSuggestedAction:
    def test_auto_escalate_action_on_high_score(self):
        classifier = AgentiveClassifier()
        incident = _make_incident(
            severity=Severity.CRITICAL,
            damage_is_spreading=True,
        )
        assessment = classifier.assess(incident)
        assert "AUTO_ESCALATE" in assessment.suggested_action

    def test_spread_lock_action_on_spreading(self):
        classifier = AgentiveClassifier()
        # Low severity + spreading — score below escalation threshold, but spreading.
        incident = _make_incident(severity=Severity.LOW, damage_is_spreading=True)
        assessment = classifier.assess(incident)
        assert "SPREAD_LOCK" in assessment.suggested_action

    def test_pattern_block_action_on_repeat_risk(self):
        classifier = AgentiveClassifier()
        incident = _make_incident(severity=Severity.LOW, repeat_risk=True)
        assessment = classifier.assess(incident)
        assert "PATTERN_BLOCK" in assessment.suggested_action


class TestReasoning:
    def test_reasoning_contains_score(self):
        classifier = AgentiveClassifier()
        assessment = classifier.assess(_make_incident())
        assert "Confidence score:" in assessment.reasoning

    def test_reasoning_mentions_spreading(self):
        classifier = AgentiveClassifier()
        assessment = classifier.assess(
            _make_incident(severity=Severity.MEDIUM, damage_is_spreading=True)
        )
        assert "spreading" in assessment.reasoning.lower()

    def test_reasoning_mentions_spine(self):
        classifier = AgentiveClassifier()
        assessment = classifier.assess(
            _make_incident(severity=Severity.HIGH, spine_threatened=True)
        )
        assert "spine" in assessment.reasoning.lower()


class TestPatternLearning:
    def test_pattern_added_after_assessment(self):
        classifier = AgentiveClassifier()
        incident = _make_incident(
            incident_type=IncidentType.REPEATED_ATTACK,
            source=SourceType.UNKNOWN_SOURCE,
        )
        classifier.assess(incident)
        patterns = classifier.export_patterns()
        assert any("REPEATED_ATTACK" in p for p in patterns)

    def test_second_assessment_matches_pattern(self):
        classifier = AgentiveClassifier()
        incident = _make_incident(
            incident_type=IncidentType.BAD_UPLOAD,
            source=SourceType.EMAIL_INTAKE,
        )
        classifier.assess(incident)
        # Second assessment of same type should match the stored pattern.
        assessment2 = classifier.assess(incident)
        assert len(assessment2.patterns_matched) > 0


class TestCalibration:
    def test_record_true_positive_increments_counter(self):
        classifier = AgentiveClassifier()
        assessment = classifier.assess(_make_incident(severity=Severity.HIGH))
        classifier.record_outcome(assessment.assessment_id, was_correct=True, was_positive_detection=True)
        assert classifier.calibration.true_positives == 1

    def test_record_false_positive_increments_counter(self):
        classifier = AgentiveClassifier()
        assessment = classifier.assess(_make_incident(severity=Severity.HIGH))
        classifier.record_outcome(assessment.assessment_id, was_correct=False, was_positive_detection=False)
        assert classifier.calibration.false_positives == 1

    def test_precision_one_when_no_false_positives(self):
        classifier = AgentiveClassifier()
        assessment = classifier.assess(_make_incident(severity=Severity.HIGH))
        classifier.record_outcome(assessment.assessment_id, was_correct=True, was_positive_detection=True)
        assert classifier.calibration.precision == 1.0

    def test_f1_between_zero_and_one(self):
        classifier = AgentiveClassifier()
        a = classifier.assess(_make_incident(severity=Severity.MEDIUM))
        classifier.record_outcome(a.assessment_id, was_correct=True, was_positive_detection=True)
        f1 = classifier.calibration.f1
        assert 0.0 <= f1 <= 1.0


class TestKnowledgeSharing:
    def test_export_returns_list(self):
        classifier = AgentiveClassifier()
        classifier.assess(_make_incident())
        patterns = classifier.export_patterns()
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_import_patterns_from_peer(self):
        node_a = AgentiveClassifier()
        node_a.assess(
            _make_incident(
                incident_type=IncidentType.LEDGER_DRIFT,
                source=SourceType.SCRIPT_ACTION,
            )
        )
        node_b = AgentiveClassifier()
        added = node_b.import_patterns(node_a.export_patterns())
        assert added > 0
        # A second import should add nothing new.
        assert node_b.import_patterns(node_a.export_patterns()) == 0

    def test_imported_patterns_appear_in_matches(self):
        node_a = AgentiveClassifier()
        node_a.assess(
            _make_incident(
                incident_type=IncidentType.CHECKPOINT_DAMAGE,
                source=SourceType.SCRIPT_ACTION,
            )
        )
        node_b = AgentiveClassifier()
        node_b.import_patterns(node_a.export_patterns())
        # Node B should now recognise the pattern node A learned.
        assessment = node_b.assess(
            _make_incident(
                incident_type=IncidentType.CHECKPOINT_DAMAGE,
                source=SourceType.SCRIPT_ACTION,
            )
        )
        assert len(assessment.patterns_matched) > 0


class TestAssessmentHistory:
    def test_history_grows_with_each_assessment(self):
        classifier = AgentiveClassifier()
        for _ in range(5):
            classifier.assess(_make_incident())
        assert len(classifier.assessment_history()) == 5

    def test_history_preserves_assessment_ids(self):
        classifier = AgentiveClassifier()
        a1 = classifier.assess(_make_incident())
        a2 = classifier.assess(_make_incident())
        ids = [a.assessment_id for a in classifier.assessment_history()]
        assert a1.assessment_id in ids
        assert a2.assessment_id in ids
