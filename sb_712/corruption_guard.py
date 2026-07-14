"""
SB-712 Corruption Guard
=======================

The CorruptionGuard is the aggressive, always-on interceptor that sits at the
boundary of every processing step.

Responsibilities (in order):
    1. INTERCEPT — detect corruption the moment an incident is raised.
    2. CONTAIN    — if damage is spreading, issue an immediate spread lock;
                   no further processing is permitted until the lock clears.
    3. LEARN      — run the LearningNode pipeline to classify, derive root
                   cause, build prevention rules, and update hunter patterns.
    4. IMMUNISE   — run the ImmunityNode to convert the lesson into hard
                   defences (tighter gates, quarantine triggers, hunter
                   detection updates).
    5. RECOVER    — run the RecoveryOrchestrator to repair or roll back.
    6. RESTORE    — mark the incident node/object as HEALTHY once recovery
                   succeeds.
    7. RECORD     — persist every lesson to disk via LessonStore so
                   knowledge survives restarts.

Architecture position:
    Windows OS
        ↕
    SB-712 CorruptionGuard  ← this module (watchdog layer)
        ↕
    SB-689 FreeFlowPipeline ← fast, unrestricted processing
        ↕
    SB-688 data integrity   ← bottom integrity kernel
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .checkpoint import CheckpointRegistry
from .immunity_node import ImmunityNode
from .incident import IncidentStudyRecord, IncidentStatus, Severity
from .learning_node import LearningNode
from .lesson_store import LessonStore
from .prevention import PreventionRegistry
from .recovery import RecoveryMethod, RecoveryOrchestrator, RecoveryResult


@dataclass
class GuardResult:
    """Full record of a single guard cycle."""

    incident_id: str
    spread_locked: bool
    learned: bool
    immunised: bool
    recovery_method: Optional[str]
    recovery_success: bool
    restored_to_healthy: bool
    lesson_file: Optional[str]
    completed_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    notes: str = ""


class CorruptionGuard:
    """
    Aggressive, self-contained corruption interceptor.

    Parameters
    ----------
    checkpoint_registry : CheckpointRegistry
        The registry used by RecoveryOrchestrator for rollbacks.
    lesson_store : LessonStore, optional
        Where to persist learned lessons.  If *None*, a default store
        writing to ``./lessons/`` is created.
    """

    def __init__(
        self,
        checkpoint_registry: CheckpointRegistry,
        lesson_store: Optional[LessonStore] = None,
    ) -> None:
        self._prevention_registry = PreventionRegistry()
        self._learner = LearningNode(self._prevention_registry)
        self._immunity = ImmunityNode(self._prevention_registry)
        self._recovery = RecoveryOrchestrator(checkpoint_registry)
        self._lesson_store = lesson_store or LessonStore()
        self._spread_locks: set = set()

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def intercept(self, incident: IncidentStudyRecord) -> GuardResult:
        """
        Run the full guard cycle for *incident*.

        Steps: Intercept → Contain → Learn → Immunise → Recover → Restore → Record.
        """
        spread_locked = self._contain(incident)
        lesson_report = self._learn(incident)
        self._immunise(incident)
        recovery_result = self._recover(incident)
        restored = self._restore_if_healed(incident, recovery_result)
        lesson_file = self._record(incident, lesson_report)

        return GuardResult(
            incident_id=incident.incident_id,
            spread_locked=spread_locked,
            learned=True,
            immunised=True,
            recovery_method=(
                recovery_result.method_used.value if recovery_result else None
            ),
            recovery_success=bool(recovery_result and recovery_result.success),
            restored_to_healthy=restored,
            lesson_file=lesson_file,
            notes=self._build_notes(incident, recovery_result, spread_locked),
        )

    # ------------------------------------------------------------------
    # Stage 1: CONTAIN
    # ------------------------------------------------------------------

    def _contain(self, incident: IncidentStudyRecord) -> bool:
        """
        If damage is spreading, immediately issue a spread lock.

        A spread lock is registered against the project_id.  Downstream
        callers can query ``is_spread_locked()`` to honour the lock.
        For CRITICAL incidents, the lock fires regardless of the spreading
        flag — early, aggressive containment.
        """
        should_lock = incident.damage_is_spreading or (
            incident.severity == Severity.CRITICAL and not incident.damage_is_local
        )
        if should_lock:
            self._spread_locks.add(incident.project_id)
            incident.containment_action = (
                "SPREAD LOCK ENGAGED: all outbound processing for "
                f"project {incident.project_id} halted until guard clears."
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Stage 2: LEARN
    # ------------------------------------------------------------------

    def _learn(self, incident: IncidentStudyRecord) -> str:
        return self._learner.process(incident)

    # ------------------------------------------------------------------
    # Stage 3: IMMUNISE
    # ------------------------------------------------------------------

    def _immunise(self, incident: IncidentStudyRecord) -> None:
        self._immunity.apply_immunity(incident)

    # ------------------------------------------------------------------
    # Stage 4: RECOVER
    # ------------------------------------------------------------------

    def _recover(self, incident: IncidentStudyRecord) -> Optional[RecoveryResult]:
        try:
            return self._recovery.recover(incident)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Stage 5: RESTORE
    # ------------------------------------------------------------------

    def _restore_if_healed(
        self,
        incident: IncidentStudyRecord,
        recovery_result: Optional[RecoveryResult],
    ) -> bool:
        """
        If recovery succeeded, mark the incident CLOSED and lift the
        spread lock for its project.
        """
        if recovery_result and recovery_result.success:
            incident.status = IncidentStatus.CLOSED
            self._spread_locks.discard(incident.project_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Stage 6: RECORD
    # ------------------------------------------------------------------

    def _record(self, incident: IncidentStudyRecord, report_text: str) -> Optional[str]:
        try:
            return self._lesson_store.record(incident, report_text)
        except OSError:
            return None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def is_spread_locked(self, project_id: str) -> bool:
        """Return True if a spread lock is currently active for *project_id*."""
        return project_id in self._spread_locks

    def lift_spread_lock(self, project_id: str) -> None:
        """Manually lift the spread lock for *project_id* (e.g. after operator review)."""
        self._spread_locks.discard(project_id)

    @property
    def prevention_registry(self) -> PreventionRegistry:
        return self._prevention_registry

    @property
    def lesson_store(self) -> LessonStore:
        return self._lesson_store

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_notes(
        self,
        incident: IncidentStudyRecord,
        recovery_result: Optional[RecoveryResult],
        spread_locked: bool,
    ) -> str:
        parts = []
        if spread_locked:
            parts.append("Spread lock engaged.")
        if recovery_result:
            parts.append(
                f"Recovery: {recovery_result.method_used.value} — "
                f"{'OK' if recovery_result.success else 'FAILED'}."
            )
        if incident.prevention_rule_added:
            parts.append(f"Rule added: {incident.prevention_rule_added[:80]}")
        return " | ".join(parts) if parts else "Guard cycle complete."
