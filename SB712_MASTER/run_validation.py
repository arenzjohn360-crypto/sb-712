#!/usr/bin/env python3
"""
run_validation.py — SB-712 Stitch Brick validation CLI.

Usage examples
--------------
# Run 1 000 tests under the default (byte_corruption) scenario
python run_validation.py --tests 1000

# Run 10 000 tests
python run_validation.py --tests 10000

# Run a named scenario
python run_validation.py --scenario 80_percent_brick_failure
python run_validation.py --scenario hallucination_containment
python run_validation.py --scenario ledger_drift

# Replay a specific seed
python run_validation.py --tests 1 --seed 42

# Print a summary of all existing reports
python run_validation.py --report

# Full combination
python run_validation.py --tests 500 --scenario message_tamper --seed 7 --verbose

Available scenarios
-------------------
  byte_corruption           Random byte flip in brick output
  ledger_hash_mismatch      Brick supplies wrong seal
  ledger_drift              Alias for ledger_hash_mismatch
  broken_brick              Brick crashes on compute()
  80_percent_brick_failure  80 % of bricks crash simultaneously
  message_tamper            Strand payload corrupted in transit
  hallucination_containment Brick returns random garbage with a valid seal
  network_delay             Strand introduces artificial latency
  disk_write_interrupt      Checkpoint snapshot truncated mid-write
  partial_checkpoint        Required field removed from checkpoint
  dependency_failure        Cascading brick failure
  recovery_loop_failure     All bricks fail — worst-case scenario
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Ensure src/ is on the path when run from the repo root
_HERE = Path(__file__).resolve().parent
_SRC = _HERE / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from stitch_brick import ProofGenerator, ValidationRunner
from stitch_brick.fault_injector import FAULT_SCENARIOS

_REPO_ROOT = _HERE


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )


def _progress(done: int, total: int) -> None:
    pct = done / total * 100
    bar_len = 40
    filled = int(bar_len * done / total)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  [{bar}] {done}/{total} ({pct:.1f}%)", end="", flush=True)
    if done == total:
        print()   # newline when complete


def _cmd_run(args: argparse.Namespace) -> int:
    scenario = args.scenario or "byte_corruption"
    if scenario not in FAULT_SCENARIOS and scenario != "all":
        print(f"[ERROR] Unknown scenario {scenario!r}.")
        print(f"        Valid: {', '.join(sorted(FAULT_SCENARIOS))}")
        return 1

    n_tests = args.tests
    base_seed = args.seed if args.seed is not None else 0

    print(f"\n{'='*60}")
    print(f"  SB-712 Stitch Brick Validation Framework")
    print(f"{'='*60}")
    print(f"  Scenario : {scenario}")
    print(f"  Runs     : {n_tests}")
    print(f"  Base seed: {base_seed}")
    print(f"  Root     : {_REPO_ROOT}")
    print(f"{'='*60}\n")

    runner = ValidationRunner(root=_REPO_ROOT)
    pg = ProofGenerator(root=_REPO_ROOT)

    t_start = time.perf_counter()
    print(f"  Running {n_tests} test(s)…")
    metrics = runner.run_batch(
        n_tests=n_tests,
        scenario=scenario,
        base_seed=base_seed,
        progress_cb=_progress if not args.verbose else None,
    )
    elapsed = time.perf_counter() - t_start

    # Print results
    print(f"\n{'='*60}")
    print(f"  RESULTS — {scenario}")
    print(f"{'='*60}")
    print(f"  Total tests          : {metrics.total_tests}")
    print(f"  Passed               : {metrics.passed}")
    print(f"  Failed               : {metrics.failed}")
    pass_rate = metrics.passed / metrics.total_tests * 100 if metrics.total_tests else 0
    print(f"  Pass rate            : {pass_rate:.2f}%")
    print(f"  Recovery success rate: {metrics.recovery_success_rate * 100:.2f}%")
    print(f"  Mean recovery time   : {metrics.mean_recovery_time_ms:.3f} ms")
    print(f"  Max recovery time    : {metrics.max_recovery_time_ms:.3f} ms")
    print(f"  Ledger mismatches    : {metrics.ledger_seal_mismatches}")
    print(f"  Drift detected       : {metrics.drift_events_detected}")
    print(f"  Drift recovered      : {metrics.drift_events_recovered}")
    print(f"  Quarantine events    : {metrics.quarantine_events}")
    print(f"  False positives      : {metrics.false_positives}")
    print(f"  False negatives      : {metrics.false_negatives}")
    if metrics.cpu_usage_pct is not None:
        print(f"  CPU usage            : {metrics.cpu_usage_pct:.1f}%")
    if metrics.ram_usage_mb is not None:
        print(f"  RAM used             : {metrics.ram_usage_mb:.1f} MB")
    print(f"  Wall time            : {elapsed:.2f}s")
    print(f"{'='*60}")

    # Precise findings
    print(f"\n  Under the tested simulation conditions ({n_tests} runs):")
    if metrics.ledger_seal_mismatches == 0:
        print(
            f"  ✓ Observed zero undetected ledger drift across {n_tests} runs."
        )
    else:
        print(
            f"  ✗ {metrics.ledger_seal_mismatches} ledger seal mismatch(es) recorded."
        )
    print(
        f"  ✓ Recovered successfully in "
        f"{metrics.drift_events_recovered}/{metrics.total_tests} runs."
    )
    if metrics.false_negatives == 0:
        print(f"  ✓ Zero false negatives — every injected fault was detected.")
    else:
        print(
            f"  ✗ {metrics.false_negatives} false negative(s) — "
            f"fault injected but not detected."
        )
    if metrics.failed > 0:
        print(
            f"  ⚠ Failed in {metrics.failed} case(s) — see proof/failures_* for details."
        )

    # Generate reports
    print(f"\n  Generating reports…")
    artefacts = pg.generate_all(metrics)
    for label, path in artefacts.items():
        print(f"  {label:<24}: {path.relative_to(_REPO_ROOT)}")

    return 0 if metrics.failed == 0 else 1


def _cmd_report(args: argparse.Namespace) -> int:
    reports_dir = _REPO_ROOT / "reports"
    if not reports_dir.exists() or not any(reports_dir.iterdir()):
        print("No reports found.  Run `python run_validation.py --tests N` first.")
        return 0

    print(f"\n{'='*60}")
    print(f"  Existing validation reports")
    print(f"{'='*60}")
    for f in sorted(reports_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            summary = data.get("summary", {})
            total = summary.get("total_tests", "?")
            passed = summary.get("passed", "?")
            scenario = summary.get("scenario", f.stem)
            gen = data.get("generated_at", "?")
            print(f"  {f.name}")
            print(f"    scenario={scenario}  runs={total}  passed={passed}  at={gen}")
        except (json.JSONDecodeError, KeyError):
            print(f"  {f.name}  (could not parse)")
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_validation.py",
        description="SB-712 Stitch Brick — validation & proof CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--tests",
        type=int,
        default=0,
        metavar="N",
        help="Number of validation runs to execute",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        metavar="NAME",
        help="Fault scenario name (default: byte_corruption)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Base random seed for reproducibility (default: 0)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print a summary of all existing reports and exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.report:
        return _cmd_report(args)

    if args.tests == 0 and args.scenario is None:
        # Default: 100 tests, byte_corruption
        args.tests = 100
        args.scenario = "byte_corruption"
        print("No arguments supplied — running default: --tests 100 --scenario byte_corruption")

    if args.tests == 0:
        args.tests = 100   # default when only --scenario is given

    return _cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
