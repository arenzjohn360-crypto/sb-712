from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


class TrustStage(str, Enum):
    UNKNOWN = "unknown"
    VERIFIED = "verified"
    RE_VERIFIED = "re_verified"
    CERTIFIED = "certified"
    TRUSTED = "trusted"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class TrustEvidence:
    stage: TrustStage
    source: str
    result: bool
    note: str = ""
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class TrustGate:
    """
    SB-712 Rule of Three Trust Gate.

    Nothing becomes trusted until it has passed:

    1. Verification
    2. Re-Verification
    3. Certification

    Any failure quarantines the object.
    """

    object_id: str
    payload: Any = None
    stage: TrustStage = TrustStage.UNKNOWN
    evidence: List[TrustEvidence] = field(default_factory=list)

    def verify(self, source: str, result: bool, note: str = "") -> TrustStage:
        return self._advance(
            expected_current=TrustStage.UNKNOWN,
            next_stage=TrustStage.VERIFIED,
            source=source,
            result=result,
            note=note,
        )

    def re_verify(self, source: str, result: bool, note: str = "") -> TrustStage:
        return self._advance(
            expected_current=TrustStage.VERIFIED,
            next_stage=TrustStage.RE_VERIFIED,
            source=source,
            result=result,
            note=note,
        )

    def certify(self, source: str, result: bool, note: str = "") -> TrustStage:
        self._advance(
            expected_current=TrustStage.RE_VERIFIED,
            next_stage=TrustStage.CERTIFIED,
            source=source,
            result=result,
            note=note,
        )

        self.stage = TrustStage.TRUSTED
        self.evidence.append(
            TrustEvidence(
                stage=TrustStage.TRUSTED,
                source="trust_gate",
                result=True,
                note="Object promoted to trusted state after verification, re-verification, and certification.",
            )
        )
        return self.stage

    def quarantine(self, source: str, note: str = "") -> TrustStage:
        self.stage = TrustStage.QUARANTINED
        self.evidence.append(
            TrustEvidence(
                stage=TrustStage.QUARANTINED,
                source=source,
                result=False,
                note=note,
            )
        )
        return self.stage

    @property
    def is_trusted(self) -> bool:
        return self.stage == TrustStage.TRUSTED

    @property
    def is_quarantined(self) -> bool:
        return self.stage == TrustStage.QUARANTINED

    def report(self) -> Dict[str, Any]:
        return {
            "object_id": self.object_id,
            "stage": self.stage.value,
            "trusted": self.is_trusted,
            "quarantined": self.is_quarantined,
            "evidence_count": len(self.evidence),
            "evidence": [
                {
                    "stage": item.stage.value,
                    "source": item.source,
                    "result": item.result,
                    "note": item.note,
                    "timestamp_utc": item.timestamp_utc,
                }
                for item in self.evidence
            ],
        }

    def _advance(
        self,
        expected_current: TrustStage,
        next_stage: TrustStage,
        source: str,
        result: bool,
        note: str,
    ) -> TrustStage:
        if self.stage == TrustStage.QUARANTINED:
            return self.stage

        if self.stage != expected_current:
            return self.quarantine(
                source=source,
                note=f"Invalid trust transition from {self.stage.value}; expected {expected_current.value}.",
            )

        self.evidence.append(
            TrustEvidence(
                stage=next_stage,
                source=source,
                result=result,
                note=note,
            )
        )

        if not result:
            return self.quarantine(
                source=source,
                note=f"{next_stage.value} failed. Object remains untrusted.",
            )

        self.stage = next_stage
        return self.stage
