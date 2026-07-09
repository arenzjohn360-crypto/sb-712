# SB712_MASTER — Canonical Production Snapshot

Generated: 2026-07-09  
Basis: automated dedup scan of `arenzjohn360-crypto/sb-712`

## Folder layout

```
SB712_MASTER/
├── sb_712/              # Core SB-712 package
│   ├── security.py      # JWT auth, rate limiter, audit trail, service blueprints
│   ├── system.py        # Trust gate, proof ledger, heartbeat monitor
│   ├── recovery.py      # Convoy + return-check recovery orchestrator
│   ├── corruption_guard.py
│   ├── immunity_node.py
│   ├── learning_node.py
│   ├── lesson_store.py
│   ├── checkpoint.py
│   ├── incident.py
│   ├── prevention.py
│   ├── report.py
│   ├── sb689.py         # SB-689 free-flow pipeline
│   └── service_host.py
├── sb688/               # SB-688 storage engine (from src/sb688)
│   ├── store.py         # BlockStore — atomic SHA-256 writes
│   ├── wal.py           # WAL + DurableStore
│   ├── replica.py       # N-replica quorum set
│   ├── merkle.py        # Merkle tree proofs
│   ├── ecc.py           # XOR-parity erasure coding
│   ├── crypto.py        # AES-256-GCM encryption
│   ├── clock.py         # Lamport + vector clocks
│   ├── integrity.py     # Self-healing integrity checker
│   └── rule_of_three.py # TrustGate
├── stitch_brick/        # Stitch Brick validation (from src/stitch_brick)
│   ├── validator.py
│   ├── braid.py
│   ├── brick.py
│   ├── strand.py
│   ├── spine.py
│   ├── fault_injector.py
│   ├── metrics.py
│   ├── proof_generator.py
│   └── disk_io.py
├── intelligence/        # IronBraid Radiant Core
│   ├── ava_coordinator.py
│   ├── vera_gate.py
│   ├── forecast_node.py
│   ├── mask_evaluator.py
│   ├── receptor_registry.py
│   └── fieldview_encoder.py
├── recovery/            # Recovery layer
│   ├── checkpoint_validator.py
│   ├── phoenix_triangle.py
│   ├── rollback_engine.py
│   └── route_healer.py
├── run_validation.py    # Validation CLI entry point
├── run_sb712_ironbraid.py # IronBraid run entry point
├── pyproject.toml
└── requirements.txt
```

## Dedup notes

- All 48 modules carry unique SHA-256 content hashes.
- Two `__init__.py` files are intentionally empty (hash `e3b0c44298fc`) — not duplicates.
- `sb_712/sb689.py` (SB-689 free-flow pipeline) and `sb688/` (SB-688 storage engine) are
  distinct subsystems despite similar names.
- No redundant files were found or removed.

## Test evidence

418/418 tests pass. See `../proof/test_checklist.md`.
