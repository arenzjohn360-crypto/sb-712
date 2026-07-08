# SB-712 IronBraid Radiant Core — Installation Guide

> **Target platform:** Windows 10 · Python 3.10+ · 8 GB RAM minimum  
> **Time required:** ~5 minutes

---

## Quick Start (Windows)

1. Install **Python 3.10+** from <https://python.org> — tick **"Add Python to PATH"** during setup.
2. Double-click **`INSTALL.bat`** in this folder. It will:
   - Upgrade pip
   - Install all Python packages (SB688 + SB-712 + dev extras)
   - Verify all imports resolve cleanly
   - Run the full test suite (418 tests)
3. Copy `.env.example` → `.env` and fill in your secrets (see [Environment Variables](#environment-variables) below).
4. Double-click **`RUN_SB712_IRONBRAID.bat`** to run your first integrity scan.

---

## Manual Install (any OS)

```bash
# 1. Clone or download the repository
git clone https://github.com/arenzjohn360-crypto/sb-712.git
cd sb-712

# 2. Install all dependencies (Python 3.10+ required)
pip install -e ".[dev]"

# 3. Copy and fill in the environment file
copy .env.example .env     # Windows
# cp .env.example .env     # Linux / macOS

# 4. Run the test suite to confirm everything works
pytest tests/ -q

# 5. Run the integrity scan
python run_sb712_ironbraid.py
```

---

## What Gets Installed

| Package | Location | Purpose |
|---|---|---|
| `sb688` | `src/sb688/` | Low-level data integrity kernel (storage, WAL, encryption, Merkle, ECC, clocks) |
| `stitch_brick` | `src/stitch_brick/` | Fault-injection validation framework |
| `sb_712` | `sb_712/` | Resilience engine (trust gates, recovery convoy, Phoenix nodes, security layer) |
| `intelligence` | `intelligence/` | VERA gate, forecast, mask evaluator, AVA coordinator |
| `recovery` | `recovery/` | Phoenix Triangle, rollback engine, route healer, checkpoint validator |

---

## Environment Variables

Copy `.env.example` to `.env` and set the following:

| Variable | Description | Example |
|---|---|---|
| `SB712_JWT_SECRET` | 32-byte secret for JWT signing | `openssl rand -hex 32` |
| `SUPABASE_URL` | Your Supabase project URL | `https://abc.supabase.co` |
| `SUPABASE_ANON_KEY` | Supabase anon/public key | from Supabase dashboard |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key | from Supabase dashboard |
| `SB712_AUDIT_LOG_KEY` | 32-byte key for audit log encryption | `openssl rand -hex 32` |
| `SB712_ALLOWED_ORIGINS` | CORS origins (comma-separated) | `https://app.sb712.local` |

> **Supabase is optional** — the core Python integrity engine works without it.  
> JWT auth and the encrypted audit trail require `SB712_JWT_SECRET` and `SB712_AUDIT_LOG_KEY`.

---

## Running the System

### Integrity scan
```bash
# Windows (double-click or run from command prompt)
RUN_SB712_IRONBRAID.bat

# Cross-platform
python run_sb712_ironbraid.py
```
Produces a proof-report JSON in `reports/daily/proof/`.

### Test suite
```bash
pytest tests/ -q
# Expected: 418 passed, 0 failed, 0 warnings
```

### Validation framework
```bash
# Run 100 fault-injection cycles for a specific scenario
python run_validation.py --tests 100 --scenario byte_corruption

# Available scenarios:
#   byte_corruption · ledger_drift · broken_brick · network_delay
#   hallucination_containment · recovery_loop_failure · spine_tamper
#   cascade_failure · 80_percent_brick_failure · multi_fault · none

# Exact replay with seed
python run_validation.py --tests 1 --seed 42

# List all existing reports
python run_validation.py --report
```

### Service heartbeat
```bash
python -m sb_712.service_host --heartbeat-once
```
Returns a JSON blob with `heartbeat.level`, `heartbeat.score`, and full security/Supabase config.

### Control Room UI
```bash
python -m http.server 8080 --directory ui
# Open http://localhost:8080 in a browser
```

---

## Windows Service (Optional)

Run **as Administrator** in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-sb712-service.ps1
```

This installs **SB712SecurityHost** as a Windows service that starts automatically at boot.

To check status:
```powershell
Get-Service SB712SecurityHost
```

To uninstall:
```powershell
Stop-Service SB712SecurityHost
sc.exe delete SB712SecurityHost
```

---

## Directory Layout

```
sb-712/
├── INSTALL.bat                  ← Windows one-click installer  ← START HERE
├── INSTALL.md                   ← This file
├── RUN_SB712_IRONBRAID.bat      ← Windows one-click integrity scan
├── run_sb712_ironbraid.py       ← Cross-platform integrity scan entrypoint
├── run_validation.py            ← Fault-injection validation CLI
├── .env.example                 ← Copy to .env and fill in secrets
├── pyproject.toml               ← Python package definition
├── requirements.txt             ← Flat requirements file
│
├── src/
│   ├── sb688/                   ← Data integrity kernel
│   └── stitch_brick/            ← Validation framework
│
├── sb_712/                      ← Resilience engine
│   ├── security.py              ← JWT, RBAC, AES-256-GCM audit log
│   ├── service_host.py          ← Service host / heartbeat
│   ├── system.py                ← Proof ledger, heartbeat monitor
│   ├── recovery.py              ← Recovery convoy
│   ├── checkpoint.py            ← Checkpoint registry
│   ├── corruption_guard.py      ← Corruption detection
│   ├── immunity_node.py         ← Immunity tracking
│   ├── learning_node.py         ← Learning pipeline
│   ├── lesson_store.py          ← Persistent lesson storage
│   ├── incident.py              ← Incident taxonomy
│   ├── prevention.py            ← Prevention rules
│   ├── report.py                ← Report generation
│   └── sb689.py                 ← SB-689 free-flow pipeline
│
├── intelligence/                ← Intelligence layer
│   ├── vera_gate.py             ← Triple-certification gate (VERA)
│   ├── ava_coordinator.py       ← Workflow coordinator
│   ├── fieldview_encoder.py     ← File hash / mutation detection
│   ├── forecast_node.py         ← Risk prediction
│   ├── mask_evaluator.py        ← Spine-proximity scoring
│   └── receptor_registry.py     ← Signal-permission registry
│
├── recovery/                    ← Recovery layer
│   ├── phoenix_triangle.py      ← 3-node cluster (2-of-3 majority)
│   ├── rollback_engine.py       ← Checkpoint rollback
│   ├── route_healer.py          ← BFS bypass routing
│   └── checkpoint_validator.py  ← Checkpoint integrity checks
│
├── spine/                       ← Protected truth rail (JSON configs)
├── ledger/                      ← Hash-chained JSONL audit ledger
├── checkpoints/                 ← Ghost + Phoenix A/B/C checkpoints
├── data/                        ← intake / quarantine / active / cold / replicas
├── supabase/migrations/         ← SQL schema + rollback scripts
├── docs/                        ← Architecture and command hierarchy docs
├── scripts/                     ← install-sb712-service.ps1
├── ui/                          ← Control Room web UI (static HTML/CSS/JS)
├── tests/                       ← pytest test suite (418 tests)
├── reports/                     ← Generated integrity scan reports
├── logs/                        ← Validation run logs
└── proof/                       ← Fault-injection proof artifacts
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Python not found on PATH` | Re-install Python and tick "Add Python to PATH" |
| `ModuleNotFoundError: cryptography` | Run `pip install cryptography>=41.0` |
| `ModuleNotFoundError: sb688` | Run `pip install -e ".[dev]"` from the repo root |
| `ModuleNotFoundError: intelligence` | Run from the repo root directory, not a subdirectory |
| Tests fail with `DeprecationWarning` | Already fixed — make sure you have the latest code |
| Service install fails | Run PowerShell as Administrator |
| `.env` errors | Copy `.env.example` to `.env` and fill in your keys |

---

## System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 64-bit | Windows 10/11 64-bit |
| Python | 3.10 | 3.11 or 3.12 |
| RAM | 4 GB | 8 GB |
| Disk | 500 MB free | 2 GB free |
| Network | Not required | Required for Supabase |

---

## Verification Checklist

After installing, confirm each item passes:

- [ ] `python --version` shows 3.10 or higher
- [ ] `pytest tests/ -q` shows **418 passed, 0 failed**
- [ ] `python run_sb712_ironbraid.py` completes without errors and writes a report to `reports/`
- [ ] `python -m sb_712.service_host --heartbeat-once` returns `"level": "HEALTHY"`
- [ ] `python run_validation.py --tests 10 --scenario byte_corruption` shows **10/10 recovered**
