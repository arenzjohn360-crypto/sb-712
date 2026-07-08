# SB-712 Stitch Brick — Validation Report

**Generated:** 2026-07-08T01:00:40+00:00  
**Scenario:** `hallucination_containment`  
**Total runs:** 1000

---

## Summary Metrics

| Metric | Value |
|--------|-------|
| Total tests | 1000 |
| Passed | 1000 |
| Failed | 0 |
| Pass rate | 100.00% |
| Recovery success rate | 100.00% |
| Mean recovery time | 27.733 ms |
| Max recovery time | 50.121 ms |
| Ledger seal mismatches | 0 |
| Drift events detected | 1000 |
| Drift events recovered | 1000 |
| Quarantine events | 1000 |
| False positives | 0 |
| False negatives | 0 |

---

## Precise Findings

> *Under the tested simulation conditions for scenario `hallucination_containment`:*

- Observed **zero undetected ledger drift** across 1000 runs.
- Recovered successfully in **1000/1000** runs.
- **Zero false negatives** — every injected fault was detected.

---

## Seeds Used

First 10 seeds: `[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]`  
Total seeds: 1000  
_(Replay any run: `python run_validation.py --tests 1 --scenario hallucination_containment --seed <N>`)_
