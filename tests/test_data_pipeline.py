import pytest

from sb_712.data_contracts import (
    CANONICAL_SCHEMA_VERSION,
    DataContractValidator,
)
from sb_712.evidence import EvidenceVault
from sb_712.system import TrustGatePipeline, TrustStatus


def test_data_contract_migrates_legacy_payload():
    migrated = DataContractValidator.migrate_payload({"object_id": "x", "source": "legacy", "schema_version": 1})
    assert migrated["schema_version"] == CANONICAL_SCHEMA_VERSION
    assert "lineage_id" in migrated


def test_evidence_vault_indexes_and_integrity():
    vault = EvidenceVault()
    first = vault.append("ev-1", "lin-1", "trust_gate", {"score": 0.9})
    second = vault.append("ev-2", "lin-1", "security_gate", {"score": 1.0})
    assert vault.verify_integrity() is True
    assert first in vault.by_lineage("lin-1")
    assert second in vault.by_category("security_gate")


def test_weighted_verification_false_positive_negative_controls():
    pipeline = TrustGatePipeline()
    trusted = pipeline.process(
        object_id="OBJ-FP",
        source="trusted_feed",
        structural_score=0.9,
        behavioral_score=0.85,
        proof_ledger_score=0.95,
        clip_policy_ok=True,
    )
    rejected = pipeline.process(
        object_id="OBJ-FN",
        source="trusted_feed",
        structural_score=0.5,
        behavioral_score=0.5,
        proof_ledger_score=0.5,
        clip_policy_ok=True,
    )
    assert trusted.status == TrustStatus.TRUSTED
    assert rejected.status == TrustStatus.QUARANTINED


def test_trust_gate_replay_consistency():
    pipeline = TrustGatePipeline()
    first = pipeline.process(
        object_id="OBJ-REPLAY",
        source="trusted_feed",
        structural_score=1.0,
        behavioral_score=1.0,
        proof_ledger_score=1.0,
        clip_policy_ok=True,
        lineage_id="lineage-replay",
    )
    second = pipeline.process(
        object_id="OBJ-REPLAY",
        source="trusted_feed",
        structural_score=1.0,
        behavioral_score=1.0,
        proof_ledger_score=1.0,
        clip_policy_ok=True,
        lineage_id="lineage-replay",
    )
    assert first.status == second.status
    assert first.lineage_id == second.lineage_id


def test_trust_gate_blocks_unknown_source_contract():
    pipeline = TrustGatePipeline()
    result = pipeline.process(
        object_id="OBJ-UNKNOWN",
        source="unknown",
        structural_score=1.0,
        behavioral_score=1.0,
        proof_ledger_score=1.0,
        clip_policy_ok=True,
    )
    assert result.status == TrustStatus.QUARANTINED


def test_schema_validator_rejects_unsupported():
    with pytest.raises(ValueError):
        DataContractValidator.require_supported_schema(999)
