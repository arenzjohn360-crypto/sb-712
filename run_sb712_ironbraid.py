#!/usr/bin/env python3
"""
run_sb712_ironbraid.py — SB-712 IronBraid Radiant Core

Cross-platform entrypoint that:
  1. Ensures all required folders and key files exist.
  2. Runs a basic integrity scan pass across the spine/ and ledger/ directories.
  3. Appends a proof-report JSON artifact to reports/daily/proof/.

Usage:
    python run_sb712_ironbraid.py

No external dependencies required beyond the standard library.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ── Configuration ─────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent

REQUIRED_DIRS = [
    "spine",
    "data/intake",
    "data/quarantine",
    "data/active_brics",
    "data/offline_brics",
    "data/cold_storage",
    "data/replicas",
    "ledger",
    "checkpoints/ghost",
    "checkpoints/phoenix_a",
    "checkpoints/phoenix_b",
    "checkpoints/phoenix_c",
    "intelligence",
    "recovery",
    "tests",
    "reports/daily/proof",
    "ui",
]

SCAN_PATHS = ["spine", "ledger"]


# ── Utilities ──────────────────────────────────────────────────────────────

def _hash_file(path: Path) -> str | None:
    """Return sha256 hex digest of *path*, or None on read error."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Step 1: Ensure folders exist ───────────────────────────────────────────

def ensure_structure() -> list[str]:
    """Create any missing required directories. Returns list of created paths."""
    created = []
    for rel in REQUIRED_DIRS:
        d = REPO_ROOT / rel
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(rel)
            print(f"  [CREATED] {rel}/")
        else:
            print(f"  [OK]      {rel}/")
    return created


# ── Step 2: Integrity scan ─────────────────────────────────────────────────

def run_integrity_scan() -> dict:
    """
    Hash every file under SCAN_PATHS and report mutations / read errors.

    Returns a summary dict suitable for inclusion in the proof report.
    """
    results = {
        "files_scanned": 0,
        "mutations_detected": 0,
        "read_errors": 0,
        "hash_map": {},
        "fault_events": [],
    }

    baseline_path = REPO_ROOT / "reports/daily/proof/.baseline.json"
    baseline: dict[str, str] = {}

    if baseline_path.exists():
        try:
            baseline = json.loads(baseline_path.read_text())
        except (json.JSONDecodeError, OSError):
            baseline = {}

    for scan_rel in SCAN_PATHS:
        scan_dir = REPO_ROOT / scan_rel
        if not scan_dir.exists():
            continue
        for root, _dirs, files in os.walk(scan_dir):
            for name in files:
                fpath = Path(root) / name
                rel_key = str(fpath.relative_to(REPO_ROOT))
                digest = _hash_file(fpath)
                if digest is None:
                    results["read_errors"] += 1
                    results["fault_events"].append(f"READ_ERROR:{rel_key}")
                else:
                    results["hash_map"][rel_key] = digest
                    results["files_scanned"] += 1
                    if rel_key in baseline and baseline[rel_key] != digest:
                        results["mutations_detected"] += 1
                        results["fault_events"].append(f"MUTATION:{rel_key}")

    # Persist new baseline.
    try:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(results["hash_map"], indent=2))
    except OSError as exc:
        print(f"  [WARN] Could not write baseline: {exc}")

    return results


# ── Step 3: Write proof report ─────────────────────────────────────────────

def write_proof_report(scan_results: dict) -> Path:
    """
    Compose and append a proof-report JSON artifact to reports/daily/proof/.

    Returns the path of the written file.
    """
    run_id = str(uuid.uuid4())[:8]
    ts = _utc_now()
    date_str = ts[:10]  # YYYY-MM-DD

    mutations = scan_results["mutations_detected"]
    errors = scan_results["read_errors"]

    if mutations == 0 and errors == 0:
        risk_level = "LOW"
        status = "PROOF_COMPLETE"
    elif mutations <= 2 and errors == 0:
        risk_level = "MEDIUM"
        status = "PROOF_COMPLETE_WITH_WARNINGS"
    else:
        risk_level = "HIGH"
        status = "PROOF_FAILED_REVIEW_REQUIRED"

    report = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "timestamp": ts,
        "files_scanned": scan_results["files_scanned"],
        "mutations_detected": mutations,
        "read_errors": errors,
        "risk_level": risk_level,
        "status": status,
        "fault_events": scan_results["fault_events"],
        "system": "SB-712 IronBraid Radiant Core",
    }

    proof_dir = REPO_ROOT / "reports/daily/proof"
    proof_dir.mkdir(parents=True, exist_ok=True)
    report_path = proof_dir / f"proof_{date_str}_{run_id}.json"
    report_path.write_text(json.dumps(report, indent=2))
    return report_path


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 60)
    print("  SB-712 IronBraid Radiant Core — Integrity Scan")
    print(f"  {_utc_now()}")
    print("=" * 60)

    print("\n[1/3] Ensuring directory structure …")
    ensure_structure()

    print("\n[2/3] Running integrity scan …")
    scan = run_integrity_scan()
    print(f"  Files scanned : {scan['files_scanned']}")
    print(f"  Mutations     : {scan['mutations_detected']}")
    print(f"  Read errors   : {scan['read_errors']}")
    if scan["fault_events"]:
        for ev in scan["fault_events"]:
            print(f"  ⚠  {ev}")

    print("\n[3/3] Writing proof report …")
    report_path = write_proof_report(scan)
    print(f"  Report written: {report_path.relative_to(REPO_ROOT)}")

    print("\n" + "=" * 60)
    print("  Scan complete.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
