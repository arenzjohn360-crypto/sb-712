# SB-712 — IronBraid Radiant Core

**Universal Data Integrity Intelligence System**

> *Designed for radiation-style fault resilience and extreme-environment data integrity.*

---

## ⚠ Honest Disclaimer

**Software alone cannot guarantee survival of actual space radiation events.**
Cosmic and ionising radiation can cause single-event upsets, data corruption,
latch-up, and outright hardware failure that no amount of software can prevent.
NASA and ESA both document radiation effects as a genuine threat to spacecraft
electronics (see [NASA LLIS](https://llis.nasa.gov/lesson/824) and
[ESA Radiation Effects](https://www.esa.int/Enabling_Support/Space_Engineering_Technology/Radiation_satellites_unseen_enemy)).

For **actual deployment** in radiation environments you **must** pair this
software with:

- ECC memory
- Redundant, radiation-hardened processors
- Hardened storage media
- Physical shielding
- Watchdog power cycling
- Formal, independent radiation testing

**No unverifiable guarantees are made by this project.**

---

## Architecture Overview

SB-712 IronBraid Radiant Core treats every file, node, command, memory
pocket, checkpoint, AI decision, and recovery action as **untrusted until
verified, validated, and certified**.

### Core State Lifecycle

```
UNVERIFIED → VERIFIED → VALIDATED → CERTIFIED → ACTIVE
                                             ↘ QUARANTINED → (repair) → VERIFIED
                                             ↘ FAILED
```

### Key Components

| Component | Purpose |
|---|---|
| **Spine** | Protected truth rail; holds core config and manifest |
| **IronBraid Data Vault** | Sealed BRIC files with hash verification |
| **Triple-Certification Gate** (VERA) | Hash check + validation + certification mark |
| **Ledger** | Hash-chained append-only audit log with two mirrors |
| **Phoenix Triangle** | Three dormant recovery nodes; 2-of-3 majority required |
| **Intelligence Layer** | FieldView encoder, forecast, mask evaluator, AVA coordinator |
| **Quarantine** | Isolation zone for unverified or corrupted data |
| **Proof Reports** | Mandatory JSON artifacts proving every integrity scan |

---

## Directory Structure

```
sb-712/
├── spine/                  # Protected truth rail (config & manifests)
├── data/
│   ├── intake/             # Unverified incoming data
│   ├── quarantine/         # Isolated corrupted items
│   ├── active_brics/       # Certified active BRIC files
│   ├── offline_brics/      # Offline/warm BRIC storage
│   ├── cold_storage/       # Cold archival storage
│   └── replicas/           # Replica copies
├── ledger/                 # Hash-chained JSONL ledger + two mirrors
├── checkpoints/
│   ├── ghost/              # Ghost checkpoint (stealth baseline)
│   ├── phoenix_a/          # Phoenix A recovery node
│   ├── phoenix_b/          # Phoenix B recovery node
│   └── phoenix_c/          # Phoenix C recovery node
├── intelligence/           # Python intelligence modules
├── recovery/               # Python recovery modules
├── tests/                  # pytest test suite
├── reports/daily/proof/    # Proof report JSON artifacts
├── ui/                     # Control-room web UI (static)
├── run_sb712_ironbraid.py  # Cross-platform Python entrypoint
└── RUN_SB712_IRONBRAID.bat # Windows launcher
```

---

## Quickstart

### Requirements

- Python 3.9+
- `pytest` (for tests only)

```bash
pip install -r requirements.txt
```

### Run the integrity scan

```bash
python run_sb712_ironbraid.py
```

This will:
1. Ensure all required folders exist.
2. Run a hash-based integrity scan over `spine/` and `ledger/`.
3. Write a proof-report JSON file to `reports/daily/proof/`.

**Windows:**

```
RUN_SB712_IRONBRAID.bat
```

### Run tests

```bash
pytest tests/ -q
```

### View the Control Room UI

Open `ui/index.html` in a browser, or serve it locally:

```bash
python -m http.server 8080 --directory ui
```

---

## Intelligence Layer

| Module | Role |
|---|---|
| `intelligence/fieldview_encoder.py` | File hash scanning and mutation detection |
| `intelligence/forecast_node.py` | Risk prediction from field snapshots |
| `intelligence/mask_evaluator.py` | Proximity-to-Spine risk scoring |
| `intelligence/vera_gate.py` | Triple-certification gate (VERA) |
| `intelligence/ava_coordinator.py` | Workflow coordination under owner authority |
| `intelligence/receptor_registry.py` | Signal-permission registry for nodes |

## Recovery Layer

| Module | Role |
|---|---|
| `recovery/phoenix_triangle.py` | Three-node recovery cluster with lineage checks |
| `recovery/rollback_engine.py` | Rollback to most recent certified checkpoint |
| `recovery/route_healer.py` | BFS bypass routing around failed nodes |
| `recovery/checkpoint_validator.py` | Continuity and integrity validation |

---

## Deployment Levels

| Level | Environment | Key Requirements |
|---|---|---|
| 1 | Local business / JGA | Windows, Python, file monitoring |
| 2 | Edge devices, kiosks | Offline-first, signed intake, cold storage |
| 3 | Industrial / harsh | Redundant nodes, hot/warm/cold replicas |
| 4 | Space-style research | ECC RAM, rad-hardened hardware, formal testing |

---

## Contributing

All contributions must pass `pytest tests/ -q` and include proof that
imports resolve cleanly (`python -c "import intelligence.vera_gate"`).

---

## License

See `LICENSE` if present. This scaffold is released for engineering
research and evaluation purposes only.
