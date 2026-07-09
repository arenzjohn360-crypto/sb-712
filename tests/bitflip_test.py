"""
bitflip_test.py — SB-712 IronBraid Radiant Core

Tests that verify the system responds correctly to single-bit-flip style
corruption events, including proper risk escalation to VERA.
"""

import pytest

from intelligence.mask_evaluator import MaskEvaluator
from intelligence.vera_gate import CertificationBundle, VERAGate
from intelligence.forecast_node import ForecastNode, RiskForecast
from intelligence.fieldview_encoder import FieldSnapshot


class TestMaskEvaluator:
    def setup_method(self):
        self.evaluator = MaskEvaluator()

    def test_low_risk_for_untouched_data(self):
        result = self.evaluator.evaluate("data/active_brics/safe.bric", action="read",
                                         state="CERTIFIED")
        assert result.risk_score < 0.5

    def test_high_risk_for_spine_write(self):
        result = self.evaluator.evaluate("spine/root_manifest.json", action="write",
                                         state="VERIFIED")
        assert result.risk_score >= 0.5
        assert result.escalate_to_vera is True

    def test_unverified_state_raises_risk(self):
        result = self.evaluator.evaluate("data/intake/new_file.dat", action="read",
                                         state="UNVERIFIED")
        assert "UNTRUSTED_STATE:UNVERIFIED" in result.flags

    def test_ledger_write_escalates(self):
        result = self.evaluator.evaluate("ledger/ledger.jsonl", action="write",
                                         state="CERTIFIED")
        assert result.escalate_to_vera is True

    def test_delete_action_adds_mutating_flag(self):
        result = self.evaluator.evaluate("data/active_brics/x.bric", action="delete",
                                         state="CERTIFIED")
        assert any("MUTATING_ACTION" in f for f in result.flags)


class TestVERAGate:
    def setup_method(self):
        self.gate = VERAGate()

    def test_approved_with_full_bundle(self):
        bundle = CertificationBundle(hash_check=True, validation_pass=True,
                                     certification_mark=True)
        decision = self.gate.evaluate("write", "spine/root_manifest.json", bundle)
        assert decision.approved is True

    def test_denied_without_certification_mark(self):
        bundle = CertificationBundle(hash_check=True, validation_pass=True,
                                     certification_mark=False)
        decision = self.gate.evaluate("write", "spine/root_manifest.json", bundle)
        assert decision.approved is False
        assert "certification_mark" in decision.reason

    def test_denied_with_empty_bundle(self):
        bundle = CertificationBundle()
        decision = self.gate.evaluate("delete", "spine/ledger_head.json", bundle)
        assert decision.approved is False

    def test_audit_log_grows(self):
        bundle = CertificationBundle(hash_check=True, validation_pass=True,
                                     certification_mark=True)
        self.gate.evaluate("read", "data/x.bric", bundle)
        self.gate.evaluate("write", "data/y.bric", bundle)
        assert len(self.gate.audit_log) == 2


class TestForecastNodeBitFlip:
    def test_no_risk_on_clean_snapshots(self):
        node = ForecastNode()
        snaps = [FieldSnapshot() for _ in range(3)]
        forecast = node.predict(snaps)
        assert forecast.risk_score == 0.0
        assert forecast.risk_level == "LOW"

    def test_risk_increases_with_mutations(self):
        node = ForecastNode()
        snap = FieldSnapshot(mutation_count=10)
        forecast = node.predict([snap])
        assert forecast.risk_score > 0.0

    def test_empty_snapshot_list_returns_zero_risk(self):
        node = ForecastNode()
        forecast = node.predict([])
        assert forecast.risk_score == 0.0
