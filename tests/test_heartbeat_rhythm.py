"""
Tests for SB-712 Heartbeat Rhythm monitor.
"""
from datetime import timedelta

import pytest

from sb_712 import (
    HeartRhythm,
    HeartbeatPulse,
    RhythmAction,
    RhythmReport,
    RhythmStatus,
)
from sb_712.heartbeat_rhythm import HeartRhythm


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestHeartRhythmConstruction:
    def test_default_parameters(self):
        rhythm = HeartRhythm()
        assert rhythm.target_interval_ms == 30_000.0
        assert rhythm.tolerance_pct == 20.0
        assert rhythm.missed_beat_limit == 3

    def test_rejects_zero_interval(self):
        with pytest.raises(ValueError):
            HeartRhythm(target_interval_ms=0)

    def test_rejects_negative_interval(self):
        with pytest.raises(ValueError):
            HeartRhythm(target_interval_ms=-1)

    def test_rejects_zero_tolerance(self):
        with pytest.raises(ValueError):
            HeartRhythm(tolerance_pct=0)

    def test_rejects_hundred_percent_tolerance(self):
        with pytest.raises(ValueError):
            HeartRhythm(tolerance_pct=100)

    def test_rejects_zero_missed_beat_limit(self):
        with pytest.raises(ValueError):
            HeartRhythm(missed_beat_limit=0)


# ---------------------------------------------------------------------------
# First beat
# ---------------------------------------------------------------------------


class TestFirstBeat:
    def test_first_beat_is_normal(self):
        rhythm = HeartRhythm()
        pulse = rhythm.beat(health_score=100.0)
        assert pulse.rhythm_status == RhythmStatus.NORMAL

    def test_first_beat_has_no_interval(self):
        rhythm = HeartRhythm()
        pulse = rhythm.beat(health_score=100.0)
        assert pulse.interval_ms is None

    def test_first_beat_action_is_none(self):
        rhythm = HeartRhythm()
        pulse = rhythm.beat(health_score=100.0)
        assert pulse.action == RhythmAction.NONE

    def test_first_beat_note_mentions_baseline(self):
        rhythm = HeartRhythm()
        pulse = rhythm.beat(health_score=100.0)
        assert "First heartbeat" in pulse.note


# ---------------------------------------------------------------------------
# Normal rhythm
# ---------------------------------------------------------------------------


def _beats(rhythm: HeartRhythm, n: int, interval_s: float = 30.0, score: float = 100.0):
    from datetime import datetime, timezone
    import datetime as dt

    base = datetime.now(timezone.utc)
    pulses = []
    for i in range(n):
        now = base + timedelta(seconds=interval_s * i)
        pulses.append(rhythm.beat(health_score=score, now=now))
    return pulses


class TestNormalRhythm:
    def test_on_target_interval_is_normal(self):
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulses = _beats(rhythm, 3, interval_s=30.0)
        # Skip first beat (no prior interval).
        for p in pulses[1:]:
            assert p.rhythm_status == RhythmStatus.NORMAL

    def test_upper_edge_of_tolerance_is_normal(self):
        # target=30 s, tolerance=20 % → high=36 s — exactly at high boundary.
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulses = _beats(rhythm, 2, interval_s=36.0)
        assert pulses[1].rhythm_status == RhythmStatus.NORMAL

    def test_lower_edge_of_tolerance_is_normal(self):
        # target=30 s, tolerance=20 % → low=24 s.
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulses = _beats(rhythm, 2, interval_s=24.0)
        assert pulses[1].rhythm_status == RhythmStatus.NORMAL


# ---------------------------------------------------------------------------
# Arrhythmia
# ---------------------------------------------------------------------------


class TestArrhythmia:
    def test_interval_outside_tolerance_is_arrhythmia(self):
        # 20 s interval on a 30 s target with 20 % tolerance (low=24 s).
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulses = _beats(rhythm, 2, interval_s=20.0)
        assert pulses[1].rhythm_status == RhythmStatus.ARRHYTHMIA

    def test_arrhythmia_triggers_alert_operator(self):
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulses = _beats(rhythm, 2, interval_s=20.0)
        assert pulses[1].action == RhythmAction.ALERT_OPERATOR


# ---------------------------------------------------------------------------
# Elevated
# ---------------------------------------------------------------------------


