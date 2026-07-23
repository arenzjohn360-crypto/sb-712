"""
Tests for SB-712 T-800 Silent Intercept Node.
"""
import pytest

from sb_712 import (
    InterceptDecision,
    InterceptPhase,
    SilentInterceptNode,
    ThreatBehaviourRecord,
)


class TestThreatBehaviourRecord:
    def test_threat_score_zero_for_single_attempt(self):
        rec = ThreatBehaviourRecord(threat_id="t-001", access_attempts=1)
        assert rec.threat_score < 0.5

    def test_exfiltration_raises_score(self):
        baseline = ThreatBehaviourRecord(threat_id="t-002", access_attempts=5)
        hostile = ThreatBehaviourRecord(
            threat_id="t-003", access_attempts=5, exfiltration_attempted=True
        )
        assert hostile.threat_score > baseline.threat_score

    def test_score_capped_at_one(self):
        rec = ThreatBehaviourRecord(
            threat_id="t-004",
            access_attempts=100,
            exfiltration_attempted=True,
            privilege_escalation_attempted=True,
            lateral_movement_detected=True,
        )
        assert rec.threat_score <= 1.0
        assert rec.threat_score >= 0.99

    def test_add_pattern_deduplicates(self):
        rec = ThreatBehaviourRecord(threat_id="t-005")
        rec.add_pattern("scan:port443")
        rec.add_pattern("scan:port443")
        assert rec.patterns_observed.count("scan:port443") == 1


class TestSilentInterceptNodeShadowPhase:
    def test_single_attempt_stays_in_shadow(self):
        node = SilentInterceptNode()
        result = node.intercept("threat-A", access_attempts=1)
        assert result.final_phase == InterceptPhase.SHADOW
        assert result.decision == InterceptDecision.CONTINUE_STUDY

    def test_shadow_phase_no_honeypot(self):
        node = SilentInterceptNode()
        result = node.intercept("threat-A", access_attempts=1)
        assert result.behaviour.decoys_consumed == 0
        assert result.deception_success is False


class TestSilentInterceptNodeStudyPhase:
    def test_two_attempts_enters_study(self):
        node = SilentInterceptNode()
        result = node.intercept("threat-B", access_attempts=2)
        assert result.final_phase == InterceptPhase.STUDYING

    def test_honeypot_active_in_study_phase(self):
        node = SilentInterceptNode()
        result = node.intercept("threat-B", access_attempts=2)
        assert result.deception_success is True
        assert result.behaviour.decoys_consumed == 1

    def test_patterns_banked_during_study(self):
        node = SilentInterceptNode()
        result = node.intercept(
            "threat-C",
            access_attempts=3,
            observed_patterns=["sql_injection", "port_scan"],
        )
        assert "sql_injection" in result.patterns_banked
        assert "port_scan" in result.patterns_banked


class TestSilentInterceptNodePurge:
    def test_high_threat_score_triggers_purge(self):
        node = SilentInterceptNode()
        result = node.intercept(
            "threat-D",
            access_attempts=10,
            exfiltration=True,
            privilege_escalation=True,
            lateral_movement=True,
        )
        assert result.purged is True
        assert result.final_phase == InterceptPhase.PURGED
        assert result.decision == InterceptDecision.SILENCE_AND_PURGE

    def test_lesson_summary_contains_threat_id(self):
        node = SilentInterceptNode()
        result = node.intercept("threat-E", access_attempts=10, exfiltration=True)
        assert "threat-E" in result.lesson_summary


class TestPatternBanking:
    def test_fingerprint_always_banked(self):
        node = SilentInterceptNode()
        result = node.intercept("threat-F", access_attempts=1)
        assert any("sig:" in p for p in result.patterns_banked)

    def test_banked_patterns_accumulate_across_calls(self):
        node = SilentInterceptNode()
        node.intercept("t-1", access_attempts=3, observed_patterns=["alpha"])
        node.intercept("t-2", access_attempts=3, observed_patterns=["beta"])
        patterns = node.banked_patterns()
        assert "alpha" in patterns
        assert "beta" in patterns

    def test_is_known_threat_returns_true_for_banked_pattern(self):
        node = SilentInterceptNode()
        node.intercept("t-3", access_attempts=3, observed_patterns=["xss_probe"])
        assert node.is_known_threat("xss_probe") is True

    def test_is_known_threat_returns_false_for_unknown(self):
        node = SilentInterceptNode()
        assert node.is_known_threat("unknown_sig") is False


class TestKnowledgeSharing:
    def test_export_and_import_between_nodes(self):
        node_a = SilentInterceptNode()
        node_a.intercept("t-A1", access_attempts=3, observed_patterns=["sig-x"])

        node_b = SilentInterceptNode()
        added = node_b.import_patterns(node_a.export_patterns())

        assert added > 0
        assert node_b.is_known_threat("sig-x")

    def test_import_skips_duplicates(self):
        node_a = SilentInterceptNode()
        node_a.intercept("t-A2", access_attempts=3, observed_patterns=["dupe-sig"])

        node_b = SilentInterceptNode()
        first_add = node_b.import_patterns(node_a.export_patterns())
        second_add = node_b.import_patterns(node_a.export_patterns())

        assert first_add > 0
        assert second_add == 0


class TestGetIntercept:
    def test_get_intercept_returns_last_result(self):
        node = SilentInterceptNode()
        node.intercept("threat-G", access_attempts=2)
        result = node.get_intercept("threat-G")
        assert result is not None
        assert result.threat_id == "threat-G"

    def test_get_intercept_returns_none_for_unknown(self):
        node = SilentInterceptNode()
        assert node.get_intercept("nonexistent") is None
