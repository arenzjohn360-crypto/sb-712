"""
Healthcare industry stress tests for SB688.

Covers:
- HIPAA: data encrypted at rest; plaintext never stored raw
- Corrupt ciphertext raises error — never silently decrypts wrong data
- Concurrent patient record updates: no version collision, no corruption
- Emergency access during network partition: local replica readable
- Partition below quorum: write rejected
"""
import os
import threading
import pytest
from sb688 import (
    BlockStore,
    CorruptionError,
    EncryptedStore,
    EncryptionError,
    PartitionError,
    ReplicaSet,
)


class TestHIPAAEncryption:
    def test_plaintext_never_stored_raw(self):
        inner = BlockStore()
        enc = EncryptedStore(inner)
        plaintext = b"PatientID:12345;Diagnosis:Confidential"
        enc.put("patient_001", plaintext)
        raw_blob = inner.get("patient_001")
        assert plaintext not in raw_blob

    def test_corrupted_ciphertext_raises_not_silent(self):
        inner = BlockStore()
        enc = EncryptedStore(inner)
        enc.put("record", b"sensitive_data")
        enc.inject_corruption("record")
        with pytest.raises((EncryptionError, CorruptionError)):
            enc.get("record")

    def test_decrypted_value_matches_original(self):
        enc = EncryptedStore(BlockStore())
        data = b"PHI:BloodType=O+;Allergies=Penicillin"
        enc.put("pat_rec", data)
        assert enc.get("pat_rec") == data


class TestPatientRecordVersioning:
    def test_concurrent_updates_no_corruption(self):
        """1 000 records updated concurrently; no checksum failures."""
        store = BlockStore()
        n = 1_000
        for i in range(n):
            store.put(f"patient_{i}", f"v0_data_{i}".encode())

        errors = []

        def updater(thread_id: int):
            for i in range(thread_id, n, 4):
                try:
                    store.put(f"patient_{i}", f"v1_t{thread_id}".encode())
                except Exception as exc:
                    errors.append(str(exc))

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert store.corrupt_keys() == []

    def test_version_advances_on_overwrite(self):
        store = BlockStore()
        store.put("patient_001", b"initial")
        v0 = store.get_version("patient_001")
        store.put("patient_001", b"updated")
        v1 = store.get_version("patient_001")
        assert v1 > v0


class TestEmergencyAccessPartition:
    def test_local_replica_readable_during_partition(self):
        replicas = ReplicaSet(n=3, quorum=2)
        patient_data = {f"pat_{i}": os.urandom(64) for i in range(50)}
        for k, v in patient_data.items():
            replicas.put(k, v)

        replicas.partition([2])
        for k, v in patient_data.items():
            assert replicas.get(k) == v

    def test_partition_below_quorum_rejects_write(self):
        replicas = ReplicaSet(n=3, quorum=2)
        replicas.put("initial", b"data")
        replicas.partition([0, 1])
        with pytest.raises(PartitionError):
            replicas.put("new_key", b"data")
