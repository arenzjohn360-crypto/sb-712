from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Any, Dict, List, Optional
import uuid

from .data_contracts import CANONICAL_SCHEMA_VERSION, DataContractValidator, canonical_hash
from .evidence import EvidenceVault


class ClassificationStage(Enum):
    UNKNOWN = "UNKNOWN"
    OBSERVED = "OBSERVED"
    STUDIED = "STUDIED"
    CLASSIFIED = "CLASSIFIED"
    VERIFIED = "VERIFIED"
    TRUSTED = "TRUSTED"
    LAW = "LAW"


class TrustStatus(Enum):
    QUARANTINED = "QUARANTINED"
    VERIFIED = "VERIFIED"
    CERTIFIED = "CERTIFIED"
    TRUSTED = "TRUSTED"
    REJECTED = "REJECTED"


class QuarantineState(Enum):
    ISOLATED = "ISOLATED"
    STUDYING = "STUDYING"
    REPAIRING = "REPAIRING"
    PURGED = "PURGED"
    ARCHIVED = "ARCHIVED"
    RELEASED = "RELEASED"


class HeartbeatLevel(Enum):
    HEALTHY = "HEALTHY"
    PHOENIX_ALERT = "PHOENIX_ALERT"
    SELF_HEALING = "SELF_HEALING"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True)
class SystemConfig:
    verify_passes_required: int = 3
    phoenix_alert_threshold: float = 99.9
    self_heal_threshold: float = 99.8
    minimum_ram_gb: int = 8
    max_background_scans: int = 4
    allow_unknown_sources: bool = False

    def validate(self) -> None:
        if self.verify_passes_required < 3:
            raise ValueError("verify_passes_required must be at least 3")
        if not (0 <= self.self_heal_threshold <= 100):
            raise ValueError("self_heal_threshold must be between 0 and 100")
        if not (0 <= self.phoenix_alert_threshold <= 100):
            raise ValueError("phoenix_alert_threshold must be between 0 and 100")
        if self.self_heal_threshold > self.phoenix_alert_threshold:
            raise ValueError("self_heal_threshold cannot exceed phoenix_alert_threshold")
        if self.minimum_ram_gb < 1:
            raise ValueError("minimum_ram_gb must be positive")
        if self.max_background_scans < 1:
            raise ValueError("max_background_scans must be positive")


@dataclass
class VerificationEvidence:
    structural_score: float
    behavioral_score: float
    proof_ledger_score: float
    hard_fail_reasons: List[str] = field(default_factory=list)
    structural_weight: float = 0.4
    behavioral_weight: float = 0.3
    proof_ledger_weight: float = 0.3
    minimum_weighted_score: float = 0.75

    @property
    def weighted_score(self) -> float:
        return (
            (self.structural_score * self.structural_weight)
            + (self.behavioral_score * self.behavioral_weight)
            + (self.proof_ledger_score * self.proof_ledger_weight)
        )

    @property
    def structural_ok(self) -> bool:
        return self.structural_score >= self.minimum_weighted_score

    @property
    def behavioral_ok(self) -> bool:
        return self.behavioral_score >= self.minimum_weighted_score

    @property
    def proof_ledger_ok(self) -> bool:
        return self.proof_ledger_score >= self.minimum_weighted_score

    @property
    def passed(self) -> bool:
        return not self.hard_fail_reasons and self.weighted_score >= self.minimum_weighted_score


@dataclass
class QuarantineRecord:
    object_id: str
    reason: str
    state: QuarantineState = QuarantineState.ISOLATED
    created_at: datetime = field(default_factory=datetime.utcnow)
    history: List[str] = field(default_factory=list)

    _ALLOWED_TRANSITIONS = {
        QuarantineState.ISOLATED: frozenset({QuarantineState.STUDYING}),
        QuarantineState.STUDYING: frozenset(
            {QuarantineState.REPAIRING, QuarantineState.PURGED, QuarantineState.ARCHIVED}
        ),
        QuarantineState.REPAIRING: frozenset(
            {QuarantineState.RELEASED, QuarantineState.PURGED, QuarantineState.ARCHIVED}
        ),
        QuarantineState.PURGED: frozenset(),
        QuarantineState.ARCHIVED: frozenset(),
        QuarantineState.RELEASED: frozenset(),
    }

    def transition(self, to_state: QuarantineState, note: str = "") -> None:
        allowed = self._ALLOWED_TRANSITIONS[self.state]
        if to_state not in allowed:
            raise ValueError(f"Invalid quarantine transition: {self.state.value} -> {to_state.value}")
        self.state = to_state
        if note:
            self.history.append(note)


