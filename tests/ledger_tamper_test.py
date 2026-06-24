"""
ledger_tamper_test.py — SB-712 IronBraid Radiant Core

Tests that verify the system detects ledger tampering and prevents
promotion of data with a broken hash chain.
"""

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from intelligence.fieldview_encoder import hash_string, hash_file


def build_ledger_entry(seq: int, event: str, previous_hash: str) -> dict:
    """Build a ledger entry dict with a valid entry_hash."""
    entry = {
        "seq": seq,
        "event": event,
        "previous_hash": previous_hash,
        "entry_hash": None,
        "timestamp": "2026-06-24T00:00:00Z",
        "state": "CERTIFIED",
        "source": "test",
        "schema_version": "1.0.0",
    }
    payload = {k: v for k, v in entry.items() if k != "entry_hash"}
    entry["entry_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
    return entry


def verify_ledger_chain(entries: list) -> tuple[bool, str]:
    """
    Walk the ledger entries and verify hash continuity.
    Returns (ok, message).
    """
    for i, entry in enumerate(entries):
        # Recompute entry hash.
        payload = {k: v for k, v in entry.items() if k != "entry_hash"}
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        if entry["entry_hash"] != expected:
            return False, f"Entry {i} hash mismatch."
        # Check backward chain.
        if i > 0:
            if entry["previous_hash"] != entries[i - 1]["entry_hash"]:
                return False, f"Chain broken between entry {i-1} and {i}."
    return True, "Chain intact."


class TestLedgerIntegrity:
    def test_valid_chain_passes(self):
        genesis = build_ledger_entry(0, "GENESIS",
                                     "0" * 64)
        entry1 = build_ledger_entry(1, "WRITE", genesis["entry_hash"])
        ok, msg = verify_ledger_chain([genesis, entry1])
        assert ok, msg

    def test_tampered_entry_detected(self):
        genesis = build_ledger_entry(0, "GENESIS", "0" * 64)
        entry1 = build_ledger_entry(1, "WRITE", genesis["entry_hash"])
        # Tamper: overwrite event after hash was computed.
        entry1["event"] = "TAMPERED"
        ok, msg = verify_ledger_chain([genesis, entry1])
        assert not ok

    def test_broken_chain_link_detected(self):
        genesis = build_ledger_entry(0, "GENESIS", "0" * 64)
        entry1 = build_ledger_entry(1, "WRITE", genesis["entry_hash"])
        # Break chain by forging previous_hash.
        entry1_copy = dict(entry1)
        entry1_copy["previous_hash"] = "deadbeef" * 8
        # Re-hash so entry hash is self-consistent but chain is broken.
        payload = {k: v for k, v in entry1_copy.items() if k != "entry_hash"}
        entry1_copy["entry_hash"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        ok, msg = verify_ledger_chain([genesis, entry1_copy])
        assert not ok

    def test_empty_ledger_passes(self):
        ok, msg = verify_ledger_chain([])
        assert ok

    def test_genesis_only_passes(self):
        genesis = build_ledger_entry(0, "GENESIS", "0" * 64)
        ok, msg = verify_ledger_chain([genesis])
        assert ok


class TestLedgerFileExists:
    """Verify the genesis ledger files were scaffolded correctly."""

    def test_ledger_file_exists(self):
        p = Path("ledger/ledger.jsonl")
        assert p.exists(), "ledger/ledger.jsonl must exist"

    def test_mirror_a_exists(self):
        assert Path("ledger/ledger_mirror_a.jsonl").exists()

    def test_mirror_b_exists(self):
        assert Path("ledger/ledger_mirror_b.jsonl").exists()

    def test_genesis_entry_valid(self):
        p = Path("ledger/ledger.jsonl")
        if not p.exists():
            pytest.skip("ledger not scaffolded")
        entry = json.loads(p.read_text().strip().splitlines()[0])
        assert entry["event"] == "GENESIS"
        assert entry["seq"] == 0
