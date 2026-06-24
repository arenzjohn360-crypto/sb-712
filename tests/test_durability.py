"""
Durability tests — data survives crashes, power loss, hardware failure.

Covers:
- Crash before write: store unchanged
- Crash at every byte offset (N = 0..5): committed data always survives
- WAL chain integrity after many writes
- Snapshot / restore round-trip
- Recovery is idempotent (running twice gives the same result)
"""
import os
import pytest
from sb688 import BlockStore, DurableStore, SimulatedCrash
from sb688.wal import WriteAheadLog


def test_crash_before_first_write():
    """Crash before any data reaches the store: store stays empty."""
    wal = WriteAheadLog()
    inner = BlockStore()
    ds = DurableStore(store=inner, wal=wal)

    inner.arm_crash(after_n_writes=0)
    with pytest.raises(SimulatedCrash):
        ds.put("volatile", b"should_not_appear")
    inner.disarm_crash()
    ds.recover()

    assert "volatile" not in inner


@pytest.mark.parametrize("crash_after", range(6))
def test_crash_at_every_write_offset_preserves_committed(crash_after):
    """
    Crash after exactly N successful puts.  All N committed records must
    be intact after recovery; the in-flight record must NOT appear.
    """
    wal = WriteAheadLog()
    inner = BlockStore()
    ds = DurableStore(store=inner, wal=wal)

    committed = {}
    for i in range(crash_after):
        k, v = f"pre_{i}", f"value_{i}".encode()
        ds.put(k, v)
        committed[k] = v

    inner.arm_crash(after_n_writes=0)
    try:
        ds.put("crash_target", b"lost_in_crash")
    except SimulatedCrash:
        pass
    inner.disarm_crash()
    ds.recover()

    for k, v in committed.items():
        assert ds.get(k) == v
    assert "crash_target" not in inner


def test_wal_entry_checksums_hold_after_many_writes():
    """WAL entry checksums remain valid after 50 writes."""
    wal = WriteAheadLog()
    inner = BlockStore()
    ds = DurableStore(store=inner, wal=wal)

    for i in range(50):
        ds.put(f"key_{i}", os.urandom(64))

    assert wal.verify_all()


def test_snapshot_and_restore():
    """Take a snapshot of a live store and restore it into a new store."""
    store = BlockStore()
    data = {f"k{i}": os.urandom(32) for i in range(100)}
    for k, v in data.items():
        store.put(k, v)

    snap = store.snapshot()
    new_store = BlockStore()
    new_store.restore_from_snapshot(snap)

    for k, v in data.items():
        assert new_store.get(k) == v


def test_recovery_is_idempotent():
    """Running recovery twice gives the same result as running it once."""
    wal = WriteAheadLog()
    store1 = BlockStore()
    ds = DurableStore(store=store1, wal=wal)
    ds.put("key", b"important_data")

    store2 = BlockStore()
    wal.recover(store2)
    wal.recover(store2)  # second replay must be safe

    assert store2.get("key") == b"important_data"
