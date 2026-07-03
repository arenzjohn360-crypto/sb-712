from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from .data_contracts import canonical_hash, utcnow


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    lineage_id: str
    category: str
    payload: Dict[str, Any]
    created_at: datetime = field(default_factory=utcnow)
    integrity_hash: str = ""
    previous_hash: str = ""


class EvidenceVault:
    """Append-only cold evidence store with lineage and category indexes."""

    def __init__(self) -> None:
        self._records: List[EvidenceRecord] = []
        self._by_lineage: Dict[str, List[str]] = {}
        self._by_category: Dict[str, List[str]] = {}

    def append(self, evidence_id: str, lineage_id: str, category: str, payload: Mapping[str, Any]) -> EvidenceRecord:
        previous_hash = self._records[-1].integrity_hash if self._records else "GENESIS"
        payload_dict = dict(payload)
        integrity_hash = canonical_hash(
            [
                evidence_id,
                lineage_id,
                category,
                repr(sorted(payload_dict.items())),
                previous_hash,
            ]
        )
        record = EvidenceRecord(
            evidence_id=evidence_id,
            lineage_id=lineage_id,
            category=category,
            payload=payload_dict,
            previous_hash=previous_hash,
            integrity_hash=integrity_hash,
        )
        self._records.append(record)
        self._by_lineage.setdefault(lineage_id, []).append(evidence_id)
        self._by_category.setdefault(category, []).append(evidence_id)
        return record

    def by_lineage(self, lineage_id: str) -> List[EvidenceRecord]:
        ids = set(self._by_lineage.get(lineage_id, []))
        return [record for record in self._records if record.evidence_id in ids]

    def by_category(self, category: str) -> List[EvidenceRecord]:
        ids = set(self._by_category.get(category, []))
        return [record for record in self._records if record.evidence_id in ids]

    def latest(self) -> Optional[EvidenceRecord]:
        return self._records[-1] if self._records else None

    def verify_integrity(self) -> bool:
        previous_hash = "GENESIS"
        for record in self._records:
            expected_hash = canonical_hash(
                [
                    record.evidence_id,
                    record.lineage_id,
                    record.category,
                    repr(sorted(record.payload.items())),
                    previous_hash,
                ]
            )
            if record.previous_hash != previous_hash or record.integrity_hash != expected_hash:
                return False
            previous_hash = record.integrity_hash
        return True