@dataclass
class LedgerEntry:
    event_type: str
    object_id: str
    before_state: str
    after_state: str
    verification_result: str
    repair_result: str
    certification_result: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    previous_hash: str = ""
    entry_hash: str = ""
    schema_version: int = CANONICAL_SCHEMA_VERSION
    integrity_proof: str = ""
    lineage_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent_lineage_id: Optional[str] = None

    def __post_init__(self) -> None:
        DataContractValidator.validate_contract(
            object_id=self.object_id,
            source=self.event_type,
            schema_version=self.schema_version,
            lineage_id=self.lineage_id,
        )
        if not self.integrity_proof:
            self.integrity_proof = canonical_hash(
                [
                    self.event_type,
                    self.object_id,
                    self.before_state,
                    self.after_state,
                    self.verification_result,
                    self.timestamp.isoformat(),
                    self.lineage_id,
                    str(self.schema_version),
                ]
            )


class ProofLedger:
    """Append-only tamper-evident proof ledger."""

    def __init__(self) -> None:
        self._entries: List[LedgerEntry] = []

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        previous_hash = self._entries[-1].entry_hash if self._entries else "GENESIS"
        entry.previous_hash = previous_hash
        entry.entry_hash = self._hash_entry(entry)
        self._entries.append(entry)
        return entry

    def entries(self) -> List[LedgerEntry]:
        return list(self._entries)

    def verify_integrity(self) -> bool:
        previous = "GENESIS"
        for entry in self._entries:
            if entry.previous_hash != previous:
                return False
            expected_hash = self._hash_entry(entry)
            if entry.entry_hash != expected_hash:
                return False
            previous = entry.entry_hash
        return True

    def _hash_entry(self, entry: LedgerEntry) -> str:
        payload = "|".join(
            [
                entry.event_type,
                entry.object_id,
                entry.before_state,
                entry.after_state,
                entry.verification_result,
                entry.repair_result,
                entry.certification_result,
                entry.timestamp.isoformat(),
                entry.previous_hash,
                repr(sorted(entry.metadata.items())),
                str(entry.schema_version),
                entry.lineage_id,
                str(entry.parent_lineage_id or ""),
                entry.integrity_proof,
            ]
        )
        return sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class TrustGateResult:
    object_id: str
    classification_path: List[ClassificationStage]
    status: TrustStatus
    evidence: VerificationEvidence
    certified: bool
    clip_approved: bool
    quarantine_record: Optional[QuarantineRecord] = None
    message: str = ""
    schema_version: int = CANONICAL_SCHEMA_VERSION
    lineage_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    integrity_proof: str = ""


@dataclass
class SystemHealth:
    heartbeat_score: float
    heartbeat_level: HeartbeatLevel
    node_readiness: float
    recovery_readiness: float
    trust_ratio: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


class HeartbeatMonitor:
    def __init__(self, config: SystemConfig) -> None:
        self.config = config
        self._latest: Optional[SystemHealth] = None

    def evaluate(
        self,
        heartbeat_score: float,
        node_readiness: float,
        recovery_readiness: float,
        trust_ratio: float,
    ) -> SystemHealth:
        if heartbeat_score >= 100:
            level = HeartbeatLevel.HEALTHY
        elif heartbeat_score >= self.config.phoenix_alert_threshold:
            level = HeartbeatLevel.PHOENIX_ALERT
        elif heartbeat_score >= self.config.self_heal_threshold:
            level = HeartbeatLevel.SELF_HEALING
        else:
            level = HeartbeatLevel.DEGRADED
        self._latest = SystemHealth(
            heartbeat_score=heartbeat_score,
            heartbeat_level=level,
            node_readiness=node_readiness,
            recovery_readiness=recovery_readiness,
            trust_ratio=trust_ratio,
        )
        return self._latest

    def latest(self) -> Optional[SystemHealth]:
        return self._latest


@dataclass
class ConsistencySLOSnapshot:
    trust_ratio: float
    quarantine_count: int
    rollback_count: int
    reopen_loop_count: int
    drift_score: float
    alarms: List[str]
    timestamp: datetime = field(default_factory=datetime.utcnow)


