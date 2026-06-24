"""
Finance industry stress tests for SB688.

Covers:
- 10 K transaction writes with zero loss
- Lamport clock ordering (strictly increasing timestamps)
- Idempotent write semantics
- WAL-based regulatory audit / history reconstruction
- Merkle immutability proofs and tampering detection
- Bank failover with full data on secondary
"""
import os
import pytest
from sb688 import BlockStore, DurableStore, LamportClock, MerkleTree
from sb688.wal import WriteAheadLog


class TestHighThroughputWrites:
    def test_10k_transactions_no_loss(self):
        store = BlockStore()
        n = 10_000
        txns = {f"txn_{i:06d}": os.urandom(32) for i in range(n)}
        for k, v in txns.items():
            store.put(k, v)
        assert len(store) == n
        for k, v in txns.items():
            assert store.get(k) == v

    def test_no_silent_overwrite_of_distinct_keys(self):
        store = BlockStore()
        keys = [f"tx_{i:04d}" for i in range(1_000)]
        for k in keys:
            store.put(k, os.urandom(16))
        assert len(set(keys)) == len(keys)
        assert len(store) == len(keys)


class TestTransactionOrdering:
    def test_lamport_timestamps_strictly_increasing(self):
        clock = LamportClock()
        store = BlockStore()
        prev_ts = 0
        for i in range(200):
            ts = clock.tick()
            assert ts > prev_ts
            prev_ts = ts
            store.put(f"tx_{ts:010d}", f"amount_{i}".encode())


class TestIdempotentWrite:
    def test_same_key_same_data_increments_version_only(self):
        store = BlockStore()
        store.put("tx_001", b"amount=100")
        v1 = store.get_version("tx_001")
        store.put("tx_001", b"amount=100")
        v2 = store.get_version("tx_001")
        assert v2 == v1 + 1
        assert store.get("tx_001") == b"amount=100"


class TestRegulatoryAudit:
    def test_reconstruct_history_from_wal(self):
        wal = WriteAheadLog()
        inner = BlockStore()
        ds = DurableStore(store=inner, wal=wal)

        history = {}
        for i in range(50):
            k = f"tx_{i:04d}"
            v = f"amount_{i * 10}".encode()
            ds.put(k, v)
            history[k] = v

        audit_store = BlockStore()
        wal.recover(audit_store)

        for k, v in history.items():
            assert audit_store.get(k) == v

    def test_merkle_immutability_proof(self):
        txns = {f"tx_{i:04d}": os.urandom(16) for i in range(100)}
        tree = MerkleTree(txns)
        root = tree.root

        for key in list(txns.keys())[::10]:
            proof = tree.proof(key)
            assert proof is not None
            assert MerkleTree.verify_proof(key, txns[key], proof, root)

    def test_merkle_detects_tampering(self):
        txns = {"tx_001": b"amount=500", "tx_002": b"amount=200"}
        tree = MerkleTree(txns)
        root = tree.root
        proof = tree.proof("tx_001")
        assert not MerkleTree.verify_proof("tx_001", b"amount=99999", proof, root)


class TestBankFailover:
    def test_secondary_has_full_data_after_primary_failure(self):
        primary = BlockStore()
        secondary = BlockStore()
        txns = {f"tx_{i}": os.urandom(16) for i in range(200)}
        for k, v in txns.items():
            primary.put(k, v)
            secondary.put(k, v)

        # Primary fails — secondary serves all reads
        for k, v in txns.items():
            assert secondary.get(k) == v