class TestElevated:
    def test_very_short_interval_is_elevated(self):
        # target=30 s, tolerance=20 % → low=24 s → 0.5×low=12 s.
        # An interval of 5 s (< 12 s) should be ELEVATED.
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulses = _beats(rhythm, 2, interval_s=5.0)
        assert pulses[1].rhythm_status == RhythmStatus.ELEVATED


# ---------------------------------------------------------------------------
# Missed beat
# ---------------------------------------------------------------------------


class TestMissedBeat:
    def test_very_long_interval_is_missed_beat(self):
        # target=30 s, tolerance=20 % → high=36 s → 1.5×high=54 s.
        # An interval of 60 s should be MISSED_BEAT.
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulses = _beats(rhythm, 2, interval_s=60.0)
        assert pulses[1].rhythm_status == RhythmStatus.MISSED_BEAT

    def test_missed_beat_triggers_alert_operator(self):
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulses = _beats(rhythm, 2, interval_s=60.0)
        assert pulses[1].action == RhythmAction.ALERT_OPERATOR


# ---------------------------------------------------------------------------
# Flatline
# ---------------------------------------------------------------------------


class TestFlatline:
    def test_flatline_declared_after_limit_consecutive_misses(self):
        rhythm = HeartRhythm(
            target_interval_ms=30_000, tolerance_pct=20, missed_beat_limit=3
        )
        # First beat to establish baseline.
        pulses = _beats(rhythm, 5, interval_s=60.0)
        # After 3 consecutive 60 s beats (all MISSED_BEAT), 4th should be FLATLINE.
        assert pulses[-1].rhythm_status == RhythmStatus.FLATLINE

    def test_flatline_triggers_emergency_rollback(self):
        rhythm = HeartRhythm(
            target_interval_ms=30_000, tolerance_pct=20, missed_beat_limit=3
        )
        pulses = _beats(rhythm, 5, interval_s=60.0)
        assert pulses[-1].action == RhythmAction.EMERGENCY_ROLLBACK


# ---------------------------------------------------------------------------
# Recovering
# ---------------------------------------------------------------------------


class TestRecovering:
    def test_sub_full_health_score_in_normal_window_is_recovering(self):
        # Score < 99.8 with interval in normal window → RECOVERING.
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulses = _beats(rhythm, 2, interval_s=30.0, score=99.0)
        assert pulses[1].rhythm_status == RhythmStatus.RECOVERING

    def test_recovering_triggers_self_heal(self):
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulses = _beats(rhythm, 2, interval_s=30.0, score=98.0)
        assert pulses[1].action == RhythmAction.SELF_HEAL


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestRhythmReport:
    def test_report_counts_pulses(self):
        rhythm = HeartRhythm(target_interval_ms=30_000)
        _beats(rhythm, 5, interval_s=30.0)
        assert rhythm.report().pulse_count == 5

    def test_report_counts_missed_beats(self):
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        _beats(rhythm, 2, interval_s=60.0)
        assert rhythm.report().missed_beats >= 1

    def test_report_counts_arrhythmia(self):
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        _beats(rhythm, 2, interval_s=20.0)
        assert rhythm.report().arrhythmia_count >= 1

    def test_report_average_interval_calculated(self):
        rhythm = HeartRhythm(target_interval_ms=30_000)
        _beats(rhythm, 4, interval_s=30.0)
        report = rhythm.report()
        assert report.average_interval_ms is not None
        # Should be approximately 30 000 ms.
        assert 29_000 <= report.average_interval_ms <= 31_000

    def test_report_current_status_matches_last_pulse(self):
        rhythm = HeartRhythm(target_interval_ms=30_000, tolerance_pct=20)
        pulses = _beats(rhythm, 3, interval_s=30.0)
        report = rhythm.report()
        assert report.current_status == pulses[-1].rhythm_status

    def test_empty_rhythm_report_is_normal(self):
        rhythm = HeartRhythm()
        report = rhythm.report()
        assert report.pulse_count == 0
        assert report.current_status == RhythmStatus.NORMAL
        assert report.average_interval_ms is None


# ---------------------------------------------------------------------------
# Pulse history
# ---------------------------------------------------------------------------


class TestPulseHistory:
    def test_pulses_returns_all_recorded_beats(self):
        rhythm = HeartRhythm()
        _beats(rhythm, 7, interval_s=30.0)
        assert len(rhythm.pulses()) == 7

    def test_pulses_are_immutable_copy(self):
        rhythm = HeartRhythm()
        _beats(rhythm, 3, interval_s=30.0)
        pulses = rhythm.pulses()
        pulses.clear()
        assert len(rhythm.pulses()) == 3
