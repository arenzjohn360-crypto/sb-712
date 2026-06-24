"""
Consistency tests — no partial writes, no torn reads.

Covers:
- Atomic put: either fully succeeds or store is unchanged
- Crash leaves previous committed value intact
- WAL uncommitted entries are NOT replayed
- Concurrent writers never produce torn reads on the reader side
"""
import os
import threading
import time
import pytest
from sb688 import BlockStore, CorruptionError, DurableStore, SimulatedCrash
from sb688.wal import WriteAheadLog, WALOp


def test_atomic_put_fully_applied():
    """A put either fully succeeds or fails; no partial state is ever visible."""
    ds = DurableStore()
    data = os.urandom(4096)
    ds.put("key", data)
    assert ds.get("key") == data


def test_crash_leaves_previous_value_intact():
    """
    After a crash mid-write the previous committed value is still readable.
    The WAL ensures the last committed state is recovered on restart.
    """
    wal = WriteAheadLog()
    inner = BlockStore()
    ds = DurableStore(store=inner, wal=wal)

    ds.put("key", b"initial_value")

    # Crash the store on the very next put
    inner.arm_crash(after_n_writes=0)
    with pytest.raises(SimulatedCrash):
        ds.put("key", b"should_not_persist")

    inner.disarm_crash()
    ds.recover()

    assert ds.get("key") == b"initial_value"


def test_uncommitted_wal_entry_not_replayed():
    """WAL entries without a COMMIT are silently skipped during recovery."""
    wal = WriteAheadLog()
    wal.log_put("partial_key", b"partial_data")
    # Intentionally no wal.commit() — simulates crash between log and commit

    fresh_store = BlockStore()
    replayed = wal.recover(fresh_store)

    assert "partial_key" not in fresh_store
    assert replayed == 0


def test_committed_entry_is_replayed():
    """A fully committed WAL entry is replayed into a fresh store on recovery."""
    wal = WriteAheadLog()
    wal.log_put("key", b"committed_data")
    wal.commit("key")

    fresh_store = BlockStore()
    replayed = wal.recover(fresh_store)

    assert replayed >= 1
    assert fresh_store.get("key") == b"committed_data"


def test_no_torn_read_under_concurrent_writes():
    """
    While writers continuously overwrite a key, readers must never observe
    a checksum-failing partial write.
    """
    store = BlockStore()
    store.put("shared", os.urandom(256))
    errors = []
    stop = threading.Event()

    def writer():
        while not stop.is_set():
            store.put("shared", os.urandom(256))

    def reader():
        while not stop.is_set():
            try:
                store.get("shared")
            except CorruptionError as exc:
                errors.append(str(exc))

    threads = [threading.Thread(target=writer, daemon=True)] + [
        threading.Thread(target=reader, daemon=True) for _ in range(4)
    ]
    for t in threads:
        t.start()
    time.sleep(0.5)
    stop.set()
    for t in threads:
        t.join(timeout=2)

    assert errors == [], f"Torn read detected: {errors}"


def test_read_sees_committed_write_immediately():
    store = BlockStore()
    store.put("k", b"value")
    assert store.get("k") == b"value"
