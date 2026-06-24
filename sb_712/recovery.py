"""
SB-712 Recovery Engine
======================

Primary method : Recovery Convoy
    Master Phoenix → Hunters → Warriors → Repair Nodes →
    Truth/Verification → Certification →
    Return-Check Loop (Certification → Re-Verify → Confirm Repair →
                       Warrior Release → Hunter Rescan → Phoenix Closure)

Fallback method : Emergency Rollback to last healthy certified checkpoint.

Decision rule (locked law):
    If damage is local  → repair it (convoy).
    If damage spreading → contain it (convoy).
    If truth cannot be proven → rollback.
    If any rollback trigger is present → rollback immediately.
    If convoy fails or max attempts exceeded → rollback.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from .incident import IncidentStudyRecord, IncidentType, HUNTER_RESCAN_REOPEN_OUTCOMES
from .checkpoint import CheckpointRegistry, RollbackResult

# Maximum times the convoy will loop before escalating to rollback.
MAX_CONVOY_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Forward-pass stages
# ---------------------------------------------------------------------------

class ConvoyStage(Enum):
    HUNT = "HUNT"
    CONTAIN = "CONTAIN"
    REPAIR = "REPAIR"
    VERIFY = "VERIFY"
    CERTIFY = "CERTIFY"


@dataclass
class ConvoyStageResult:
    stage: ConvoyStage
    success: bool
    message: str = ""


# ---------------------------------------------------------------------------
# Return-check-loop stages
# ---------------------------------------------------------------------------

class ReturnCheckStage(Enum):
    RECHECK_TRUTH = "RECHECK_TRUTH"
    CONFIRM_REPAIR = "CONFIRM_REPAIR"
    WARRIOR_RELEASE = "WARRIOR_RELEASE"
    HUNTER_RESCAN = "HUNTER_RESCAN"
    PHOENIX_CLOSURE = "PHOENIX_CLOSURE"


@dataclass
class ReturnCheckStageResult:
    stage: ReturnCheckStage
    success: bool
    message: str = ""


class PhoenixDecision(Enum):
    CLOSED = "CLOSED"
    REOPEN_CONVOY = "REOPEN_CONVOY"


@dataclass
class ReturnCheckResult:
    success: bool
    stages: List[ReturnCheckStageResult] = field(default_factory=list)
    phoenix_decision: PhoenixDecision = PhoenixDecision.CLOSED
    failed_stage: Optional[ReturnCheckStage] = None
    message: str = ""


# ---------------------------------------------------------------------------
# Top-level convoy result
# ---------------------------------------------------------------------------

@dataclass
class ConvoyResult:
    success: bool
    forward_stages: List[ConvoyStageResult] = field(default_factory=list)
    return_check: Optional[ReturnCheckResult] = None
    failed_stage: Optional[ConvoyStage] = None
    convoy_attempts: int = 1
    message: str = ""


# ---------------------------------------------------------------------------
# Recovery method + final result
# ---------------------------------------------------------------------------

class RecoveryMethod(Enum):
    CONVOY = "convoy"
    ROLLBACK = "rollback"


@dataclass
class RecoveryResult:
    method_used: RecoveryMethod
    success: bool
    project_id: str
    incident_id: str
    convoy_result: Optional[ConvoyResult] = None
    rollback_result: Optional[RollbackResult] = None
    completed_at: datetime = field(default_factory=datetime.utcnow)
    notes: str = ""


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

def _decide_method(incident: IncidentStudyRecord) -> RecoveryMethod:
    """
    Pre-flight check: some conditions mandate immediate rollback.

    Use convoy when:
        one project folder breaks, one payment record is missing,
        one proof report fails, one file corrupts, one route drifts,
        one module acts wrong, one log does not match.

    Use rollback when:
        the Spine is threatened, the ledger is corrupted,
        multiple nodes disagree, checkpoint lineage is unclear,
        truth cannot be verified, the same problem keeps returning,
        damage spreads across programs, Master Phoenix loses confidence.
    """
    if incident.spine_threatened:
        return RecoveryMethod.ROLLBACK
    if incident.ledger_corrupted:
        return RecoveryMethod.ROLLBACK
    if incident.nodes_disagree:
        return RecoveryMethod.ROLLBACK
    if incident.checkpoint_lineage_unclear:
        return RecoveryMethod.ROLLBACK
    if not incident.master_phoenix_confidence:
        return RecoveryMethod.ROLLBACK
    if incident.incident_type == IncidentType.REPEATED_ATTACK:
        return RecoveryMethod.ROLLBACK
    return RecoveryMethod.CONVOY


# ---------------------------------------------------------------------------
# Forward-pass convoy
# ---------------------------------------------------------------------------

class _ForwardConvoy:
    """Runs the five forward stages: Hunt → Contain → Repair → Verify → Certify."""

    def run(self, incident: IncidentStudyRecord) -> tuple:
        """Returns (success, List[ConvoyStageResult], failed_stage_or_None, message)."""
        stages: List[ConvoyStageResult] = []
        for stage in ConvoyStage:
            result = self._run_stage(stage, incident)
            stages.append(result)
            if not result.success:
                return False, stages, stage, f"Forward convoy failed at {stage.value}: {result.message}"
        return True, stages, None, "Forward convoy complete."

    def _run_stage(self, stage: ConvoyStage, incident: IncidentStudyRecord) -> ConvoyStageResult:
        handlers = {
            ConvoyStage.HUNT: self._hunt,
            ConvoyStage.CONTAIN: self._contain,
            ConvoyStage.REPAIR: self._repair,
            ConvoyStage.VERIFY: self._verify,
            ConvoyStage.CERTIFY: self._certify,
        }
        return handlers[stage](incident)

    def _hunt(self, incident: IncidentStudyRecord) -> ConvoyStageResult:
        return ConvoyStageResult(
            stage=ConvoyStage.HUNT,
            success=True,
            message=(
                f"Hunters located {incident.incident_type.value} "
                f"in {incident.location or 'unknown location'}."
            ),
        )

    def _contain(self, incident: IncidentStudyRecord) -> ConvoyStageResult:
        if incident.damage_is_spreading:
            msg = "Warriors contained spreading damage. Lockdown active."
        else:
            msg = "Warriors confirmed local damage. No spread detected."
        return ConvoyStageResult(stage=ConvoyStage.CONTAIN, success=True, message=msg)

    def _repair(self, incident: IncidentStudyRecord) -> ConvoyStageResult:
        if incident.repair_action:
            return ConvoyStageResult(
                stage=ConvoyStage.REPAIR,
                success=True,
                message=f"Repair nodes applied: {incident.repair_action}",
            )
        return ConvoyStageResult(
            stage=ConvoyStage.REPAIR,
            success=False,
            message="No repair action defined. Cannot proceed.",
        )

    def _verify(self, incident: IncidentStudyRecord) -> ConvoyStageResult:
        if incident.truth_verified:
            return ConvoyStageResult(
                stage=ConvoyStage.VERIFY,
                success=True,
                message="Truth verified. Repair confirmed by verification nodes.",
            )
        return ConvoyStageResult(
            stage=ConvoyStage.VERIFY,
            success=False,
            message="Truth could not be verified. Convoy cannot certify.",
        )

    def _certify(self, incident: IncidentStudyRecord) -> ConvoyStageResult:
        if incident.certification_result:
            return ConvoyStageResult(
                stage=ConvoyStage.CERTIFY,
                success=True,
                message=f"Certification nodes sealed state: {incident.certification_result}",
            )
        return ConvoyStageResult(
            stage=ConvoyStage.CERTIFY,
            success=False,
            message="No certification result provided. State not sealed.",
        )


# ---------------------------------------------------------------------------
# Return-check loop
# ---------------------------------------------------------------------------

class _ReturnCheck:
    """
    Runs the return-check loop after certification.

    The repaired state travels back through the chain:
        Certification → Re-Verify Truth → Confirm Repair →
        Warrior Release → Hunter Rescan → Phoenix Closure.

    If Hunter Rescan finds the problem still active, Phoenix reopens the convoy.
    If all stages pass, Phoenix closes the incident.
    """

    def run(self, incident: IncidentStudyRecord) -> ReturnCheckResult:
        stages: List[ReturnCheckStageResult] = []
        for stage in ReturnCheckStage:
            result = self._run_stage(stage, incident)
            stages.append(result)
            if not result.success:
                # Hunter rescan failure means reopen, not a hard stop.
                if stage == ReturnCheckStage.HUNTER_RESCAN:
                    return ReturnCheckResult(
                        success=False,
                        stages=stages,
                        phoenix_decision=PhoenixDecision.REOPEN_CONVOY,
                        failed_stage=stage,
                        message=f"Hunter rescan requires convoy reopen: {result.message}",
                    )
                return ReturnCheckResult(
                    success=False,
                    stages=stages,
                    phoenix_decision=PhoenixDecision.REOPEN_CONVOY,
                    failed_stage=stage,
                    message=f"Return check failed at {stage.value}: {result.message}",
                )
        return ReturnCheckResult(
            success=True,
            stages=stages,
            phoenix_decision=PhoenixDecision.CLOSED,
            message="Return check passed. Master Phoenix closes the incident.",
        )

    def _run_stage(
        self, stage: ReturnCheckStage, incident: IncidentStudyRecord
    ) -> ReturnCheckStageResult:
        handlers = {
            ReturnCheckStage.RECHECK_TRUTH: self._recheck_truth,
            ReturnCheckStage.CONFIRM_REPAIR: self._confirm_repair,
            ReturnCheckStage.WARRIOR_RELEASE: self._warrior_release,
            ReturnCheckStage.HUNTER_RESCAN: self._hunter_rescan,
            ReturnCheckStage.PHOENIX_CLOSURE: self._phoenix_closure,
        }
        return handlers[stage](incident)

    def _recheck_truth(self, incident: IncidentStudyRecord) -> ReturnCheckStageResult:
        """Truth/Verification nodes recheck the repaired state."""
        if incident.truth_verified:
            return ReturnCheckStageResult(
                stage=ReturnCheckStage.RECHECK_TRUTH,
                success=True,
                message="Repaired state is still true. No state drift after repair.",
            )
        return ReturnCheckStageResult(
            stage=ReturnCheckStage.RECHECK_TRUTH,
            success=False,
            message="Repaired state could not be re-verified. Truth check failed.",
        )

    def _confirm_repair(self, incident: IncidentStudyRecord) -> ReturnCheckStageResult:
        """Repair nodes confirm that folders, records, routes, and pieces held."""
        if incident.repair_action:
            return ReturnCheckStageResult(
                stage=ReturnCheckStage.CONFIRM_REPAIR,
                success=True,
                message=f"Repair confirmed intact: {incident.repair_action}",
            )
        return ReturnCheckStageResult(
            stage=ReturnCheckStage.CONFIRM_REPAIR,
            success=False,
            message="Repair action missing. Cannot confirm repair held.",
        )

    def _warrior_release(self, incident: IncidentStudyRecord) -> ReturnCheckStageResult:
        """Warriors decide whether the lockdown can lift."""
        if incident.damage_is_spreading or incident.spine_threatened:
            return ReturnCheckStageResult(
                stage=ReturnCheckStage.WARRIOR_RELEASE,
                success=False,
                message="Warriors holding lockdown: damage still spreading or Spine threatened.",
            )
        return ReturnCheckStageResult(
            stage=ReturnCheckStage.WARRIOR_RELEASE,
            success=True,
            message="Warriors confirm threat is gone. Lockdown released. Spine safe.",
        )

    def _hunter_rescan(self, incident: IncidentStudyRecord) -> ReturnCheckStageResult:
        """Hunters sweep the repaired area again."""
        outcome = incident.hunter_rescan_outcome

        if outcome is None or outcome == "problem_gone":
            return ReturnCheckStageResult(
                stage=ReturnCheckStage.HUNTER_RESCAN,
                success=True,
                message="Hunters confirm: problem gone. Area is clean.",
            )
        if outcome == "false_alarm":
            return ReturnCheckStageResult(
                stage=ReturnCheckStage.HUNTER_RESCAN,
                success=True,
                message="Hunters confirm: false alarm. No actual damage found.",
            )
        if outcome in HUNTER_RESCAN_REOPEN_OUTCOMES:
            return ReturnCheckStageResult(
                stage=ReturnCheckStage.HUNTER_RESCAN,
                success=False,
                message=f"Hunters report: {outcome}. Convoy must reopen.",
            )
        # Unknown outcome — treat conservatively as a reopen trigger.
        return ReturnCheckStageResult(
            stage=ReturnCheckStage.HUNTER_RESCAN,
            success=False,
            message=f"Hunter rescan outcome unknown: '{outcome}'. Reopening convoy.",
        )

    def _phoenix_closure(self, incident: IncidentStudyRecord) -> ReturnCheckStageResult:
        """Master Phoenix makes the final call: CLOSED."""
        return ReturnCheckStageResult(
            stage=ReturnCheckStage.PHOENIX_CLOSURE,
            success=True,
            message="Master Phoenix closes the incident. Recovery complete.",
        )


# ---------------------------------------------------------------------------
# Full convoy (forward + return-check, with reopen loop)
# ---------------------------------------------------------------------------

class ConvoyRecovery:
    """
    Runs the full convoy:
        Forward pass  → Hunters → Warriors → Repair → Verify → Certify
        Return check  → Re-Verify → Confirm Repair → Warrior Release
                        → Hunter Rescan → Phoenix Closure

    If Phoenix decides REOPEN_CONVOY, the convoy runs again (up to MAX_CONVOY_ATTEMPTS).
    If the convoy exhausts all attempts, the caller should escalate to rollback.
    """

    def __init__(self) -> None:
        self._forward = _ForwardConvoy()
        self._return_check = _ReturnCheck()

    def run(self, incident: IncidentStudyRecord) -> ConvoyResult:
        attempt = 0
        last_return_check: Optional[ReturnCheckResult] = None

        while attempt < MAX_CONVOY_ATTEMPTS:
            attempt += 1

            # Forward pass
            fwd_ok, fwd_stages, failed_stage, fwd_msg = self._forward.run(incident)
            if not fwd_ok:
                return ConvoyResult(
                    success=False,
                    forward_stages=fwd_stages,
                    failed_stage=failed_stage,
                    convoy_attempts=attempt,
                    message=fwd_msg,
                )

            # Return-check loop
            rc = self._return_check.run(incident)
            last_return_check = rc

            if rc.success and rc.phoenix_decision == PhoenixDecision.CLOSED:
                return ConvoyResult(
                    success=True,
                    forward_stages=fwd_stages,
                    return_check=rc,
                    convoy_attempts=attempt,
                    message="Convoy complete. Phoenix closed the incident.",
                )

            # Phoenix said REOPEN — loop again if attempts remain.
            if attempt >= MAX_CONVOY_ATTEMPTS:
                break

        # Exhausted all attempts.
        return ConvoyResult(
            success=False,
            forward_stages=[],
            return_check=last_return_check,
            convoy_attempts=attempt,
            message=(
                f"Convoy exhausted {MAX_CONVOY_ATTEMPTS} attempt(s) without closure. "
                "Escalating to emergency rollback."
            ),
        )


# ---------------------------------------------------------------------------
# Recovery Orchestrator
# ---------------------------------------------------------------------------

class RecoveryOrchestrator:
    """
    Primary method  : ConvoyRecovery (intelligent, surgical repair).
    Fallback method : Emergency rollback to last healthy certified checkpoint.

    Locked Recovery Law:
        Hunters find it.
        Warriors contain it.
        Repair nodes fix it.
        Truth verifies it.
        Certification seals it.
        Return-check proves it stayed fixed.
        Master Phoenix closes it.
        If any part fails, Phoenix rolls back to the last healthy certified checkpoint.
    """

    def __init__(self, checkpoint_registry: CheckpointRegistry) -> None:
        self.checkpoint_registry = checkpoint_registry
        self._convoy = ConvoyRecovery()

    def decide_method(self, incident: IncidentStudyRecord) -> RecoveryMethod:
        return _decide_method(incident)

    def recover(self, incident: IncidentStudyRecord) -> RecoveryResult:
        method = self.decide_method(incident)

        if method == RecoveryMethod.ROLLBACK:
            return self._do_rollback(
                incident, reason="Pre-flight rollback trigger detected."
            )

        # Attempt the full convoy (forward + return-check loop).
        convoy_result = self._convoy.run(incident)

        if convoy_result.success:
            return RecoveryResult(
                method_used=RecoveryMethod.CONVOY,
                success=True,
                project_id=incident.project_id,
                incident_id=incident.incident_id,
                convoy_result=convoy_result,
                notes="Convoy recovery succeeded. Incident closed by Master Phoenix.",
            )

        # Convoy failed — emergency rollback.
        rollback_result = self.checkpoint_registry.rollback(
            incident.project_id,
            reason=convoy_result.message,
        )
        return RecoveryResult(
            method_used=RecoveryMethod.ROLLBACK,
            success=rollback_result.success,
            project_id=incident.project_id,
            incident_id=incident.incident_id,
            convoy_result=convoy_result,
            rollback_result=rollback_result,
            notes=(
                "Convoy failed. Emergency rollback to last healthy certified checkpoint. "
                "The extinguisher is off the wall."
            ),
        )

    def _do_rollback(
        self, incident: IncidentStudyRecord, reason: str
    ) -> RecoveryResult:
        rollback_result = self.checkpoint_registry.rollback(
            incident.project_id, reason=reason
        )
        return RecoveryResult(
            method_used=RecoveryMethod.ROLLBACK,
            success=rollback_result.success,
            project_id=incident.project_id,
            incident_id=incident.incident_id,
            rollback_result=rollback_result,
            notes=reason,
        )
