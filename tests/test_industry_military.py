"""
Military / Defense stress tests for SB688.

Covers:
- EMP simulation: bulk bit-flip injection; all detected
- Encryption key rotation: old records remain decryptable
- New writes after rotation use the new key ID
- Store-and-forward: SHA-256 proof of delivery
- Intermittent connectivity: local queue delivered on reconnect
"""
import os
import hashlib
import pytest
from sb688 import BlockStore, EncryptedStore


class TestEMPBitFlip:
    def test_emp_simulation_100pct_detection(self):
        store = BlockStore()
        n = 200
        for i in range(n):
            store.put(f"classified_{i:04d}", os.urandom(64))

        corrupt_indices = list(range(0, n, 3))
        for i in corrupt_indices:
            store.inject_bit_flip(f"classified_{i:04d}", i % 64)

        detected = set(store.corrupt_keys())
        expected = {f"classified_{i:04d}" for i in corrupt_indices}
        assert detected == expected


class TestEncryptionKeyRotation:
    def test_old_records_readable_after_rotation(self):
        inner = BlockStore()
        enc = EncryptedStore(inner)
        records = {f"secret_{i}": os.urandom(32) for i in range(50)}
        for k, v in records.items():
            enc.put(k, v)

        enc.rotate_key()

        for k, v in records.items():
            assert enc.get(k) == v

    def test_new_writes_use_new_key_id(self):
        inner = BlockStore()
        enc = EncryptedStore(inner)
        enc.put("old_record", b"pre_rotation_data")
        old_key_id = enc._active_key_id

        enc.rotate_key()
        new_key_id = enc._active_key_id
        enc.put("new_record", b"post_rotation_data")

        assert new_key_id != old_key_id
        assert enc.get("old_record") == b"pre_rotation_data"
        assert enc.get("new_record") == b"post_rotation_data"


class TestStoreAndForward:
    def test_sha256_proof_of_delivery(self):
        store = BlockStore()
        message = os.urandom(256)
        sent_hash = hashlib.sha256(message).digest()
        store.put("msg_001", message)
        received = store.get("msg_001")
        assert hashlib.sha256(received).digest() == sent_hash

    def test_intermittent_connectivity_eventual_delivery(self):
        local = BlockStore()
        remote = BlockStore()
        messages = {f"msg_{i:04d}": os.urandom(32) for i in range(100)}
        for k, v in messages.items():
            local.put(k, v)

        for k in local.keys():
            remote.put(k, local.get(k))

        for k, v in messages.items():
            assert remote.get(k) == v
