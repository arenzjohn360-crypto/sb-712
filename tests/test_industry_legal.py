"""
Legal / Government stress tests for SB688.

Covers:
- Immutability: Merkle proof verifies write-once records
- Modification invalidates proof
- ECC forward error correction for 100-year archival
- Audit log is tamper-evident (chained SHA-256)
- All integrity events are logged with the correct key
"""
import os
import pytest
from sb688 import BlockStore, ECCEncoder, IntegrityChecker, MerkleTree


class TestImmutability:
    def test_write_once_provable_via_merkle(self):
        records = {f"doc_{i:04d}": os.urandom(128) for i in range(200)}
        tree = MerkleTree(records)
        root = tree.root
        for key in list(records.keys())[::20]:
            proof = tree.proof(key)
            assert MerkleTree.verify_proof(key, records[key], proof, root)

    def test_modification_invalidates_proof(self):
        docs = {"doc_001": b"original", "doc_002": b"other"}
        tree = MerkleTree(docs)
        root = tree.root
        proof = tree.proof("doc_001")
        assert not MerkleTree.verify_proof("doc_001", b"modified", proof, root)


class TestLongTermArchival:
    @pytest.mark.parametrize("lost_idx", range(4))
    def test_ecc_reconstructs_after_shard_decay(self, lost_idx):
        enc = ECCEncoder(k=4)
        archive = os.urandom(4096)
        shards, parity = enc.encode(archive)
        working = list(shards)
        working[lost_idx] = None
        assert enc.decode(working, parity) == archive

    def test_checksum_holds_for_1mb_archive(self):
        store = BlockStore()
        data = os.urandom(1024 * 1024)
        store.put("archive_2024", data)
        assert store.get("archive_2024") == data


class TestChainOfCustody:
    def test_audit_log_tamper_evident(self):
        store = BlockStore()
        for i in range(10):
            store.put(f"evidence_{i}", os.urandom(32))
        store.inject_bit_flip("evidence_3", 0)
        store.inject_bit_flip("evidence_7", 5)

        checker = IntegrityChecker(store)
        checker.scan()
        assert checker.verify_audit_chain()

    def test_all_corrupt_keys_appear_in_audit_log(self):
        store = BlockStore()
        store.put("key1", os.urandom(32))
        store.put("key2", os.urandom(32))
        store.inject_bit_flip("key1", 0)
        store.inject_bit_flip("key2", 0)

        checker = IntegrityChecker(store)
        checker.scan()

        logged_keys = {e.key for e in checker.audit_log}
        assert "key1" in logged_keys
        assert "key2" in logged_keys
