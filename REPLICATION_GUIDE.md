<!--
  ♛  REPLICATION GUIDE  ·  SB-712 + SB688 WORKSPACE  ♛
  End-to-end setup and core code instructions for every system in this repo
-->

# ♛ REPLICATION GUIDE

## **SB-712 + SB688 — Complete Workspace Setup & Core Code Instructions**

> *"No active state becomes trusted state without Verification → Re-Verification → Certification."*

---

```
  ████████████████████████████████████████████████████████████████████
  ██                                                                ██
  ██    ♛  R E P L I C A T I O N   G U I D E  ·  v 1 . 0  ♛      ██
  ██    SB-712 Data Resilience  ·  SB688 Integrity  ·  Node.js     ██
  ██                                                                ██
  ████████████████████████████████████████████████████████████████████
```

---

## TABLE OF CONTENTS

1. [Workspace Overview](#1-workspace-overview)
2. [Prerequisites](#2-prerequisites)
3. [Environment Setup](#3-environment-setup)
4. [SB688 — Python Data Integrity Library](#4-sb688--python-data-integrity-library)
5. [SB-712 — Python Resilience Engine](#5-sb-712--python-resilience-engine)
6. [SB688 — Node.js Runtime](#6-sb688--nodejs-runtime)
7. [SB688 Chaos Stress Suite](#7-sb688-chaos-stress-suite)
8. [SB-712 Windows Service](#8-sb-712-windows-service)
9. [Running All Tests](#9-running-all-tests)
10. [Key Concepts Quick Reference](#10-key-concepts-quick-reference)

---

## 1. Workspace Overview

This repository contains two interlocking systems that share the same verification-first doctrine:

| System | Language | Location | Role |
|---|---|---|---|
| **SB688** (Python library) | Python ≥ 3.10 | `src/sb688/` | Low-level data integrity kernel: storage, WAL, checksums, encryption, Merkle proofs, replication, ECC, clocks |
| **SB-712** (Python engine) | Python ≥ 3.10 | `sb_712/` | High-level resilience engine: trust gates, incident management, recovery convoy, Phoenix nodes, proof ledger, security layer |
| **SB688** (Node.js runtime) | Node.js ≥ 18 | `SB688_systemIntegrity.js` | Lightweight JS self-healing state machine (Golden Integrity ↔ HEALING cycle) |
| **Chaos Stress Suite** | Node.js ≥ 18 | `SB688_chaos_stress_suite.js` | 10,000-iteration industrial simulation proving 100 % autonomous recovery |

---

## 2. Prerequisites

### Python systems (SB688 + SB-712)

```bash
# Python 3.10 or higher required
python --version   # must be ≥ 3.10

# pip must be available
pip --version
```

### Node.js systems (SB688 runtime + chaos suite)

```bash
# Node.js 18 or higher required
node --version   # must be ≥ 18

# No npm packages are required — both JS files are self-contained
```

### Windows Service (optional — Windows 10/11 only)

```
- PowerShell 5.1 or later (built into Windows 10)
- Administrator privileges
- Python on PATH (the 'py' launcher is used by default)
```

---

## 3. Environment Setup

### 3.1 Clone and enter the repository

```bash
git clone https://github.com/arenzjohn360-crypto/sb-712.git
cd sb-712
```

### 3.2 Create the `.env` file

```bash
# Copy the template
cp .env.example .env
```

Open `.env` and fill in your real values:

```bash
SB712_JWT_SECRET=<32-byte-or-longer-secret>
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=<your-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>
SB712_AUDIT_LOG_KEY=<32-byte-or-longer-audit-key>
SB712_ALLOWED_ORIGINS=https://app.sb712.local
```

> **Security law:** Never commit your real `.env` file. The `.gitignore` already excludes it.

### 3.3 Install Python dependencies (both SB688 and SB-712 together)

```bash
pip install -e ".[dev]"
```

This single command installs:
- The `sb688` Python package from `src/sb688/`
- The `sb_712` Python package from `sb_712/`
- `cryptography>=41.0` (required by `sb_712/security.py`)
- `pytest>=7.4` and `pytest-timeout>=2.2` (dev/test dependencies)

---

## 4. SB688 — Python Data Integrity Library

**Location:** `src/sb688/`  
**Entry point:** `from sb688 import BlockStore, DurableStore, IntegrityChecker, ...`

### 4.1 Module map

```
src/sb688/
├── store.py       BlockStore        — SHA-256 per-block checksums, atomic puts, crash simulation
├── wal.py         WriteAheadLog     — three-phase commit (prepare → commit → apply), crash recovery
│                  DurableStore      — WAL-backed high-level key/value store
├── integrity.py   IntegrityChecker  — full-store scan, self-heal from replica, tamper-evident audit log
├── crypto.py      EncryptedStore    — AES-256-GCM authenticated encryption, key rotation
├── merkle.py      MerkleTree        — SHA-256 Merkle tree, write-once immutability proofs
├── replica.py     ReplicaSet        — quorum writes (⌊N/2⌋+1), partition injection, sync
├── ecc.py         ECCEncoder        — XOR-parity erasure coding (RAID-5 style, 1-of-N recovery)
└── clock.py       LamportClock      — logical clock for causality ordering
                   VectorClock       — per-node vector clock for distributed causality
```

### 4.2 Core replication — minimal working example

```python
import tempfile, os
from sb688 import BlockStore, DurableStore, WriteAheadLog, IntegrityChecker
from sb688 import EncryptedStore, MerkleTree, ReplicaSet, ECCEncoder
from sb688 import LamportClock, VectorClock

# ── 1. Atomic block storage with SHA-256 checksums ──────────────────────────
with tempfile.TemporaryDirectory() as d:
    store = BlockStore(d)
    store.put("key1", b"hello world")
    assert store.get("key1") == b"hello world"
    print("BlockStore: OK")

# ── 2. Write-Ahead Log — three-phase commit ─────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    wal  = WriteAheadLog(os.path.join(d, "wal.log"))
    base = BlockStore(d)
    ds   = DurableStore(wal, base)
    ds.put("invoice_001", b'{"amount":1000}')
    assert ds.get("invoice_001") == b'{"amount":1000}'
    print("DurableStore/WAL: OK")

# ── 3. Self-healing integrity scan ──────────────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    store   = BlockStore(d)
    replica = BlockStore(d + "_replica")
    store.put("record_a", b"trusted data")
    replica.put("record_a", b"trusted data")
    checker = IntegrityChecker(store, replica)
    events  = checker.scan_and_heal()
    print(f"IntegrityChecker: {len(events)} events, self-healed: OK")

# ── 4. AES-256-GCM encryption ───────────────────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    key  = os.urandom(32)
    base = BlockStore(d)
    enc  = EncryptedStore(base, key)
    enc.put("secret", b"classified payload")
    assert enc.get("secret") == b"classified payload"
    print("EncryptedStore AES-256-GCM: OK")

# ── 5. Merkle immutability proof ─────────────────────────────────────────────
tree = MerkleTree()
tree.append(b"block_0")
tree.append(b"block_1")
tree.append(b"block_2")
root  = tree.root()
proof = tree.proof(1)          # proof for leaf index 1
assert tree.verify_proof(proof, b"block_1", root)
print(f"MerkleTree root={root[:16]}... proof verified: OK")

# ── 6. Quorum replication ───────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    replicas = [BlockStore(os.path.join(d, f"r{i}")) for i in range(3)]
    rs = ReplicaSet(replicas, quorum=2)
    rs.put("tx_001", b"DEBIT 500")
    assert rs.get("tx_001") == b"DEBIT 500"
    print("ReplicaSet quorum-2-of-3: OK")

# ── 7. Erasure coding — XOR-parity RAID-5 ──────────────────────────────────
encoder = ECCEncoder(data_shards=4, parity_shards=1)
data    = b"sensor telemetry payload"
shards  = encoder.encode(data)
shards[2] = None               # simulate losing shard 2
recovered = encoder.decode(shards)
assert recovered == data
print("ECCEncoder RAID-5 parity recovery: OK")

# ── 8. Causality clocks ──────────────────────────────────────────────────────
lc = LamportClock()
t1 = lc.tick()
t2 = lc.tick()
assert t2 > t1
vc = VectorClock(node_id="node_A")
vc.tick()
print(f"LamportClock t={t2}, VectorClock={vc.vector}: OK")
```

---

## 5. SB-712 — Python Resilience Engine

**Location:** `sb_712/`  
**Entry point:** `from sb_712 import TrustGatePipeline, RecoveryOrchestrator, HeartbeatMonitor, ...`

### 5.1 Module map

```
sb_712/
├── system.py        Enums, SystemConfig, VerificationEvidence, QuarantineRecord,
│                    LedgerEntry, ProofLedger, TrustGateResult, SystemHealth,
│                    HeartbeatMonitor, TrustGatePipeline
├── incident.py      IncidentStudyRecord, IncidentType, IncidentStatus,
│                    SourceType, Severity, hunter rescan outcome constants
├── prevention.py    PreventionRule, PreventionRegistry
├── checkpoint.py    Checkpoint, CheckpointRegistry, CheckpointStatus, RollbackResult
├── recovery.py      RecoveryOrchestrator (Convoy + Emergency Rollback),
│                    ConvoyStage, ReturnCheckStage, PhoenixDecision
├── learning_node.py LearningNode — captures incident lessons into Memory Pockets
├── immunity_node.py ImmunityNode — builds prevention rules from lessons
├── report.py        generate_report — tamper-evident HTML/JSON audit report
├── security.py      JWTAuthManager, RateLimiter, EncryptedAuditTrail,
│                    TrustedOperationGateway, SupabaseSecurityBlueprint,
│                    build_runtime_manifest, render_env_template
└── service_host.py  CLI entry point for running SB-712 as a background service
```

### 5.2 Core replication — key subsystems

#### 5.2.1 Trust Gate Pipeline — Triple Verification Gate

```python
from sb_712 import (
    TrustGatePipeline, VerificationEvidence,
    TrustStatus, ClassificationStage, SystemConfig
)

config   = SystemConfig()          # verify_passes_required=3, thresholds=99.8/99.9
pipeline = TrustGatePipeline(config)

evidence = VerificationEvidence(
    structural_ok   = True,   # SHA-256 hash matched
    behavioral_ok   = True,   # runtime behavior matched baseline
    proof_ledger_ok = True,   # Merkle root + ledger cross-reference passed
)

result = pipeline.evaluate("artifact_id_abc", evidence)
assert result.status == TrustStatus.TRUSTED
assert result.stage  == ClassificationStage.TRUSTED
print(f"TrustGate: {result.status.value} — artifact promoted to Spine")
```

#### 5.2.2 Heartbeat Monitor — Autonomous Alert Levels

```python
from sb_712 import HeartbeatMonitor, HeartbeatLevel, SystemConfig

monitor = HeartbeatMonitor(SystemConfig())

# Healthy system
health = monitor.evaluate(
    heartbeat_score    = 100.0,
    node_readiness     = 1.0,
    recovery_readiness = 1.0,
    trust_ratio        = 1.0,
)
assert health.heartbeat_level == HeartbeatLevel.HEALTHY

# Degraded system — triggers Phoenix self-heal threshold
health_degraded = monitor.evaluate(
    heartbeat_score    = 99.85,   # between 99.8 and 99.9
    node_readiness     = 0.9,
    recovery_readiness = 0.8,
    trust_ratio        = 0.95,
)
assert health_degraded.heartbeat_level == HeartbeatLevel.SELF_HEALING
print(f"Heartbeat at 99.85 → {health_degraded.heartbeat_level.value}")
```

#### 5.2.3 Proof Ledger — Tamper-Evident Chain

```python
from sb_712 import ProofLedger, LedgerEntry

ledger = ProofLedger()

entry = LedgerEntry(
    event_type           = "VERIFICATION",
    object_id            = "artifact_id_abc",
    before_state         = "UNTRUSTED",
    after_state          = "TRUSTED",
    verification_result  = "PASSED",
    repair_result        = "N/A",
    certification_result = "CERTIFIED",
)
ledger.append(entry)

# Chain integrity must always pass
assert ledger.verify_integrity() is True
print(f"ProofLedger: {len(ledger.entries())} entries, chain integrity: OK")
```

#### 5.2.4 Recovery Convoy — Incident → Convoy → Rollback

```python
from sb_712 import (
    RecoveryOrchestrator, IncidentStudyRecord,
    IncidentType, IncidentStatus, SourceType, Severity,
    CheckpointRegistry, Checkpoint, CheckpointStatus
)

# Register a certified checkpoint (Golden Directive anchor)
registry   = CheckpointRegistry()
checkpoint = Checkpoint(
    project_id = "project_alpha",
    status     = CheckpointStatus.HEALTHY,
    certified  = True,
    snapshot   = {"manifest_hash": "abc123", "files": ["core.py"]},
    notes      = "Golden Directive — last certified state",
)
registry.add_checkpoint(checkpoint)

# Create an incident record
incident = IncidentStudyRecord(
    incident_type = IncidentType.CORRUPTION,
    source        = SourceType.HUNTER_NODE,
    severity      = Severity.HIGH,
    object_id     = "file_core.py",
    description   = "SHA-256 mismatch detected on core.py",
    status        = IncidentStatus.OPEN,
    project_id    = "project_alpha",
)

# Run the Recovery Convoy
orchestrator = RecoveryOrchestrator(registry)
result       = orchestrator.run(incident)

print(f"Recovery method : {result.method.value}")
print(f"Recovery success: {result.success}")
print(f"Convoy stages   : {[s.stage.value for s in (result.convoy_result.stages if result.convoy_result else [])]}")
```

#### 5.2.5 Quarantine State Machine

```python
from sb_712 import QuarantineRecord, QuarantineState

record = QuarantineRecord(
    object_id = "suspicious_file.tmp",
    reason    = "Unknown source, no proof-ledger record",
)
assert record.state == QuarantineState.ISOLATED

record.transition(QuarantineState.STUDYING, note="Behavioral analysis started")
record.transition(QuarantineState.REPAIRING, note="Pattern matched known-good; rebuilding")
record.transition(QuarantineState.RELEASED, note="Repair verified; releasing to Trust Gate")

print(f"Quarantine path: ISOLATED → STUDYING → REPAIRING → {record.state.value}")
```

#### 5.2.6 Security Layer — JWT + Rate Limiter + Encrypted Audit

```python
import os
from datetime import datetime, timezone, timedelta
from sb_712 import (
    JWTAuthManager, TokenClaims,
    RateLimiter, EncryptedAuditTrail,
)

# JWT — issue and verify a token
jwt_manager = JWTAuthManager(secret=os.urandom(32))
claims = TokenClaims(
    sub        = "operator_001",
    role       = "admin",
    issuer     = "sb712",
    audience   = "sb712-service",
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1),
    scopes     = ("read", "write", "certify"),
)
token          = jwt_manager.issue(claims)
verified_claims = jwt_manager.verify(token, audience="sb712-service")
print(f"JWT: issued for {verified_claims.sub}, role={verified_claims.role}")

# Rate limiter — max 5 requests per 60-second window
limiter = RateLimiter(max_calls=5, window_seconds=60)
for i in range(5):
    assert limiter.check("operator_001") is True
overflow = limiter.check("operator_001")
print(f"RateLimiter: 6th request blocked = {not overflow}")

# Encrypted audit trail — AES-256-GCM
audit = EncryptedAuditTrail(key=os.urandom(32))
audit.record(event_type="CERTIFICATION", object_id="artifact_abc", detail="Passed all 3 gates")
entries = audit.read_all()
print(f"EncryptedAuditTrail: {len(entries)} entry/entries, integrity verified")
```

### 5.3 Service host — heartbeat check

```bash
# Verify the service host is alive and produces a clean heartbeat
python -m sb_712.service_host --heartbeat-once
```

Expected output (JSON):
```json
{
  "heartbeat": {
    "score": 100.0,
    "level": "HEALTHY",
    "node_readiness": 1.0,
    "recovery_readiness": 1.0,
    "trust_ratio": 1.0
  }
}
```

---

## 6. SB688 — Node.js Runtime

**Files:** `SB688_systemIntegrity.js`, `SB688_index.js`  
**No npm install required** — pure Node.js, zero external dependencies.

### 6.1 How the state machine works

```
  STABLE (integrity = 1.0)
       │
       ▼  triggerInfrastructureKill()
  HEALING (integrity = 0.01)
       │
       ▼  checkEngineStatus()   ← autonomous local recovery
  STABLE (integrity = 1.0)      ← Golden Integrity restored
```

All mutations pass through `withStateLock` — a serial promise queue that
guarantees no two state writes interleave, even under concurrent call bursts.

### 6.2 Core replication

```js
const {
  getSystemIntegrity,
  triggerInfrastructureKill,
  checkEngineStatus,
} = require('./SB688_systemIntegrity');

async function demo() {
  // 1. Nominal state
  console.log('integrity:', await getSystemIntegrity());  // 1

  // 2. Simulate catastrophic infrastructure failure
  await triggerInfrastructureKill();
  console.log('integrity after kill:', await getSystemIntegrity());  // 0.01
  console.log('status:', await checkEngineStatus());  // 'HEALING' (snapshot before reset)

  // 3. Verify autonomous recovery
  console.log('integrity after check:', await getSystemIntegrity());  // 1  (STABLE)

  // 4. Concurrent kill storm — all queue serially, one check drains them all
  await Promise.all([
    triggerInfrastructureKill(),
    triggerInfrastructureKill(),
    triggerInfrastructureKill(),
  ]);
  await checkEngineStatus();
  console.log('integrity after storm:', await getSystemIntegrity());  // 1
}

demo();
```

### 6.3 Using via the index entry point

```js
// SB688_index.js re-exports systemIntegrity for npm-style module resolution
const sb688 = require('./SB688_index');
// sb688.getSystemIntegrity, sb688.triggerInfrastructureKill, sb688.checkEngineStatus
```

---

## 7. SB688 Chaos Stress Suite

**File:** `SB688_chaos_stress_suite.js`  
**Purpose:** Industrial-grade proof of 100 % autonomous recovery across 10,000 iterations.

### 7.1 Run it

```bash
node SB688_chaos_stress_suite.js
```

### 7.2 Exit codes

| Code | Meaning |
|---|---|
| `0` | 100 % recovery — 0 % drift — all assertions passed |
| `1` | One or more iterations drifted from Golden Integrity |
| `2` | Unhandled rejection / fatal error in the test harness |

### 7.3 What it proves

| Scenario | Injection | Assertion |
|---|---|---|
| `AEROSPACE_PACKET_LOSS` | Kill + 0–50 ms blackout before recovery | `integrity === 1.0` after autonomous local recovery |
| `BIT_FLIP_CORRUPTION` | Kill + 2–8 concurrent queued kills | One `checkEngineStatus` drains full burst; no drift |
| `HIGH_FREQ_KILLS` | 5–20 `Promise.all` kills | Queue does not deadlock or freeze; recovery succeeds |
| `ZERO_DRIFT_BASELINE` | Single kill → single check | Nominal contract holds on every 4th iteration |

### 7.4 Expected terminal output

```
  ████████████████████████████████████████████████████████████
  ██   ♛  SB688  CHAOS  STRESS  SUITE  ·  v1.0  ♛         ██
  ██   Aerospace · Defense · Deep-Sea · 10,000 iterations  ██
  ████████████████████████████████████████████████████████████

  [████████████████████████████████] 10000/10000 | ZERO_DRIFT_BASELINE
  | ✓ 10000 Healed | ✗   0 Failures | Recovery: 100.00% | Drift: 0.0000%

  ♛  FINAL REPORT
  Total Iterations     : 10,000
  Autonomous Heals     : 10,000
  Failures / Drift     : 0
  Recovery Rate        : 100.0000%
  System Drift         : 0.0000%

  ✅  TARGET MET — 100.0000% recovery · 0.0000% system drift.
      Golden Directive integrity confirmed across all scenarios.
```

---

## 8. SB-712 Windows Service

**File:** `scripts/install-sb712-service.ps1`  
**Platform:** Windows 10 / 11 only. Run PowerShell as Administrator.

### 8.1 Install

```powershell
# From an Administrator PowerShell prompt:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\install-sb712-service.ps1
```

What it does:
1. Copies the entire repo into `C:\Program Files\SB712\system\`
2. Runs `pip install` in that directory
3. Creates a Windows service named `SB712SecurityHost` pointing to `python -m sb_712.service_host`
4. Sets startup type to **Automatic** and starts the service immediately

### 8.2 Override parameters

```powershell
.\scripts\install-sb712-service.ps1 `
  -ServiceName   "SB712SecurityHost" `
  -InstallRoot   "C:\SB712\system" `
  -PythonExe     "C:\Python312\python.exe" `
  -EnvFile       "C:\SB712\system\.env"
```

### 8.3 Verify the service is running

```powershell
Get-Service -Name SB712SecurityHost
```

```bash
# Or from a Python prompt inside the install dir:
python -m sb_712.service_host --heartbeat-once
```

---

## 9. Running All Tests

### 9.1 Full Python test suite (155 tests)

```bash
# Install dev dependencies first (if not already done)
pip install -e ".[dev]"

# Run everything
pytest tests/ -q
```

Expected output:
```
155 passed in XX.XXs
```

### 9.2 Targeted suites

```bash
# Self-healing verification
pytest tests/test_self_healing.py -v

# Triple Verification Gate (Rule of Three)
pytest tests/test_rule_of_three.py -v

# Chaos — crash injection, split-brain, memory pressure
pytest tests/test_chaos.py -v

# Concurrent readers/writers
pytest tests/test_concurrency.py -v

# Space environments — cosmic radiation, Mars latency, solar flares
pytest tests/test_space_environments.py -v

# Industry verticals
pytest tests/test_industry_finance.py tests/test_industry_healthcare.py \
       tests/test_industry_aviation.py tests/test_industry_military.py -v

# Recovery engine
pytest tests/test_recovery.py -v

# Security layer — JWT, rate limiting, encrypted audit
pytest tests/test_security.py -v
```

### 9.3 Node.js chaos suite

```bash
node SB688_chaos_stress_suite.js
# Exit 0 = all clear
```

---

## 10. Key Concepts Quick Reference

| Concept | Definition | Where implemented |
|---|---|---|
| **Golden Integrity / Golden Directive** | The last fully verified, certified, Spine-anchored system state. All recovery targets this. | `SB688_systemIntegrity.js` (`GOLDEN_INTEGRITY=1.0`), `sb_712/checkpoint.py` |
| **Triple Verification Gate** | Three mandatory planes — Structural · Contextual · Intent — before any artifact is trusted | `sb_712/system.py` (`TrustGatePipeline`, `VerificationEvidence`) |
| **Rule of Three** | One report = intelligence. Two = confidence. Three independent confirmations = trusted state. | `sb_712/system.py`, `docs/SB712_RULE_OF_THREE.md` |
| **The Spine** | Protected truth backbone. Only certified, triple-verified state may enter it. | Conceptual — enforced by `TrustGatePipeline` |
| **Proof Ledger** | Append-only, SHA-256 chained, tamper-evident audit log. Every state transition is recorded. | `sb_712/system.py` (`ProofLedger`) |
| **Cubic Brick Isolation** | Quarantine container for untrusted/corrupted artifacts. Cannot touch Spine or active memory. | `sb_712/system.py` (`QuarantineRecord`, `QuarantineState`) |
| **Recovery Convoy** | Ordered sequence: Hunt → Contain → Repair → Verify → Certify → Return-Check Loop | `sb_712/recovery.py` (`RecoveryOrchestrator`) |
| **Phoenix Nodes** | Four-node high-availability recovery layer. Rotate dormant/active on 3-hour cycles. Wake on 99.8/99.9 heartbeat thresholds. | `sb_712/recovery.py` (`PhoenixDecision`), `docs/SB712_COMMAND_HIERARCHY.md` |
| **Heartbeat Score** | Composite 0–100 system integrity signal. 100 = HEALTHY. 99.8 = SELF_HEALING. 99.9 = PHOENIX_ALERT. | `sb_712/system.py` (`HeartbeatMonitor`, `HeartbeatLevel`) |
| **`withStateLock`** | Serial promise queue in the Node.js runtime. Guarantees no two state mutations interleave. | `SB688_systemIntegrity.js` |
| **WAL Three-Phase Commit** | Prepare → Commit → Apply. If interrupted at any point, replay restores clean state. | `src/sb688/wal.py` (`WriteAheadLog`) |
| **ECC / RAID-5 Parity** | XOR-parity erasure coding. Recovers any 1-of-N shards from parity alone. | `src/sb688/ecc.py` (`ECCEncoder`) |

---

```
  ████████████████████████████████████████████████████████████████████
  ██                                                                ██
  ██    ♛  REPLICATION GUIDE  ·  SB-712 + SB688  ·  v1.0  ♛      ██
  ██        VERIFY FIRST  ·  PROTECT THE SPINE  ·  LOG ALL        ██
  ██                                                                ██
  ████████████████████████████████████████████████████████████████████
```
