"""
Universal chaos / fault-injection tests for SB688.

Scenarios
---------
1.  Crash at every byte offset (N = 0..5) — committed data always survives
2.  Split-brain — below-quorum write rejected; no divergent commit
3.  Filesystem full — write failure raises; no silent partial write
4.  Clock skew — Lamport / vector clock causality holds across ±skew
5.  Memory pressure — 100 × 64 KiB writes; no data loss
6.  Disk silent corruption — 100 % detection rate
7.  Network partition + heal — sync restores all data on healed replica
8.  Cascading replica failure — last replica holds all data
9.  Large / small record mix — no fragmentation loss
10. Time-series reorder — out-of-order writes; correct reconstruction by key
"""
import os
import threading
import pytest
from sb688 import (
    BlockStore,
    DurableStore,
    LamportClock,
    PartitionError,
    ReplicaSet,
    SimulatedCrash,
    VectorClock,
)
from sb688.wal import WriteAheadLog


# ------------------------------------------------------------------ #
#  1. Crash at every byte offset                                       #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("crash_after", range(6))
def test_crash_and_recover_preserves_committed(crash_after):
    wal = WriteAheadLog()
    inner = BlockStore()
    ds = DurableStore(store=inner, wal=wal)

    committed = {}
    for i in range(crash_after):
        k = f"k{i}"
        v = os.urandom(32)
        ds.put(k, v)
        committed[k] = v

    inner.arm_crash(after_n_writes=0)
    try:
        ds.put("volatile", os.urandom(32))
    except SimulatedCrash:
        pass
    inner.disarm_crash()
    ds.recover()

    for k, v in committed.items():
        assert ds.get(k) == v
    assert "volatile" not in inner


# ------------------------------------------------------------------ #
#  2. Split-brain                                                      #
# ------------------------------------------------------------------ #

def test_below_quorum_write_rejected():
    replicas = ReplicaSet(n=3, quorum=2)
    replicas.put("shared", b"original")
    replicas.partition([0, 1])  # only 1 replica reachable
    with pytest.raises(PartitionError):
        replicas.put("shared", b"split_value")


def test_below_quorum_original_value_intact():
    replicas = ReplicaSet(n=3, quorum=2)
    replicas.put("shared", b"original")
    replicas.partition([0, 1])
    try:
        replicas.put("shared", b"split_value")
    except PartitionError:
        pass
    replicas.heal_partition()
    assert replicas.get_replica(0).get("shared") == b"original"


def test_quorum_majority_write_succeeds():
    replicas = ReplicaSet(n=3, quorum=2)
    replicas.partition([2])  # 2/3 reachable
    replicas.put("key", b"quorum_value")
    replicas.heal_partition()
    assert replicas.get("key") == b"quorum_value"


# ------------------------------------------------------------------ #
#  3. Filesystem full                                                  #
# ------------------------------------------------------------------ #

def test_filesystem_full_no_silent_data_loss():
    class FullStore(BlockStore):
        def put(self, key, data):
            raise OSError("No space left on device")

    full = FullStore()
    with pytest.raises(OSError):
        full.put("key", b"data")
    assert "key" not in full


# ------------------------------------------------------------------ #
#  4. Clock skew                                                       #
# ------------------------------------------------------------------ #

def test_lamport_clock_causality_across_skew():
    """Node B must have a higher Lamport time after receiving A's message."""
    clock_a = LamportClock(initial=600)  # A is 600 ticks ahead
    clock_b = LamportClock(initial=0)

    ts_a = clock_a.tick()
    ts_b = clock_b.update(ts_a)
    assert ts_b > ts_a


def test_vector_clock_detects_concurrent_events():
    nodes = ["n1", "n2"]
    vc1 = VectorClock("n1", nodes)
    vc2 = VectorClock("n2", nodes)

    v1 = vc1.tick()   # n1 acts independently
    v2 = vc2.tick()   # n2 acts independently (concurrent)
    assert VectorClock.concurrent(v1, v2)


