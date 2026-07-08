"""
cosmic_burst_test.py — SB-712 IronBraid Radiant Core

Smoke tests simulating a cosmic-ray-style bit-flip burst across multiple
files.  The system must detect every mutation and quarantine affected data
without corrupting the Spine.
"""

import hashlib
import os
import tempfile
from pathlib import Path

import pytest

from intelligence.fieldview_encoder import FieldViewEncoder, hash_file, hash_string


class TestHashUtilities:
    def test_hash_string_returns_hex_digest(self):
        result = hash_string("hello")
        assert isinstance(result, str)
        assert len(result) == 64  # sha256 hex

    def test_hash_string_deterministic(self):
        assert hash_string("same") == hash_string("same")

    def test_hash_string_differs_on_different_input(self):
        assert hash_string("a") != hash_string("b")

    def test_hash_file_returns_hex_digest(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello world")
        result = hash_file(f)
        assert result is not None
        assert len(result) == 64

    def test_hash_file_returns_none_for_missing(self, tmp_path):
        result = hash_file(tmp_path / "nonexistent.txt")
        assert result is None


class TestCosmicBurstDetection:
    """Simulates burst mutations and verifies the FieldViewEncoder detects them."""

    def test_no_mutations_on_clean_scan(self, tmp_path):
        f = tmp_path / "clean.txt"
        f.write_bytes(b"original content")
        encoder = FieldViewEncoder(watch_paths=[tmp_path])
        snap1 = encoder.capture()
        snap2 = encoder.capture()
        assert snap2.mutation_count == 0

    def test_mutation_detected_after_file_change(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_bytes(b"original")
        encoder = FieldViewEncoder(watch_paths=[tmp_path])
        encoder.capture()  # baseline
        f.write_bytes(b"corrupted!")
        snap = encoder.capture()
        assert snap.mutation_count == 1

    def test_multiple_mutations_counted(self, tmp_path):
        files = [tmp_path / f"file{i}.dat" for i in range(5)]
        for f in files:
            f.write_bytes(b"original")
        encoder = FieldViewEncoder(watch_paths=[tmp_path])
        encoder.capture()  # baseline
        for f in files:
            f.write_bytes(b"flipped bit")
        snap = encoder.capture()
        assert snap.mutation_count == 5

    def test_mutation_events_logged(self, tmp_path):
        f = tmp_path / "target.bin"
        f.write_bytes(b"data")
        encoder = FieldViewEncoder(watch_paths=[tmp_path])
        encoder.capture()
        f.write_bytes(b"corrupted")
        snap = encoder.capture()
        assert any("MUTATION" in event for event in snap.fault_events)

    def test_read_error_counted_on_unreadable_file(self, tmp_path):
        f = tmp_path / "locked.bin"
        f.write_bytes(b"data")
        encoder = FieldViewEncoder(watch_paths=[tmp_path])
        # Remove read permission to simulate a hardware read error.
        os.chmod(f, 0o000)
        try:
            snap = encoder.capture()
            assert snap.disk_read_errors >= 1
        finally:
            os.chmod(f, 0o644)
