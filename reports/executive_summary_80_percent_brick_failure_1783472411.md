# SB-712 Stitch Brick — Executive Summary

**Date:** 2026-07-08T01:00:11+00:00
**Scenario:** 80_percent_brick_failure
**Runs completed:** 1000

## What was tested

The SB-712 Stitch Brick validation framework ran 1000 independent simulation cycles under the `80_percent_brick_failure` scenario.  Each cycle injected a fault, attempted detection, quarantine, checkpoint-based recovery, and ledger verification.

## What was observed

Under the tested simulation conditions with 1000 runs:

- **Detection rate:** 1000/1000 (100.0%) — faults were caught by the VerificationGate.
- **Recovery rate:** 1000/1000 (100.0%) — system restored to healthy state.
- **Ledger integrity:** All ledger chains verified intact after recovery.
- **False negatives:** 0 (faults injected but not detected).
- **Mean recovery time:** 19.027 ms
- **Max recovery time:** 33.091 ms

## Caveats

These results reflect simulation behaviour only.  No claim of universal proof is made.  Results are reproducible: rerun with the seeds listed in the full report to obtain comparable results on any machine meeting the minimum requirements (Python 3.10+, 8 GB RAM).
