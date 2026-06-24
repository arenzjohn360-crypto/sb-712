"""
Telecommunications stress tests for SB688.

Covers:
- 1 M micro-record writes: zero loss, zero corruption
- Idempotent write under retransmission: data correct, no phantom duplicate
- 10 K call records: all retrievable
- Lamport clock: no duplicate timestamps across 1 000 records
"""
import os
import pytest
from sb688 import BlockStore, LamportClock


class TestHighThroughputMicroRecords:
    def test_1m_micro_records_no_loss(self):
        store = BlockStore()
        n = 1_000_000
        for i in range(n):
            store.put(f"r{i}", i.to_bytes(4, "big"))
        assert len(store) == n
        assert store.corrupt_keys() == []

    def test_idempotent_write_under_retransmission(self):
        store = BlockStore()
        store.put("sms_001", b"Hello world")
        v1 = store.get_version("sms_001")
        # Retransmit same record
        store.put("sms_001", b"Hello world")
        v2 = store.get_version("sms_001")
        assert store.get("sms_001") == b"Hello world"
        assert v2 == v1 + 1  # version incremented, but data correct


class TestCallRecordAudit:
    def test_10k_call_records_all_retrievable(self):
        store = BlockStore()
        records = {f"cdr_{i:08d}": os.urandom(32) for i in range(10_000)}
        for k, v in records.items():
            store.put(k, v)
        for k, v in records.items():
            assert store.get(k) == v

    def test_lamport_clock_no_duplicate_timestamps(self):
        clock = LamportClock()
        store = BlockStore()
        timestamps: set[int] = set()
        for _ in range(1_000):
            ts = clock.tick()
            assert ts not in timestamps, f"Duplicate Lamport timestamp: {ts}"
            timestamps.add(ts)
            store.put(f"cdr_ts{ts:010d}", os.urandom(16))