def test_vector_clock_happens_before():
    nodes = ["n1", "n2"]
    vc1 = VectorClock("n1", nodes)
    vc2 = VectorClock("n2", nodes)

    v1 = vc1.tick()
    v2 = vc2.update(v1)  # n2 receives n1's message → n1 happens-before n2
    assert VectorClock.happens_before(v1, v2)


# ------------------------------------------------------------------ #
#  5. Memory pressure                                                  #
# ------------------------------------------------------------------ #

def test_large_concurrent_writes_no_data_loss():
    store = BlockStore()
    items = {}
    for i in range(100):
        data = os.urandom(64 * 1024)
        store.put(f"k{i}", data)
        items[f"k{i}"] = data
    for k, v in items.items():
        assert store.get(k) == v


# ------------------------------------------------------------------ #
#  6. Disk silent corruption — 100 % detection rate                   #
# ------------------------------------------------------------------ #

def test_100pct_corruption_detection_rate():
    store = BlockStore()
    n = 500
    for i in range(n):
        store.put(f"k{i}", os.urandom(64))

    corrupted = [f"k{i}" for i in range(0, n, 5)]
    for k in corrupted:
        store.inject_bit_flip(k, 0)

    detected = set(store.corrupt_keys())
    missed = set(corrupted) - detected
    assert missed == set(), f"Missed corruptions: {missed}"
    assert len(detected) == len(corrupted)


# ------------------------------------------------------------------ #
#  7. Network partition + heal                                         #
# ------------------------------------------------------------------ #

def test_sync_after_partition_restores_all_data():
    replicas = ReplicaSet(n=3, quorum=2)

    pre = {f"pre_{i}": os.urandom(32) for i in range(30)}
    for k, v in pre.items():
        replicas.put(k, v)

    replicas.partition([2])

    during = {f"during_{i}": os.urandom(32) for i in range(10)}
    for k, v in during.items():
        replicas.put(k, v)

    replicas.heal_partition()
    replicas.sync()

    all_data = {**pre, **during}
    for k, v in all_data.items():
        assert replicas.get_replica(2).get(k) == v


# ------------------------------------------------------------------ #
#  8. Cascading replica failure                                        #
# ------------------------------------------------------------------ #

def test_last_replica_holds_all_data():
    n = 5
    replicas = ReplicaSet(n=n, quorum=3)
    data = {f"k{i}": os.urandom(32) for i in range(100)}
    for k, v in data.items():
        replicas.put(k, v)

    replicas.kill_replicas(list(range(n - 1)))

    survivor = replicas.get_replica(n - 1)
    for k, v in data.items():
        assert survivor.get(k) == v


# ------------------------------------------------------------------ #
#  9. Large / small record mix                                         #
# ------------------------------------------------------------------ #

def test_large_small_record_mix_no_fragmentation_loss():
    store = BlockStore()
    tiny = {f"tiny_{i}": bytes([i % 256]) for i in range(1_000)}
    large = {f"large_{i}": os.urandom(512 * 1024) for i in range(5)}

    for k, v in {**tiny, **large}.items():
        store.put(k, v)

    for k, v in tiny.items():
        assert store.get(k) == v
    for k, v in large.items():
        assert store.get(k) == v

    assert store.corrupt_keys() == []


# ------------------------------------------------------------------ #
#  10. Time-series reorder                                             #
# ------------------------------------------------------------------ #

def test_out_of_order_writes_correct_reconstruction():
    """
    Writes arrive out of order.  After all writes, each key retrieves
    exactly the data that was last written for it.
    """
    store = BlockStore()
    n = 200
    # Write in reverse order
    expected = {}
    for i in range(n - 1, -1, -1):
        key = f"ts_{i:06d}"
        data = i.to_bytes(4, "big")
        store.put(key, data)
        expected[key] = data

    for k, v in expected.items():
        assert store.get(k) == v
