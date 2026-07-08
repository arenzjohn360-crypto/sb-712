"""
Metrics collection for SB-712 validation runs.

SingleRunResult  — outcome record for one test
BatchMetrics     — aggregated statistics across N tests
MetricsCollector — accumulates SingleRunResults and computes BatchMetrics
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SingleRunResult:
    """Complete outcome record for one end-to-end test run."""

    test_id: int
    seed: int
    scenario: str
    fault_type: str
    fault_target: str
    duration_ms: float
    detected: bool         # VerificationGate caught the fault
    quarantined: bool      # Bad data logged to /quarantine/
    recovered: bool        # System restored to healthy state
    ledger_intact: bool    # ProofLedger chain verified after recovery
    seal_before: str       # chain_seal() before fault injection
    seal_after: str        # chain_seal() after recovery
    recovery_time_ms: float
    failure_reason: str = ""

    @property
    def passed(self) -> bool:
        """A test passes when the fault was detected, quarantined, recovered,
        and the ledger remained intact."""
        return (
            self.detected
            and self.quarantined
            and self.recovered
            and self.ledger_intact
        )

    def as_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "seed": self.seed,
            "scenario": self.scenario,
            "fault_type": self.fault_type,
            "fault_target": self.fault_target,
            "duration_ms": round(self.duration_ms, 3),
            "detected": self.detected,
            "quarantined": self.quarantined,
            "recovered": self.recovered,
            "ledger_intact": self.ledger_intact,
            "seal_before": self.seal_before,
            "seal_after": self.seal_after,
            "recovery_time_ms": round(self.recovery_time_ms, 3),
            "passed": self.passed,
            "failure_reason": self.failure_reason,
        }


@dataclass
class BatchMetrics:
    """Aggregated statistics across a batch of validation runs."""

    scenario: str
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    ledger_seal_mismatches: int = 0
    drift_events_detected: int = 0
    drift_events_recovered: int = 0
    quarantine_events: int = 0
    recovery_success_rate: float = 0.0
    mean_recovery_time_ms: float = 0.0
    max_recovery_time_ms: float = 0.0
    false_positives: int = 0   # detected=True but fault_type was "none"
    false_negatives: int = 0   # detected=False but fault_type was not "none"
    cpu_usage_pct: Optional[float] = None
    ram_usage_mb: Optional[float] = None
    seeds_used: List[int] = field(default_factory=list)
    run_results: List[SingleRunResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "ledger_seal_mismatches": self.ledger_seal_mismatches,
            "drift_events_detected": self.drift_events_detected,
            "drift_events_recovered": self.drift_events_recovered,
            "quarantine_events": self.quarantine_events,
            "recovery_success_rate": round(self.recovery_success_rate, 4),
            "mean_recovery_time_ms": round(self.mean_recovery_time_ms, 3),
            "max_recovery_time_ms": round(self.max_recovery_time_ms, 3),
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "cpu_usage_pct": self.cpu_usage_pct,
            "ram_usage_mb": self.ram_usage_mb,
            "seeds_used_count": len(self.seeds_used),
            "seeds_sample": self.seeds_used[:10],
        }


class MetricsCollector:
    """Accumulates SingleRunResults and computes a BatchMetrics summary."""

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self._results: List[SingleRunResult] = []
        self._start_time: float = time.time()

    def record(self, result: SingleRunResult) -> None:
        self._results.append(result)

    def compute(self) -> BatchMetrics:
        if not self._results:
            return BatchMetrics(scenario=self.scenario)

        total = len(self._results)
        passed = sum(1 for r in self._results if r.passed)
        ledger_mismatches = sum(1 for r in self._results if not r.ledger_intact)
        drift_detected = sum(1 for r in self._results if r.detected)
        drift_recovered = sum(1 for r in self._results if r.recovered)
        quarantine_events = sum(1 for r in self._results if r.quarantined)
        recovery_times = [r.recovery_time_ms for r in self._results if r.recovered]
        false_positives = sum(
            1 for r in self._results if r.detected and r.fault_type == "none"
        )
        false_negatives = sum(
            1 for r in self._results if not r.detected and r.fault_type != "none"
        )

        cpu_pct: Optional[float] = None
        ram_mb: Optional[float] = None
        try:
            import psutil  # type: ignore[import]

            cpu_pct = psutil.cpu_percent(interval=0.05)
            ram_mb = psutil.virtual_memory().used / (1024 * 1024)
        except ImportError:
            pass

        return BatchMetrics(
            scenario=self.scenario,
            total_tests=total,
            passed=passed,
            failed=total - passed,
            ledger_seal_mismatches=ledger_mismatches,
            drift_events_detected=drift_detected,
            drift_events_recovered=drift_recovered,
            quarantine_events=quarantine_events,
            recovery_success_rate=drift_recovered / total if total > 0 else 0.0,
            mean_recovery_time_ms=(
                sum(recovery_times) / len(recovery_times) if recovery_times else 0.0
            ),
            max_recovery_time_ms=max(recovery_times) if recovery_times else 0.0,
            false_positives=false_positives,
            false_negatives=false_negatives,
            cpu_usage_pct=cpu_pct,
            ram_usage_mb=ram_mb,
            seeds_used=[r.seed for r in self._results],
            run_results=list(self._results),
        )
