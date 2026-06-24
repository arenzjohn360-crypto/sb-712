"""
Self-healing verification tests for SB688.

After every fault, the system must:
1. Detect corruption within a defined SLA
2. Repair without introducing new corruption
3. Repair is idempotent (running twice gives the same result)
4. Audit trail is tamper-evident throughout
"""
import os
import pytest
from sb688 import BlockStore, IntegrityChecker, ReplicaSet, ECCEncoder


class TestCorruptionDetectionSLA:
    def test_single_bit_flip_detected_on_next_scan(self):
        store = BlockStore()
        store.put("k", os.urandom(64))
        store.inject_bit_flip("k", 0)
        assert "k" in store.corrupt_keys()

    def test_bulk_corruption_fully_detected_before_heal(self):
        store = BlockStore()
        n = 100
        for i in range(n):
            store.put(f"k{i}", os.urandom(32))
        for i in range(0, n, 5):
            store.inject_bit_flip(f"k{i}", 0)

        corrupted = set(store.corrupt_keys())
        expected = {f"k{i}" for i in range(0, n, 5)}
        assert corrupted == expected


class TestRepairIntroducesNoNewCorruption:
    def test_healed_blocks_pass_integrity_check(self):
        primary = BlockStore()
        backup = BlockStore()
        data = {f"k{i}": os.urandom(64) for i in range(50)}

        for k, v in data.items():
            primary.put(k, v)
            backup.put(k, v)

        # Corrupt 20 % of primary
        for i in range(0, 50, 5):
            primary.inject_bit_flip(f"k{i}", 0)

        checker = IntegrityChecker(primary, repair_source=backup)
        checker.scan_and_heal()

        # After heal, no corrupt blocks remain
        assert primary.corrupt_keys() == []

    def test_repair_does_not_corrupt_healthy_neighbors(self):
        primary = BlockStore()
        backup = BlockStore()
        for i in range(10):
            v = os.urandom(32)
            primary.put(f"k{i}", v)
            backup.put(f"k{i}", v)

        # Corrupt only k5
        primary.inject_bit_flip("k5", 0)

        checker = IntegrityChecker(primary, repair_source=backup)
        checker.scan_and_heal()

        # All blocks must now be healthy
        assert primary.corrupt_keys() == []


class TestIdempotentRepair:
    def test_healing_twice_gives_same_result(self):
        primary = BlockStore()
        backup = BlockStore()
        v = os.urandom(64)
        primary.put("key", v)
        backup.put("key", v)
        primary.inject_bit_flip("key", 0)

        checker = IntegrityChecker(primary, repair_source=backup)
        checker.heal("key")
        data_after_first = primary.get("key")

        # Heal again (even though no corruption now)
        checker2 = IntegrityChecker(primary, repair_source=backup)
        checker2.heal("key")
        data_after_second = primary.get("key")

        assert data_after_first == data_after_second

    def test_is_idempotent_repair_check(self):
        primary = BlockStore()
        backup = BlockStore()
        v = os.urandom(64)
        primary.put("key", v)
        backup.put("key", v)

        checker = IntegrityChecker(primary, repair_source=backup)
        assert checker.is_idempotent_repair("key")

    def test_ecc_decode_idempotent(self):
        enc = ECCEncoder(k=4)
        data = os.urandom(256)
        shards, parity = enc.encode(data)
        shards_with_loss = list(shards)
        shards_with_loss[2] = None
        assert enc.decode(shards_with_loss, parity) == enc.decode(shards_with_loss, parity)


class TestAuditTrailTamperEvident:
    def test_audit_chain_valid_after_multiple_events(self):
        store = BlockStore()
        for i in range(20):
            store.put(f"k{i}", os.urandom(32))
        for i in range(0, 20, 4):
            store.inject_bit_flip(f"k{i}", 0)

        backup = BlockStore()
        for k in store.keys():
            try:
                backup.put(k, store.get(k))
            except Exception:
                pass

        checker = IntegrityChecker(store)
        checker.scan()
        assert checker.verify_audit_chain()

    def test_audit_chain_includes_repair_events(self):
        primary = BlockStore()
        backup = BlockStore()
        v = os.urandom(32)
        primary.put("k", v)
        backup.put("k", v)
        primary.inject_bit_flip("k", 0)

        checker = IntegrityChecker(primary, repair_source=backup)
        checker.scan_and_heal()

        event_types = {e.event_type for e in checker.audit_log}
        assert "corruption_detected" in event_types
        assert "repair_success" in event_types
        assert checker.verify_audit_chain()

    def test_replica_sync_self_heals_all_corrupt_blocks(self):
        replicas = ReplicaSet(n=3, quorum=2)
        data = {f"k{i}": os.urandom(32) for i in range(50)}
        for k, v in data.items():
            replicas.put(k, v)

        # Corrupt replica 0
        for i in range(0, 50, 5):
            replicas.corrupt_replica(0, f"k{i}", 0)

        # Sync heals corrupt replica 0 from replicas 1 and 2
        replicas.sync()

        for k, v in data.items():
            assert replicas.get_replica(0).get(k) == v
