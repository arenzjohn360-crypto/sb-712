"""
checkpoint_poison_test.py — SB-712 IronBraid Radiant Core

Tests that verify the system rejects poisoned or invalid checkpoints and
falls back to the most recent certified ancestor.
"""

import time

import pytest

from recovery.checkpoint_validator import CheckpointRecord, CheckpointValidator
from recovery.phoenix_triangle import (
    CheckpointCandidate,
    PhoenixNode,
    PhoenixState,
    PhoenixTriangle,
)
from recovery.rollback_engine import RollbackEngine


class TestCheckpointValidator:
    def setup_method(self):
        self.validator = CheckpointValidator()

    def _good_record(self, cid: str = "ckpt-001") -> CheckpointRecord:
        return CheckpointRecord(
            checkpoint_id=cid,
            state_hash="abc" * 21 + "a",
            previous_checkpoint_id="ckpt-000",
            ledger_seq=5,
            timestamp=time.time(),
            vera_certified=True,
            replica_count=2,
        )

    def test_valid_checkpoint_passes(self):
        result = self.validator.validate(self._good_record())
        assert result.valid is True
        assert len(result.checks_failed) == 0

    def test_missing_hash_fails(self):
        rec = self._good_record()
        rec.state_hash = ""
        result = self.validator.validate(rec)
        assert result.valid is False
        assert "state_hash_present" in result.checks_failed

    def test_uncertified_fails(self):
        rec = self._good_record()
        rec.vera_certified = False
        result = self.validator.validate(rec)
        assert result.valid is False
        assert "vera_certified" in result.checks_failed

    def test_zero_replicas_fails(self):
        rec = self._good_record()
        rec.replica_count = 0
        result = self.validator.validate(rec)
        assert result.valid is False

    def test_future_timestamp_fails(self):
        rec = self._good_record()
        rec.timestamp = time.time() + 7200  # 2 hours in the future
        result = self.validator.validate(rec)
        assert result.valid is False
        assert "timestamp_sanity" in result.checks_failed


class TestPhoenixRejectsPoison:
    def _good_candidate(self) -> CheckpointCandidate:
        return CheckpointCandidate(
            checkpoint_id="ckpt-007",
            hash="validhash123",
            ledger_seq=10,
            timestamp=time.time(),
            mutation_distance=3,
            vera_certified=True,
            lineage_ok=True,
            replica_agreement=True,
        )

    def test_good_candidate_verified(self):
        node = PhoenixNode("phoenix-a")
        result = node.evaluate_and_restore(self._good_candidate())
        assert result.state == PhoenixState.VERIFIED

    def test_uncertified_candidate_rejected(self):
        node = PhoenixNode("phoenix-a")
        candidate = self._good_candidate()
        candidate.vera_certified = False
        result = node.evaluate_and_restore(candidate)
        assert result.state == PhoenixState.FAILED
        assert result.restored_checkpoint is None

    def test_bad_lineage_rejected(self):
        node = PhoenixNode("phoenix-a")
        candidate = self._good_candidate()
        candidate.lineage_ok = False
        result = node.evaluate_and_restore(candidate)
        assert result.state == PhoenixState.FAILED

    def test_no_replica_agreement_rejected(self):
        node = PhoenixNode("phoenix-a")
        candidate = self._good_candidate()
        candidate.replica_agreement = False
        result = node.evaluate_and_restore(candidate)
        assert result.state == PhoenixState.FAILED

    def test_triangle_majority_required(self):
        cluster = PhoenixTriangle()
        candidate = self._good_candidate()
        results = cluster.recover(candidate)
        assert cluster.majority_verified(results) is True

    def test_triangle_fails_on_all_bad_candidates(self):
        cluster = PhoenixTriangle()
        candidate = self._good_candidate()
        candidate.vera_certified = False
        candidate.lineage_ok = False
        results = cluster.recover(candidate)
        assert cluster.majority_verified(results) is False


class TestRollbackFallback:
    def test_rollback_succeeds_with_certified_checkpoint(self):
        engine = RollbackEngine()
        engine.register_checkpoint("ckpt-001", certified=True)
        engine.register_checkpoint("ckpt-002", certified=True)
        record = engine.rollback("QUARANTINED")
        assert record.success is True
        assert record.to_checkpoint == "ckpt-002"

    def test_rollback_fails_without_certified_checkpoints(self):
        engine = RollbackEngine()
        engine.register_checkpoint("ckpt-001", certified=False)
        record = engine.rollback("FAILED")
        assert record.success is False

    def test_rollback_uses_most_recent(self):
        engine = RollbackEngine()
        engine.register_checkpoint("ckpt-001", certified=True)
        engine.register_checkpoint("ckpt-002", certified=True)
        engine.register_checkpoint("ckpt-003", certified=True)
        record = engine.rollback("FAILED")
        assert record.to_checkpoint == "ckpt-003"
