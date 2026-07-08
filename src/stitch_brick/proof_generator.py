"""
ProofGenerator — generates reproducible evidence reports from BatchMetrics.

Output formats:
  JSON report      → reports/<scenario>_<timestamp>.json
  Markdown report  → reports/<scenario>_<timestamp>.md
  Executive summary → reports/executive_summary_<timestamp>.md
  Failure analysis → proof/failures_<scenario>_<timestamp>.json
  Ledger integrity → proof/ledger_integrity_<scenario>_<timestamp>.json

All reports use precise language:
  "Under the tested simulation conditions..."
  "Observed zero undetected ledger drift across N runs..."
  "Recovered successfully in X/Y runs..."
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .metrics import BatchMetrics, SingleRunResult


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ts() -> str:
    return str(int(time.time()))


class ProofGenerator:
    """Generates all report artefacts from a BatchMetrics result."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root = root or Path(".")
        self._reports = self._root / "reports"
        self._proof = self._root / "proof"
        self._logs = self._root / "logs"
        for d in (self._reports, self._proof, self._logs):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_all(self, metrics: BatchMetrics) -> dict:
        """
        Generate all report files.  Returns a dict of {report_type: Path}.
        """
        ts = _ts()
        slug = metrics.scenario.replace(" ", "_").replace("/", "_")

        json_path = self._write_json(metrics, slug, ts)
        md_path = self._write_markdown(metrics, slug, ts)
        exec_path = self._write_executive_summary(metrics, slug, ts)
        fail_path = self._write_failure_analysis(metrics, slug, ts)
        ledger_path = self._write_ledger_integrity(metrics, slug, ts)
        log_path = self._write_run_log(metrics, slug, ts)

        return {
            "json_report": json_path,
            "markdown_report": md_path,
            "executive_summary": exec_path,
            "failure_analysis": fail_path,
            "ledger_integrity": ledger_path,
            "run_log": log_path,
        }

    # ------------------------------------------------------------------
    # JSON report
    # ------------------------------------------------------------------

    def _write_json(self, metrics: BatchMetrics, slug: str, ts: str) -> Path:
        path = self._reports / f"{slug}_{ts}.json"
        payload = {
            "generated_at": _utc_iso(),
            "framework": "SB-712 Stitch Brick Validation Framework",
            "scenario": metrics.scenario,
            "summary": metrics.as_dict(),
            "run_results": [r.as_dict() for r in metrics.run_results],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Markdown report
    # ------------------------------------------------------------------

    def _write_markdown(self, metrics: BatchMetrics, slug: str, ts: str) -> Path:
        path = self._reports / f"{slug}_{ts}.md"
        pass_rate = (
            f"{metrics.passed / metrics.total_tests * 100:.2f}%"
            if metrics.total_tests
            else "N/A"
        )
        recovery_rate = f"{metrics.recovery_success_rate * 100:.2f}%"

        lines = [
            f"# SB-712 Stitch Brick — Validation Report",
            f"",
            f"**Generated:** {_utc_iso()}  ",
            f"**Scenario:** `{metrics.scenario}`  ",
            f"**Total runs:** {metrics.total_tests}",
            f"",
            f"---",
            f"",
            f"## Summary Metrics",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total tests | {metrics.total_tests} |",
            f"| Passed | {metrics.passed} |",
            f"| Failed | {metrics.failed} |",
            f"| Pass rate | {pass_rate} |",
            f"| Recovery success rate | {recovery_rate} |",
            f"| Mean recovery time | {metrics.mean_recovery_time_ms:.3f} ms |",
            f"| Max recovery time | {metrics.max_recovery_time_ms:.3f} ms |",
            f"| Ledger seal mismatches | {metrics.ledger_seal_mismatches} |",
            f"| Drift events detected | {metrics.drift_events_detected} |",
            f"| Drift events recovered | {metrics.drift_events_recovered} |",
            f"| Quarantine events | {metrics.quarantine_events} |",
            f"| False positives | {metrics.false_positives} |",
            f"| False negatives | {metrics.false_negatives} |",
        ]

        if metrics.cpu_usage_pct is not None:
            lines.append(f"| CPU usage | {metrics.cpu_usage_pct:.1f}% |")
        if metrics.ram_usage_mb is not None:
            lines.append(f"| RAM used | {metrics.ram_usage_mb:.1f} MB |")

        lines += [
            f"",
            f"---",
            f"",
            f"## Precise Findings",
            f"",
            f"> *Under the tested simulation conditions for scenario "
            f"`{metrics.scenario}`:*",
            f"",
        ]

        if metrics.total_tests > 0:
            if metrics.ledger_seal_mismatches == 0:
                lines.append(
                    f"- Observed **zero undetected ledger drift** across "
                    f"{metrics.total_tests} runs."
                )
            else:
                lines.append(
                    f"- Observed **{metrics.ledger_seal_mismatches} ledger seal "
                    f"mismatch(es)** across {metrics.total_tests} runs."
                )

            lines.append(
                f"- Recovered successfully in "
                f"**{metrics.drift_events_recovered}/{metrics.total_tests}** runs."
            )

            if metrics.failed > 0:
                lines.append(
                    f"- Failed in **{metrics.failed}** case(s) — logged to "
                    f"`proof/failures_{slug}_{ts}.json`."
                )

            if metrics.false_negatives > 0:
                lines.append(
                    f"- **{metrics.false_negatives}** fault(s) were injected but "
                    f"not detected (false negatives) — review `proof/failures_{slug}_{ts}.json`."
                )
            else:
                lines.append(
                    f"- **Zero false negatives** — every injected fault was detected."
                )

        lines += [
            f"",
            f"---",
            f"",
            f"## Seeds Used",
            f"",
            f"First 10 seeds: `{metrics.seeds_used[:10]}`  ",
            f"Total seeds: {len(metrics.seeds_used)}  ",
            f"_(Replay any run: `python run_validation.py --tests 1 "
            f"--scenario {metrics.scenario} --seed <N>`)_",
            f"",
        ]

        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Executive summary
    # ------------------------------------------------------------------

    def _write_executive_summary(
        self, metrics: BatchMetrics, slug: str, ts: str
    ) -> Path:
        path = self._reports / f"executive_summary_{slug}_{ts}.md"
        n = metrics.total_tests
        rec = metrics.drift_events_recovered
        det = metrics.drift_events_detected
        fail = metrics.failed

        lines = [
            "# SB-712 Stitch Brick — Executive Summary",
            "",
            f"**Date:** {_utc_iso()}",
            f"**Scenario:** {metrics.scenario}",
            f"**Runs completed:** {n}",
            "",
            "## What was tested",
            "",
            f"The SB-712 Stitch Brick validation framework ran {n} independent "
            f"simulation cycles under the `{metrics.scenario}` scenario.  "
            f"Each cycle injected a fault, attempted detection, quarantine, "
            f"checkpoint-based recovery, and ledger verification.",
            "",
            "## What was observed",
            "",
            f"Under the tested simulation conditions with {n} runs:",
            "",
        ]

        if n > 0:
            lines += [
                f"- **Detection rate:** {det}/{n} "
                f"({det/n*100:.1f}%) — faults were caught by the VerificationGate.",
                f"- **Recovery rate:** {rec}/{n} "
                f"({rec/n*100:.1f}%) — system restored to healthy state.",
                f"- **Ledger integrity:** "
                + (
                    "All ledger chains verified intact after recovery."
                    if metrics.ledger_seal_mismatches == 0
                    else f"{metrics.ledger_seal_mismatches} ledger seal mismatch(es) recorded."
                ),
                f"- **False negatives:** {metrics.false_negatives} "
                f"(faults injected but not detected).",
                f"- **Mean recovery time:** {metrics.mean_recovery_time_ms:.3f} ms",
                f"- **Max recovery time:** {metrics.max_recovery_time_ms:.3f} ms",
            ]

        lines += [
            "",
            "## Caveats",
            "",
            "These results reflect simulation behaviour only.  "
            "No claim of universal proof is made.  "
            "Results are reproducible: rerun with the seeds listed in the full report "
            "to obtain comparable results on any machine meeting the minimum "
            "requirements (Python 3.10+, 8 GB RAM).",
            "",
        ]

        if fail > 0:
            lines += [
                "## Failures to investigate",
                "",
                f"{fail} run(s) did not achieve full pass criteria.  "
                f"Detailed failure records are saved to `proof/failures_{slug}_{ts}.json`.",
                "",
            ]

        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Failure analysis
    # ------------------------------------------------------------------

    def _write_failure_analysis(
        self, metrics: BatchMetrics, slug: str, ts: str
    ) -> Path:
        path = self._proof / f"failures_{slug}_{ts}.json"
        failures = [r.as_dict() for r in metrics.run_results if not r.passed]
        payload = {
            "generated_at": _utc_iso(),
            "scenario": metrics.scenario,
            "total_failures": len(failures),
            "failures": failures,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Ledger integrity
    # ------------------------------------------------------------------

    def _write_ledger_integrity(
        self, metrics: BatchMetrics, slug: str, ts: str
    ) -> Path:
        path = self._proof / f"ledger_integrity_{slug}_{ts}.json"
        intact_runs = [
            {"test_id": r.test_id, "seed": r.seed, "seal_before": r.seal_before,
             "seal_after": r.seal_after}
            for r in metrics.run_results
            if r.ledger_intact
        ]
        broken_runs = [
            {"test_id": r.test_id, "seed": r.seed, "seal_before": r.seal_before,
             "seal_after": r.seal_after, "failure_reason": r.failure_reason}
            for r in metrics.run_results
            if not r.ledger_intact
        ]
        payload = {
            "generated_at": _utc_iso(),
            "scenario": metrics.scenario,
            "total_runs": metrics.total_tests,
            "intact_count": len(intact_runs),
            "broken_count": len(broken_runs),
            "ledger_seal_mismatches": metrics.ledger_seal_mismatches,
            "finding": (
                f"Under the tested simulation conditions, observed zero undetected "
                f"ledger drift across {metrics.total_tests} runs."
                if metrics.ledger_seal_mismatches == 0
                else f"{metrics.ledger_seal_mismatches} ledger seal mismatch(es) detected."
            ),
            "intact_runs": intact_runs,
            "broken_runs": broken_runs,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Run log (one line per test for trend tracking)
    # ------------------------------------------------------------------

    def _write_run_log(self, metrics: BatchMetrics, slug: str, ts: str) -> Path:
        path = self._logs / f"run_log_{slug}_{ts}.jsonl"
        lines = [
            json.dumps(r.as_dict()) for r in metrics.run_results
        ]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path
