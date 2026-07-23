"""
SB-712 Heartbeat Rhythm
========================

The system's heartbeat, modelled on cardiac function.

Like a healthy heart, SB-712 needs:
    • A regular rhythm       — pulses at a configured cadence (default: every 30 s).
    • Variability detection  — small natural variation is healthy; large swings
                               signal arrhythmia.
    • Missed-beat detection  — a pulse that does not arrive triggers a recovery action.
    • Flatline escalation    — consecutive missed beats escalate to emergency rollback.
    • Recovery cadence       — after arrhythmia the system re-synchronises.

Relationship to HeartbeatMonitor
---------------------------------
HeartbeatMonitor (``sb_712.system``) produces a health *score* by evaluating
node readiness, recovery readiness, and trust ratios.  HeartRhythm tracks the
*cadence* — the timing of those score evaluations.  Together they form the
full cardiac picture:

    HeartbeatMonitor — the blood pressure reading
    HeartRhythm      — the ECG trace
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
import uuid


class RhythmStatus(Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"         # Beating faster than baseline (system under pressure)
    ARRHYTHMIA = "ARRHYTHMIA"     # Irregular interval — not within tolerance window
    MISSED_BEAT = "MISSED_BEAT"   # Beat arrived very late
    FLATLINE = "FLATLINE"         # Multiple consecutive beats missed
    RECOVERING = "RECOVERING"     # Re-synchronising after arrhythmia or missed beat


class RhythmAction(Enum):
    NONE = "NONE"
    SELF_HEAL = "SELF_HEAL"
    ALERT_OPERATOR = "ALERT_OPERATOR"
    EMERGENCY_ROLLBACK = "EMERGENCY_ROLLBACK"


@dataclass
class HeartbeatPulse:
    """A single heartbeat pulse measurement."""

    pulse_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    health_score: float = 100.0          # Score from HeartbeatMonitor (0–100)
    interval_ms: Optional[float] = None  # Time since last pulse; None for first beat
    rhythm_status: RhythmStatus = RhythmStatus.NORMAL
    action: RhythmAction = RhythmAction.NONE
    note: str = ""


@dataclass
class RhythmReport:
    """Summary of the rhythm state across all recorded pulses."""

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    pulse_count: int = 0
    missed_beats: int = 0
    arrhythmia_count: int = 0
    current_status: RhythmStatus = RhythmStatus.NORMAL
    last_action: RhythmAction = RhythmAction.NONE
    average_interval_ms: Optional[float] = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HeartRhythm:
    """
    Tracks the system's heartbeat rhythm like a cardiac monitor.

    Parameters
    ----------
    target_interval_ms : float
        Expected time between heartbeats in milliseconds (default: 30 000 ms = 30 s).
    tolerance_pct : float
        Percentage of the target interval that is considered "normal" variance.
        For example, 20 % tolerance on a 30 s interval means 24 s – 36 s is NORMAL.
    missed_beat_limit : int
        Number of consecutive missed/very-late beats before FLATLINE is declared.

    Usage::

        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulse = rhythm.beat(health_score=100.0)
        # … 35 seconds later …
        pulse = rhythm.beat(health_score=99.9)
        report = rhythm.report()
    """

    def __init__(
        self,
        target_interval_ms: float = 30_000.0,
        tolerance_pct: float = 20.0,
        missed_beat_limit: int = 3,
    ) -> None:
        if target_interval_ms <= 0:
            raise ValueError("target_interval_ms must be positive")
        if not (0 < tolerance_pct < 100):
            raise ValueError("tolerance_pct must be between 0 and 100 (exclusive)")
        if missed_beat_limit < 1:
            raise ValueError("missed_beat_limit must be at least 1")

        self.target_interval_ms = target_interval_ms
        self.tolerance_pct = tolerance_pct
        self.missed_beat_limit = missed_beat_limit
        self._pulses: List[HeartbeatPulse] = []
        self._consecutive_missed: int = 0

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def beat(
        self,
        health_score: float,
        now: Optional[datetime] = None,
    ) -> HeartbeatPulse:
        """
        Record a heartbeat pulse and return its rhythm assessment.

        Parameters
        ----------
        health_score : float
            Current system health score (0–100) from HeartbeatMonitor.
        now : datetime, optional
            Timestamp of this beat; defaults to UTC now.
        """
        ts = now or datetime.now(timezone.utc)
        interval_ms = self._measure_interval(ts)
        status = self._classify_rhythm(interval_ms, health_score)
        action = self._decide_action(status)

        if status in (RhythmStatus.MISSED_BEAT, RhythmStatus.FLATLINE):
            self._consecutive_missed += 1
        else:
            self._consecutive_missed = 0

        pulse = HeartbeatPulse(
            timestamp=ts,
            health_score=health_score,
            interval_ms=interval_ms,
            rhythm_status=status,
            action=action,
            note=self._compose_note(status, interval_ms, health_score),
        )
        self._pulses.append(pulse)
        return pulse

    def report(self) -> RhythmReport:
        """Return a summary of the current rhythm state across all pulses."""
        missed = sum(
            1
            for p in self._pulses
            if p.rhythm_status in (RhythmStatus.MISSED_BEAT, RhythmStatus.FLATLINE)
        )
        arrhythmia = sum(
            1 for p in self._pulses if p.rhythm_status == RhythmStatus.ARRHYTHMIA
        )
        intervals = [p.interval_ms for p in self._pulses if p.interval_ms is not None]
        avg: Optional[float] = round(sum(intervals) / len(intervals), 2) if intervals else None
        last = self._pulses[-1] if self._pulses else None
        return RhythmReport(
            pulse_count=len(self._pulses),
            missed_beats=missed,
            arrhythmia_count=arrhythmia,
            current_status=last.rhythm_status if last else RhythmStatus.NORMAL,
            last_action=last.action if last else RhythmAction.NONE,
            average_interval_ms=avg,
        )

    def pulses(self) -> List[HeartbeatPulse]:
        return list(self._pulses)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _measure_interval(self, now: datetime) -> Optional[float]:
        if not self._pulses:
            return None
        last_ts = self._pulses[-1].timestamp
        return round((now - last_ts).total_seconds() * 1000.0, 2)

    def _classify_rhythm(
        self, interval_ms: Optional[float], health_score: float
    ) -> RhythmStatus:
        # First beat — no prior interval; always NORMAL.
        if interval_ms is None:
            return RhythmStatus.NORMAL

        low = self.target_interval_ms * (1.0 - self.tolerance_pct / 100.0)
        high = self.target_interval_ms * (1.0 + self.tolerance_pct / 100.0)

        # Flatline check: consecutive misses already accumulated.
        if self._consecutive_missed >= self.missed_beat_limit:
            return RhythmStatus.FLATLINE

        # Very long gap → missed beat.
        if interval_ms > high * 1.5:
            return RhythmStatus.MISSED_BEAT

        # Very short gap → elevated (system beating fast under stress).
        if interval_ms < low * 0.5:
            return RhythmStatus.ELEVATED

        # Within normal window.
        if low <= interval_ms <= high:
            # Sub-100 % health score while within timing window → recovering.
            if health_score < 99.8:
                return RhythmStatus.RECOVERING
            return RhythmStatus.NORMAL

        # Outside the tolerance window but not extreme → arrhythmia.
        return RhythmStatus.ARRHYTHMIA

    def _decide_action(self, status: RhythmStatus) -> RhythmAction:
        if status == RhythmStatus.FLATLINE:
            return RhythmAction.EMERGENCY_ROLLBACK
        if status in (RhythmStatus.MISSED_BEAT, RhythmStatus.ARRHYTHMIA):
            return RhythmAction.ALERT_OPERATOR
        if status == RhythmStatus.RECOVERING:
            return RhythmAction.SELF_HEAL
        return RhythmAction.NONE

    def _compose_note(
        self, status: RhythmStatus, interval_ms: Optional[float], score: float
    ) -> str:
        if interval_ms is None:
            return "First heartbeat registered. Rhythm baseline established."
        target = self.target_interval_ms
        diff = interval_ms - target
        sign = "+" if diff >= 0 else ""
        return (
            f"Rhythm: {status.value} | "
            f"Interval: {interval_ms:.0f} ms "
            f"(target {target:.0f} ms, {sign}{diff:.0f} ms) | "
            f"Score: {score:.1f}"
        )
