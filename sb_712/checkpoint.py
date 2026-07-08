from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


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
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str = ""


@dataclass
class RollbackResult:
    success: bool
    checkpoint_id: Optional[str]
    project_id: str
    rolled_back_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str = ""
    message: str = ""


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
        return sorted(candidates, key=lambda c: c.created_at)[-1]

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
            message=(
                f"Project {project_id} rolled back to checkpoint "
                f"{target.checkpoint_id} from {target.created_at.isoformat()}."
            ),
        )

    def all_checkpoints(self, project_id: Optional[str] = None) -> List[Checkpoint]:
        if project_id is None:
            return list(self._checkpoints)
        return [c for c in self._checkpoints if c.project_id == project_id]