class ConsistencyMonitor:
    def __init__(
        self,
        trust_ratio_floor: float = 0.95,
        quarantine_growth_limit: int = 5,
        rollback_limit: int = 2,
        reopen_loop_limit: int = 3,
    ) -> None:
        self.trust_ratio_floor = trust_ratio_floor
        self.quarantine_growth_limit = quarantine_growth_limit
        self.rollback_limit = rollback_limit
        self.reopen_loop_limit = reopen_loop_limit
        self._history: List[ConsistencySLOSnapshot] = []

    def observe(
        self,
        trust_ratio: float,
        quarantine_count: int,
        rollback_count: int,
        reopen_loop_count: int,
    ) -> ConsistencySLOSnapshot:
        alarms: List[str] = []
        if trust_ratio < self.trust_ratio_floor:
            alarms.append("TRUST_RATIO_DRIFT")
        if quarantine_count > self.quarantine_growth_limit:
            alarms.append("QUARANTINE_GROWTH")
        if rollback_count > self.rollback_limit:
            alarms.append("ROLLBACK_SPIKE")
        if reopen_loop_count > self.reopen_loop_limit:
            alarms.append("REOPEN_LOOP_SPIKE")
        drift_score = round(max(0.0, self.trust_ratio_floor - trust_ratio) + (len(alarms) * 0.1), 4)
        snapshot = ConsistencySLOSnapshot(
            trust_ratio=trust_ratio,
            quarantine_count=quarantine_count,
            rollback_count=rollback_count,
            reopen_loop_count=reopen_loop_count,
            drift_score=drift_score,
            alarms=alarms,
        )
        self._history.append(snapshot)
        return snapshot

    def history(self) -> List[ConsistencySLOSnapshot]:
        return list(self._history)


