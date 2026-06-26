from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Dict, List, Optional


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
    structural_ok: bool
    behavioral_ok: bool
    proof_ledger_ok: bool

    @property
    def passed(self) -> bool:
        return self.structural_ok and self.behavioral_ok and self.proof_ledger_ok


@dataclass
class QuarantineRecord:
    object_id: str
    reason: str
    state: QuarantineState = QuarantineState.ISOLATED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    previous_hash: str = ""
    entry_hash: str = ""


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


@dataclass
class SystemHealth:
    heartbeat_score: float
    heartbeat_level: HeartbeatLevel
    node_readiness: float
    recovery_readiness: float
    trust_ratio: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


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


class TrustGatePipeline:
    """Classify -> verify x3 -> certify -> clip."""

    def __init__(self, config: Optional[SystemConfig] = None, ledger: Optional[ProofLedger] = None) -> None:
        self.config = config or SystemConfig()
        self.config.validate()
        self.ledger = ledger or ProofLedger()
        self._quarantine: Dict[str, QuarantineRecord] = {}

    def process(
        self,
        object_id: str,
        source: str,
        structural_ok: bool,
        behavioral_ok: bool,
        proof_ledger_ok: bool,
        clip_policy_ok: bool,
    ) -> TrustGateResult:
        path = [
            ClassificationStage.UNKNOWN,
            ClassificationStage.OBSERVED,
            ClassificationStage.STUDIED,
            ClassificationStage.CLASSIFIED,
        ]
        evidence = VerificationEvidence(
            structural_ok=structural_ok,
            behavioral_ok=behavioral_ok,
            proof_ledger_ok=proof_ledger_ok,
        )

        if not self.config.allow_unknown_sources and source == "unknown":
            quarantine = self._isolate(object_id, "Unknown source blocked by policy.")
            return self._result(
                object_id=object_id,
                path=path,
                status=TrustStatus.QUARANTINED,
                evidence=evidence,
                certified=False,
                clip_approved=False,
                quarantine=quarantine,
                message="Unknown source quarantined.",
                verification_result="SOURCE_REJECTED",
                after_state=TrustStatus.QUARANTINED.value,
            )

        if not evidence.passed:
            quarantine = self._isolate(object_id, "Triple verification failed.")
            return self._result(
                object_id=object_id,
                path=path,
                status=TrustStatus.QUARANTINED,
                evidence=evidence,
                certified=False,
                clip_approved=False,
                quarantine=quarantine,
                message="Verification failed. Object isolated.",
                verification_result="VERIFY_FAILED",
                after_state=TrustStatus.QUARANTINED.value,
            )

        path.append(ClassificationStage.VERIFIED)
        certified = True
        if not clip_policy_ok:
            return self._result(
                object_id=object_id,
                path=path,
                status=TrustStatus.REJECTED,
                evidence=evidence,
                certified=certified,
                clip_approved=False,
                quarantine=None,
                message="Clip brick policy rejected object.",
                verification_result="VERIFY_PASSED",
                after_state=TrustStatus.REJECTED.value,
            )

        path.extend([ClassificationStage.TRUSTED, ClassificationStage.LAW])
        return self._result(
            object_id=object_id,
            path=path,
            status=TrustStatus.TRUSTED,
            evidence=evidence,
            certified=certified,
            clip_approved=True,
            quarantine=None,
            message="Object verified, certified, clipped, and trusted.",
            verification_result="VERIFY_PASSED",
            after_state=TrustStatus.TRUSTED.value,
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
    ) -> TrustGateResult:
        self.ledger.append(
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
                },
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
        )
