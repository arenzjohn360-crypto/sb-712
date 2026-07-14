# SB-712 Stitch Brick — Validation Plan

## Purpose

This document describes the repeatable, evidence-backed validation strategy for SB-712 Stitch Brick.  The goal is to prove or disprove eight capability claims under controlled simulation conditions, and to produce artefacts that any engineer can independently reproduce and inspect.

---

## Capability claims under test

| # | Claim | Tested by |
|---|-------|-----------|
| 1 | Ledger drift prevention | `ledger_drift`, `ledger_hash_mismatch` scenarios |
| 2 | Corruption detection | `byte_corruption`, `message_tamper` scenarios |
| 3 | Corruption isolation | Quarantine logging; `verify_seal()` gate |
| 4 | Hallucination / invalid-output containment | `hallucination_containment` scenario |
| 5 | Autonomous self-healing | Checkpoint restore in every scenario |
| 6 | Checkpoint restoration | `disk_write_interrupt`, `partial_checkpoint` scenarios |
| 7 | Module / brick failure recovery | `broken_brick`, `80_percent_brick_failure`, `dependency_failure` |
| 8 | Recovery without manual intervention | `recovery_loop_failure` scenario |

---

## Validation stages

### Stage 1 — Unit correctness (pytest)

Run: `pytest tests/test_stitch_brick.py -v`

Verifies that every individual component behaves correctly in isolation:
- `BrickModule` produces valid / invalid seals as expected per fault mode
- `StrandChannel` detects tampered messages
- `ProtectedSpine` enforces triple verification and rejects unverified state
- `VerificationGate` catches structural, hash, and semantic failures independently
- `FaultInjector` is deterministic: same seed → same target

**Pass criterion:** 42/42 tests pass, zero failures.

### Stage 2 — End-to-end single run

Run: `python run_validation.py --tests 1 --scenario <NAME> --seed <N>`

One complete inject → detect → quarantine → restore → verify cycle.
Inspect the output to confirm:
- `detected=True`
- `quarantined=True`
- `recovered=True`
- `ledger_intact=True`
- `seal_before == seal_after`

**Pass criterion:** All five conditions met for every scenario.

### Stage 3 — 1 000-run batch

Run: `python run_validation.py --tests 1000 --scenario <NAME>`

**Pass criteria (per scenario):**
- Pass rate ≥ 99.0 %
- False negatives = 0
- Ledger seal mismatches = 0
- Recovery success rate ≥ 99.0 %

### Stage 4 — 10 000-run batch

Run: `python run_validation.py --tests 10000 --scenario <NAME>`

**Pass criteria:**
- Pass rate ≥ 99.5 %
- False negatives = 0
- All ledger chains verified intact

### Stage 5 — Cross-scenario sweep

Run all eleven scenarios at 1 000 runs each:
```
python run_validation.py --tests 1000 --scenario byte_corruption
python run_validation.py --tests 1000 --scenario ledger_drift
python run_validation.py --tests 1000 --scenario 80_percent_brick_failure
python run_validation.py --tests 1000 --scenario hallucination_containment
python run_validation.py --tests 1000 --scenario message_tamper
python run_validation.py --tests 1000 --scenario broken_brick
python run_validation.py --tests 1000 --scenario network_delay
python run_validation.py --tests 1000 --scenario dependency_failure
python run_validation.py --tests 1000 --scenario recovery_loop_failure
python run_validation.py --tests 1000 --scenario disk_write_interrupt
python run_validation.py --tests 1000 --scenario partial_checkpoint
```

Then review the aggregate:
```
python run_validation.py --report
```

---

## Metrics tracked

| Metric | Description |
|--------|-------------|
| `total_tests` | Number of independent cycles run |
| `passed` | Cycles where detect + quarantine + recover + ledger_intact all succeeded |
| `failed` | Cycles that did not fully pass |
| `ledger_seal_mismatches` | Runs where chain_seal_after ≠ chain_seal_before |
| `drift_events_detected` | Faults caught by VerificationGate or availability monitor |
| `drift_events_recovered` | Runs where checkpoint restore succeeded |
| `quarantine_events` | Runs where bad data was logged to /quarantine/ |
| `recovery_success_rate` | drift_events_recovered / total_tests |
| `mean_recovery_time_ms` | Average wall time for the detect + restore phase |
| `max_recovery_time_ms` | Worst-case recovery time |
| `false_positives` | Detected fault but fault_type was "none" |
| `false_negatives` | Fault injected but not detected |
| `cpu_usage_pct` | Host CPU at end of batch (if psutil installed) |
| `ram_usage_mb` | Host RAM used at end of batch (if psutil installed) |

---

## Evidence language

All reports use precise wording:

- ✓ "Under the tested simulation conditions…"
- ✓ "Observed zero undetected ledger drift across N runs…"
- ✓ "Recovered successfully in X/Y runs…"
- ✓ "Failed in Z case(s) and logged to proof/failures_*…"

Claims are **not** made about behaviour outside the simulation boundary.

---

## Reproducibility requirements

1. **Seeds are always saved** — every `SingleRunResult` records its seed
2. **Checkpoint envelope seals** — every on-disk checkpoint carries a SHA-256 of its contents; corrupted files are detected and skipped automatically
3. **JSONL run logs** — one line per run, enabling trend analysis over time
4. **Minimum environment:** Python 3.10+, 8 GB RAM, any OS (tested on Windows 10 and Linux)
5. **No external dependencies** beyond `cryptography` (already required by `sb_712`)

Replay any specific run:
```
python run_validation.py --tests 1 --scenario byte_corruption --seed 42
```

---

## Investigating failures

When a run fails, the failure record is in `proof/failures_<scenario>_<ts>.json`.  Each entry contains:
- `test_id`, `seed` — replay the exact run
- `fault_type`, `fault_target` — what was injected
- `seal_before`, `seal_after` — compare ledger state
- `failure_reason` — human-readable cause

Use `python run_validation.py --report` to list all generated reports.

---

## Trend tracking

Run the same scenario periodically and compare `mean_recovery_time_ms` and `recovery_success_rate` across reports.  Improvement looks like:

```
2025-01-01  recovery_success_rate=96.2%  mean_recovery_ms=420
2025-03-01  recovery_success_rate=99.8%  mean_recovery_ms=115
```

The JSONL files in `logs/` contain the raw data for any charting tool.
