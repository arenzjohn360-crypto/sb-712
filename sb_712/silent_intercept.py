"""
SB-712 T-800 Silent Intercept
==============================

Silent intercept mode — the system's "T-800" operation.

When a threat is first detected, the default response is immediate quarantine.
Silent Intercept takes a different path:

    1. SHADOW    — mirror the threat's environment without touching it.
    2. HONEYPOT  — serve the threat believable decoy data and study its behaviour.
    3. STUDYING  — record every pattern the threat exhibits.
    4. SILENCED  — once patterns are fully classified, freeze the threat covertly.
    5. PURGED    — remove it cleanly; bank all new patterns for future immunity.

Why silence instead of immediate quarantine?
Premature quarantine alerts the attacker.  Silent intercept lets the
threat fully expose its capabilities before it can pivot or go dormant.
Once we know everything it does, we purge it and arm the system with its
own signature — it cannot use the same approach twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
import uuid


class InterceptPhase(Enum):
    SHADOW = "SHADOW"
    HONEYPOT = "HONEYPOT"
    STUDYING = "STUDYING"
    SILENCED = "SILENCED"
    PURGED = "PURGED"


class InterceptDecision(Enum):
    CONTINUE_STUDY = "CONTINUE_STUDY"
    SILENCE_AND_PURGE = "SILENCE_AND_PURGE"
    ESCALATE_TO_GUARD = "ESCALATE_TO_GUARD"


@dataclass
class ThreatBehaviourRecord:
    """Everything the threat did while under silent observation."""

    threat_id: str
    patterns_observed: List[str] = field(default_factory=list)
    access_attempts: int = 0
    decoys_consumed: int = 0
    exfiltration_attempted: bool = False
    privilege_escalation_attempted: bool = False
    lateral_movement_detected: bool = False

    def add_pattern(self, pattern: str) -> None:
        if pattern not in self.patterns_observed:
            self.patterns_observed.append(pattern)

    @property
    def threat_score(self) -> float:
        """0.0 (benign) → 1.0 (fully hostile)."""
        score = min(self.access_attempts / 10.0, 0.4)
        if self.exfiltration_attempted:
            score += 0.3
        if self.privilege_escalation_attempted:
            score += 0.2
        if self.lateral_movement_detected:
            score += 0.1
        return min(score, 1.0)


@dataclass
class SilentInterceptResult:
    """Complete record of one silent intercept cycle."""

    threat_id: str
    final_phase: InterceptPhase
    behaviour: ThreatBehaviourRecord
    decision: InterceptDecision
    patterns_banked: List[str]
    deception_success: bool
    purged: bool
    lesson_summary: str
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SilentInterceptNode:
    """
    T-800 silent intercept pipeline.

    Operates in up to five phases:
        SHADOW   → observe without touching
        HONEYPOT → serve decoy data while threat believes it has access
        STUDYING → classify behaviour patterns
        SILENCED → freeze the threat covertly; it does not know it is caught
        PURGED   → eliminate cleanly; bank all new signatures

    The node escalates to CorruptionGuard only when the threat score
    is so high that continued study is dangerous.

    Knowledge sharing
    -----------------
    All banked patterns can be exported and imported between peer nodes
    (quantum-inspired pairs), so a new threat seen on one node is
    immediately recognised on its partner.
    """

    # Threat score at or above which study stops and purge fires immediately.
    ESCALATION_THRESHOLD: float = 0.85

    # Minimum access attempts before the honeypot / study phase begins.
    HONEYPOT_MIN_ATTEMPTS: int = 2

    def __init__(self) -> None:
        self._banked_patterns: List[str] = []
        self._intercept_log: Dict[str, SilentInterceptResult] = {}

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def intercept(
        self,
        threat_id: str,
        access_attempts: int = 1,
        exfiltration: bool = False,
        privilege_escalation: bool = False,
        lateral_movement: bool = False,
        observed_patterns: Optional[List[str]] = None,
    ) -> SilentInterceptResult:
        """
        Run the full silent intercept pipeline for a detected threat.

        Returns
        -------
        SilentInterceptResult
            Full record of the intercept cycle, including the decision taken
            and every pattern that was banked.
        """
        behaviour = ThreatBehaviourRecord(
            threat_id=threat_id,
            access_attempts=access_attempts,
            exfiltration_attempted=exfiltration,
            privilege_escalation_attempted=privilege_escalation,
            lateral_movement_detected=lateral_movement,
        )
        for pat in (observed_patterns or []):
            behaviour.add_pattern(pat)

        phase = self._advance_phase(behaviour)
        decision = self._decide(behaviour, phase)
        deception_success = self._run_honeypot(behaviour, phase)
        new_patterns = self._bank_patterns(behaviour)

        purged = decision == InterceptDecision.SILENCE_AND_PURGE
        if purged:
            phase = InterceptPhase.PURGED

        result = SilentInterceptResult(
            threat_id=threat_id,
            final_phase=phase,
            behaviour=behaviour,
            decision=decision,
            patterns_banked=new_patterns,
            deception_success=deception_success,
            purged=purged,
            lesson_summary=self._summarise(behaviour, decision),
        )
        self._intercept_log[threat_id] = result
        return result

    def get_intercept(self, threat_id: str) -> Optional[SilentInterceptResult]:
        """Return the most recent intercept result for *threat_id*, or None."""
        return self._intercept_log.get(threat_id)

    def banked_patterns(self) -> List[str]:
        """All threat patterns learned and banked so far."""
        return list(self._banked_patterns)

    def is_known_threat(self, pattern: str) -> bool:
        """Return True if *pattern* matches a banked threat signature."""
        return pattern in self._banked_patterns

    def export_patterns(self) -> List[str]:
        """Export banked patterns for peer-node knowledge sharing."""
        return list(self._banked_patterns)

    def import_patterns(self, patterns: List[str]) -> int:
        """
        Import banked patterns from a peer node.

        Returns
        -------
        int
            Number of new patterns added (already-known patterns are skipped).
        """
        added = 0
        for pat in patterns:
            if pat not in self._banked_patterns:
                self._banked_patterns.append(pat)
                added += 1
        return added

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _advance_phase(self, behaviour: ThreatBehaviourRecord) -> InterceptPhase:
        if behaviour.threat_score >= self.ESCALATION_THRESHOLD:
            return InterceptPhase.SILENCED
        if behaviour.access_attempts >= self.HONEYPOT_MIN_ATTEMPTS:
            return InterceptPhase.STUDYING
        return InterceptPhase.SHADOW

    def _decide(
        self,
        behaviour: ThreatBehaviourRecord,
        phase: InterceptPhase,
    ) -> InterceptDecision:
        if behaviour.threat_score >= self.ESCALATION_THRESHOLD:
            return InterceptDecision.SILENCE_AND_PURGE
        if phase == InterceptPhase.STUDYING:
            return InterceptDecision.CONTINUE_STUDY
        return InterceptDecision.CONTINUE_STUDY

    def _run_honeypot(
        self, behaviour: ThreatBehaviourRecord, phase: InterceptPhase
    ) -> bool:
        """Simulate feeding decoy data; returns True if the threat consumed a decoy."""
        if phase not in (InterceptPhase.STUDYING, InterceptPhase.SILENCED):
            return False
        behaviour.decoys_consumed += 1
        return True

    def _bank_patterns(self, behaviour: ThreatBehaviourRecord) -> List[str]:
        """Add all newly observed patterns and a fingerprint to the bank."""
        new: List[str] = []

        for pat in behaviour.patterns_observed:
            if pat not in self._banked_patterns:
                self._banked_patterns.append(pat)
                new.append(pat)

        # Auto-generate a behaviour fingerprint regardless of raw patterns.
        fingerprint = (
            f"sig:atk={behaviour.access_attempts}:"
            f"exfil={int(behaviour.exfiltration_attempted)}:"
            f"privesc={int(behaviour.privilege_escalation_attempted)}:"
            f"lateral={int(behaviour.lateral_movement_detected)}"
        )
        if fingerprint not in self._banked_patterns:
            self._banked_patterns.append(fingerprint)
            new.append(fingerprint)

        return new

    def _summarise(
        self, behaviour: ThreatBehaviourRecord, decision: InterceptDecision
    ) -> str:
        status = "purged" if decision == InterceptDecision.SILENCE_AND_PURGE else "under observation"
        return (
            f"Threat {behaviour.threat_id}: score={behaviour.threat_score:.2f}, "
            f"patterns={len(behaviour.patterns_observed)}, "
            f"decoys_consumed={behaviour.decoys_consumed}. "
            f"Decision: {decision.value}. Status: {status}."
        )
