# SB-712 Stitch Brick — Architecture

## Overview

SB-712 Stitch Brick is a fault-tolerant, self-healing computational framework built on a principle of _zero trust without verification_.  Every state transition must pass triple verification before it may touch the protected Spine.

---

## Directory layout

```
sb-712/
├── src/
│   ├── sb688/              # Data integrity kernel (BlockStore, WAL, Merkle, ECC, …)
│   └── stitch_brick/       # Validation framework (this document)
│       ├── brick.py        # BrickModule — computational units
│       ├── strand.py       # StrandChannel — tamper-evident message transport
│       ├── spine.py        # ProtectedSpine — hash-chained trusted state store
│       ├── braid.py        # BraidOrchestrator + VerificationGate
│       ├── fault_injector.py  # Deterministic fault injection
│       ├── metrics.py      # SingleRunResult, BatchMetrics, MetricsCollector
│       ├── disk_io.py      # CheckpointDiskManager, QuarantineDiskManager
│       ├── validator.py    # ValidationRunner — end-to-end orchestration
│       └── proof_generator.py  # Report generation (JSON / Markdown / summary)
├── sb_712/                 # SB-712 kernel (ProofLedger, RecoveryOrchestrator, …)
├── tests/
│   ├── test_stitch_brick.py   # 42 fault-injection pytest tests (NEW)
│   └── …                      # 273 existing kernel tests
├── run_validation.py       # CLI entry point
├── checkpoints/            # On-disk checkpoint snapshots
├── quarantine/             # Quarantine log files
├── proof/                  # Failure analysis + ledger integrity artefacts
├── reports/                # JSON / Markdown / executive summary reports
└── logs/                   # Per-run JSONL log files
```

---

## Core components

### BrickModule (`brick.py`)

A computational unit that:
- Takes `input_data: bytes` and returns a `BrickOutput` with a **SHA-256 seal**
- Supports six fault modes: `byte_corruption`, `hash_mismatch`, `crash`, `hallucinate`, `degraded_slow`, `none`
- Tracks its own health state: `HEALTHY → DEGRADED → FAILED → QUARANTINED → RECOVERING → HEALTHY`

The honest computation is `SHA-256(input || brick_id)`.  This is deterministic and seed-reproducible.

### StrandChannel (`strand.py`)

One-directional tamper-evident message transport between a brick and the Braid collector:
- Each `MessageEnvelope` carries a `seal = SHA-256(sender_id | receiver_id | payload)`
- `inject_tamper()` corrupts the next payload while keeping the original seal → detected on `receive()`
- `set_delay(ms)` simulates network latency; active delay is treated as an availability anomaly

### ProtectedSpine (`spine.py`)

The system's single source of truth:
- Wraps `sb_712.system.ProofLedger` (hash-chained append-only ledger)
- `propose_state()` runs **three independent verification passes** before committing
- Any failure in structural / behavioral / chain-integrity check raises `SpineVerificationError`
- `chain_seal()` = `SHA-256(all entry seals)` — a fingerprint of the entire history
- `verify_integrity()` re-walks the full chain from `GENESIS`

### BraidOrchestrator + VerificationGate (`braid.py`)

The Braid routes input through all healthy bricks and enforces the three-gate protocol before any output reaches the Spine:

| Gate | Check | Detects |
|------|-------|---------|
| Structural | payload is non-empty bytes | empty / null output |
| Hash | `seal == SHA-256(payload)` | byte corruption, hash mismatch |
| Semantic | `payload == SHA-256(input \|\| brick_id)` | hallucinated output |

Unavailable bricks (FAILED / QUARANTINED) are counted as availability faults — not silently skipped.

### FaultInjector (`fault_injector.py`)

Eleven reproducible fault scenarios, all seed-driven:

| Scenario | What breaks |
|----------|-------------|
| `byte_corruption` | One byte flipped in brick output |
| `ledger_hash_mismatch` / `ledger_drift` | Wrong seal supplied by brick |
| `broken_brick` | Brick crashes on `compute()` |
| `80_percent_brick_failure` | 8/10 bricks crash simultaneously |
| `message_tamper` | Strand payload corrupted in transit |
| `hallucination_containment` | Brick returns random payload (semantic gate catches it) |
| `network_delay` | Strand latency anomaly flagged by availability monitor |
| `disk_write_interrupt` | Checkpoint entry list truncated mid-write |
| `partial_checkpoint` | Random field removed from snapshot |
| `dependency_failure` | Brick-000 crash cascades to Brick-001 |
| `recovery_loop_failure` | All 10 bricks fail simultaneously |

### ValidationRunner (`validator.py`)

Orchestrates one complete cycle per `run_single_test(scenario, test_id, seed)`:

```
1. Build fresh BraidOrchestrator (10 bricks, seed-deterministic)
2. Process BASELINE_INPUT → all bricks commit to Spine
3. Capture chain_seal_before, save checkpoint to /checkpoints/
4. Inject fault (FaultInjector, same seed)
5. Process BASELINE_INPUT again → Braid + Gate detect fault
6. Log detection failures to /quarantine/
7. Load last valid checkpoint, rebuild clean Braid, replay baseline
8. Verify chain_seal_after == chain_seal_before AND ledger_integrity == True
9. Return SingleRunResult with all evidence fields
```

### ProofGenerator (`proof_generator.py`)

Produces six artefacts per batch run:

| File | Location | Contents |
|------|----------|----------|
| `<scenario>_<ts>.json` | `reports/` | Full metrics + all run results |
| `<scenario>_<ts>.md` | `reports/` | Markdown report with precise findings |
| `executive_summary_<scenario>_<ts>.md` | `reports/` | One-page summary |
| `failures_<scenario>_<ts>.json` | `proof/` | Only failed runs — for investigation |
| `ledger_integrity_<scenario>_<ts>.json` | `proof/` | Per-run ledger seal comparison |
| `run_log_<scenario>_<ts>.jsonl` | `logs/` | One JSON line per run (for trend analysis) |

---

## Core laws (locked)

1. **NO ACTIVE STATE BECOMES TRUSTED STATE WITHOUT VERIFICATION.**
2. **Nothing unverified touches the Spine.**
3. **Every trusted state must be verified 3 times.**
4. If data cannot be verified → isolate to quarantine → log → purge or restore from last healthy checkpoint.
5. The system must preserve ledger integrity under simulated failures.

---

## Reproducibility guarantee

Every run is fully reproducible:
- `seed = base_seed + test_id` → same brick targeted, same bytes corrupted
- Checkpoint files include a `SHA-256` envelope seal — corrupted files are detected and skipped
- `run_log_*.jsonl` records seed, all seals, and timing for every test

Replay any run:
```
python run_validation.py --tests 1 --scenario byte_corruption --seed 42
```