class TrustGatePipeline:
    """Classify -> verify x3 -> certify -> clip."""

    def __init__(
        self,
        config: Optional[SystemConfig] = None,
        ledger: Optional[ProofLedger] = None,
        evidence_vault: Optional[EvidenceVault] = None,
    ) -> None:
        self.config = config or SystemConfig()
        self.config.validate()
        self.ledger = ledger or ProofLedger()
        self.evidence_vault = evidence_vault or EvidenceVault()
        self._quarantine: Dict[str, QuarantineRecord] = {}

    def process(
        self,
        object_id: str,
        source: str,
        structural_ok: Optional[bool] = None,
        behavioral_ok: Optional[bool] = None,
        proof_ledger_ok: Optional[bool] = None,
        clip_policy_ok: bool = True,
        structural_score: Optional[float] = None,
        behavioral_score: Optional[float] = None,
        proof_ledger_score: Optional[float] = None,
        hard_fail_reasons: Optional[List[str]] = None,
        schema_version: int = CANONICAL_SCHEMA_VERSION,
        lineage_id: Optional[str] = None,
        parent_lineage_id: Optional[str] = None,
    ) -> TrustGateResult:
        normalized_object_id, normalized_source = DataContractValidator.validate_contract(
            object_id=object_id,
            source=source,
            schema_version=schema_version,
            lineage_id=lineage_id,
        )
        lineage = lineage_id or uuid.uuid4().hex
        path = [
            ClassificationStage.UNKNOWN,
            ClassificationStage.OBSERVED,
            ClassificationStage.STUDIED,
            ClassificationStage.CLASSIFIED,
        ]
        structural_score = self._resolve_score(structural_score, structural_ok)
        behavioral_score = self._resolve_score(behavioral_score, behavioral_ok)
        proof_ledger_score = self._resolve_score(proof_ledger_score, proof_ledger_ok)
        evidence = VerificationEvidence(
            structural_score=structural_score,
            behavioral_score=behavioral_score,
            proof_ledger_score=proof_ledger_score,
            hard_fail_reasons=list(hard_fail_reasons or []),
        )

        if not self.config.allow_unknown_sources and normalized_source == "unknown":
            quarantine = self._isolate(normalized_object_id, "Unknown source blocked by policy.")
            return self._result(
                object_id=normalized_object_id,
                path=path,
                status=TrustStatus.QUARANTINED,
                evidence=evidence,
                certified=False,
                clip_approved=False,
                quarantine=quarantine,
                message="Unknown source quarantined.",
                verification_result="SOURCE_REJECTED",
                after_state=TrustStatus.QUARANTINED.value,
                schema_version=schema_version,
                lineage_id=lineage,
                parent_lineage_id=parent_lineage_id,
            )

        if not evidence.passed:
            quarantine = self._isolate(normalized_object_id, "Weighted verification failed.")
            return self._result(
                object_id=normalized_object_id,
                path=path,
                status=TrustStatus.QUARANTINED,
                evidence=evidence,
                certified=False,
                clip_approved=False,
                quarantine=quarantine,
                message="Verification failed. Object isolated.",
                verification_result="VERIFY_FAILED",
                after_state=TrustStatus.QUARANTINED.value,
                schema_version=schema_version,
                lineage_id=lineage,
                parent_lineage_id=parent_lineage_id,
            )

        path.append(ClassificationStage.VERIFIED)
        certified = True
        if not clip_policy_ok:
            return self._result(
                object_id=normalized_object_id,
                path=path,
                status=TrustStatus.REJECTED,
                evidence=evidence,
                certified=certified,
                clip_approved=False,
                quarantine=None,
                message="Clip brick policy rejected object.",
                verification_result="VERIFY_PASSED",
                after_state=TrustStatus.REJECTED.value,
                schema_version=schema_version,
                lineage_id=lineage,
                parent_lineage_id=parent_lineage_id,
            )

        path.extend([ClassificationStage.TRUSTED, ClassificationStage.LAW])
        return self._result(
            object_id=normalized_object_id,
            path=path,
            status=TrustStatus.TRUSTED,
            evidence=evidence,
            certified=certified,
            clip_approved=True,
            quarantine=None,
            message="Object verified, certified, clipped, and trusted.",
            verification_result="VERIFY_PASSED",
            after_state=TrustStatus.TRUSTED.value,
            schema_version=schema_version,
            lineage_id=lineage,
            parent_lineage_id=parent_lineage_id,
        )

    def quarantine_record(self, object_id: str) -> Optional[QuarantineRecord]:
        return self._quarantine.get(object_id)

    def _isolate(self, object_id: str, reason: str) -> QuarantineRecord:
        record = QuarantineRecord(object_id=object_id, reason=reason)
        record.history.append(reason)
        self._quarantine[object_id] = record
        return record

    def _result(
        self,
        object_id: str,
        path: List[ClassificationStage],
        status: TrustStatus,
        evidence: VerificationEvidence,
        certified: bool,
        clip_approved: bool,
        quarantine: Optional[QuarantineRecord],
        message: str,
        verification_result: str,
        after_state: str,
        schema_version: int,
        lineage_id: str,
        parent_lineage_id: Optional[str],
    ) -> TrustGateResult:
        integrity_proof = canonical_hash(
            [
                object_id,
                status.value,
                f"{evidence.weighted_score:.6f}",
                lineage_id,
                str(schema_version),
            ]
        )
        self.evidence_vault.append(
            evidence_id=f"trust:{object_id}:{len(self.ledger.entries()) + 1}",
            lineage_id=lineage_id,
            category="trust_gate",
            payload={
                "object_id": object_id,
                "status": status.value,
                "score": evidence.weighted_score,
                "classification_path": [stage.value for stage in path],
                "hard_fail_reasons": list(evidence.hard_fail_reasons),
            },
        )
        ledger_entry = self.ledger.append(
            LedgerEntry(
                event_type="trust_gate_decision",
                object_id=object_id,
                before_state=ClassificationStage.UNKNOWN.value,
                after_state=after_state,
                verification_result=verification_result,
                repair_result="N/A",
                certification_result="CERTIFIED" if certified else "NOT_CERTIFIED",
                metadata={
                    "clip_approved": clip_approved,
                    "classification_path": [stage.value for stage in path],
                    "weighted_score": evidence.weighted_score,
                    "hard_fail_reasons": list(evidence.hard_fail_reasons),
                },
                schema_version=schema_version,
                integrity_proof=integrity_proof,
                lineage_id=lineage_id,
                parent_lineage_id=parent_lineage_id,
            )
        )
        return TrustGateResult(
            object_id=object_id,
            classification_path=path,
            status=status,
            evidence=evidence,
            certified=certified,
            clip_approved=clip_approved,
            quarantine_record=quarantine,
            message=message,
            schema_version=schema_version,
            lineage_id=lineage_id,
            integrity_proof=ledger_entry.integrity_proof,
        )

    @staticmethod
    def _resolve_score(score: Optional[float], legacy_flag: Optional[bool]) -> float:
        if score is not None:
            if score < 0.0 or score > 1.0:
                raise ValueError("Verification score must be between 0.0 and 1.0")
            return score
        if legacy_flag is None:
            return 0.0
        return 1.0 if legacy_flag else 0.0
