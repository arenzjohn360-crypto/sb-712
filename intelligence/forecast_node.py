"""
forecast_node.py — SB-712 IronBraid Radiant Core

Predicts system instability before a failure occurs by analysing a series
of :class:`~intelligence.fieldview_encoder.FieldSnapshot` objects and
returning a risk forecast.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from intelligence.fieldview_encoder import FieldSnapshot


@dataclass
class RiskForecast:
    """Result produced by the ForecastNode."""

    risk_score: float  # 0.0 (calm) → 1.0 (imminent failure)
    risk_level: str    # LOW | MEDIUM | HIGH | CRITICAL
    signals: List[str]


def _score_to_level(score: float) -> str:
    if score < 0.25:
        return "LOW"
    if score < 0.5:
        return "MEDIUM"
    if score < 0.75:
        return "HIGH"
    return "CRITICAL"


class ForecastNode:
    """
    Lightweight risk forecaster that scores recent field snapshots.

    The scoring heuristic weights mutation rate, disk read errors, and
    fault event frequency.  It is intentionally simple — production
    deployments should replace or extend ``_compute_score`` with a
    calibrated model.

    Usage::

        node = ForecastNode()
        forecast = node.predict([snap1, snap2, snap3])
    """

    MUTATION_WEIGHT: float = 0.4
    READ_ERROR_WEIGHT: float = 0.4
    FAULT_WEIGHT: float = 0.2

    def predict(self, snapshots: List[FieldSnapshot]) -> RiskForecast:
        """
        Predict instability from *snapshots* (most recent last).

        Returns a :class:`RiskForecast` with a normalised ``risk_score``
        between 0.0 and 1.0.
        """
        if not snapshots:
            return RiskForecast(risk_score=0.0, risk_level="LOW", signals=[])

        total_mutations = sum(s.mutation_count for s in snapshots)
        total_read_errors = sum(s.disk_read_errors for s in snapshots)
        total_faults = sum(len(s.fault_events) for s in snapshots)
        n = len(snapshots)

        # Normalise to per-snapshot averages, capped at 1.0 each.
        mut_score = min(1.0, (total_mutations / n) / 5.0)
        err_score = min(1.0, (total_read_errors / n) / 3.0)
        fault_score = min(1.0, (total_faults / n) / 10.0)

        raw = (
            self.MUTATION_WEIGHT * mut_score
            + self.READ_ERROR_WEIGHT * err_score
            + self.FAULT_WEIGHT * fault_score
        )
        score = min(1.0, raw)
        signals: List[str] = []
        if mut_score > 0.5:
            signals.append("HIGH_MUTATION_RATE")
        if err_score > 0.5:
            signals.append("HIGH_READ_ERROR_RATE")
        if fault_score > 0.5:
            signals.append("HIGH_FAULT_RATE")
        return RiskForecast(
            risk_score=round(score, 4),
            risk_level=_score_to_level(score),
            signals=signals,
        )
