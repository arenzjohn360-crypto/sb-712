from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from .data_contracts import CANONICAL_SCHEMA_VERSION, DataContractValidator, canonical_hash


class CheckpointStatus(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CORRUPTED = "CORRUPTED"


@dataclass
class Checkpoint:
    project_id: str
    status: CheckpointStatus
    certified: bool
    snapshot: Dict[str, Any] = field(default_factory=dict)
    checkpoint_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)
    notes: str = ""
    schema_version: int = CANONICAL_SCHEMA_VERSION
    integrity_proof: str = ""
    lineage_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent_lineage_id: Optional[str] = None
    confidence_score: float = 1.0
    verification_depth: int = 3
    dependency_fingerprint: str = ""

    def __post_init__(self) -> None:
        DataContractValidator.validate_contract(
            object_id=self.checkpoint_id,
            source="checkpoint_registry",
            schema_version=self.schema_version,
            lineage_id=self.lineage_id,
        )
        if self.verification_depth < 1:
            raise ValueError("verification_depth must be >= 1")
        if not (0.0 <= self.confidence_score <= 1.0):
            raise ValueError("confidence_score must be between 0.0 and 1.0")
        if not self.dependency_fingerprint:
            self.dependency_fingerprint = canonical_hash(
                [
                    self.project_id,
                    repr(sorted(self.snapshot.items())),
                ]
            )
        if not self.integrity_proof:
            self.integrity_proof = canonical_hash(
                [
                    self.checkpoint_id,
                    self.project_id,
                    self.status.value,
                    str(self.certified),
                    self.created_at.isoformat(),
                    self.lineage_id,
                    self.dependency_fingerprint,
                    str(self.schema_version),
                ]
            )


@dataclass
class RollbackResult:
    success: bool
    checkpoint_id: Optional[str]
    project_id: str
    rolled_back_at: datetime = field(default_factory=datetime.utcnow)
    reason: str = ""
    message: str = ""
    selected_quality_score: float = 0.0


class CheckpointRegistry:
    """
    Manages certified checkpoints and executes emergency rollbacks.

    This is the emergency fallback ("fire extinguisher on the wall").
    When the recovery convoy cannot fix an incident, the system rolls back
    to the last healthy certified checkpoint.
    """

    def __init__(self) -> None:
        self._checkpoints: List[Checkpoint] = []

    def add_checkpoint(self, checkpoint: Checkpoint) -> None:
        DataContractValidator.validate_contract(
            object_id=checkpoint.checkpoint_id,
            source="checkpoint_registry",
            schema_version=checkpoint.schema_version,
            lineage_id=checkpoint.lineage_id,
        )
        self._checkpoints.append(checkpoint)

    def get_last_healthy_certified(self, project_id: str) -> Optional[Checkpoint]:
        candidates = [
            c for c in self._checkpoints
            if c.project_id == project_id
            and c.certified
            and c.status == CheckpointStatus.HEALTHY
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda c: (self._quality_score(c), c.created_at))[-1]

    def _quality_score(self, checkpoint: Checkpoint) -> float:
        depth_component = min(checkpoint.verification_depth / 10.0, 1.0)
        certified_component = 1.0 if checkpoint.certified else 0.0
        status_component = 1.0 if checkpoint.status == CheckpointStatus.HEALTHY else 0.0
        return (checkpoint.confidence_score * 0.6) + (depth_component * 0.3) + (certified_component * status_component * 0.1)

    def rollback(self, project_id: str, reason: str = "") -> RollbackResult:
        target = self.get_last_healthy_certified(project_id)
        if target is None:
            return RollbackResult(
                success=False,
                checkpoint_id=None,
                project_id=project_id,
                reason=reason,
                message="No healthy certified checkpoint found for rollback.",
            )
        return RollbackResult(
            success=True,
            checkpoint_id=target.checkpoint_id,
            project_id=project_id,
            reason=reason,
            selected_quality_score=self._quality_score(target),
            message=(
                f"Project {project_id} rolled back to checkpoint "
                f"{target.checkpoint_id} from {target.created_at.isoformat()}."
            ),
        )

    def all_checkpoints(self, project_id: Optional[str] = None) -> List[Checkpoint]:
        if project_id is None:
            return list(self._checkpoints)
        return [c for c in self._checkpoints if c.project_id == project_id]
