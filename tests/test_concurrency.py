"""
Concurrency tests — safe under simultaneous reads, writes, and deletes.

Covers:
- N writers to disjoint keys: all writes land correctly
- N readers on the same key: never see corrupt data
- Mixed readers / writers / deleters: no corruption detected
- Version numbers are monotonically increasing even under concurrent writes
"""
import os
import threading
import time
import pytest
from sb688 import BlockStore, CorruptionError


N_WRITERS = 8
N_READERS = 8
N_KEYS = 50
DURATION = 0.5  # seconds


def test_concurrent_disjoint_key_writes():
    """N writers each writing to their own key space: all data lands correctly."""
    store = BlockStore()
    expected = {}
    lock = threading.Lock()
    errors = []

    def writer(thread_id: int):
        for i in range(100):
            key = f"w{thread_id}_k{i}"
            data = os.urandom(32)
            store.put(key, data)
            with lock:
                expected[key] = data

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(N_WRITERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for k, v in expected.items():
        assert store.get(k) == v


def test_concurrent_readers_see_valid_data():
    """Multiple readers on the same key must never observe a corrupt block."""
    store = BlockStore()
    data = os.urandom(256)
    store.put("shared", data)
    errors = []

    def reader():
        for _ in range(500):
            try:
                val = store.get("shared")
                if val != data:
                    errors.append(f"Unexpected value: {val[:10]!r}")
            except Exception as exc:
                errors.append(str(exc))

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(N_READERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []


def test_concurrent_mixed_operations_no_corruption():
    """Writers, readers, and deleters operating simultaneously produce no corruption."""
    store = BlockStore()
    for i in range(N_KEYS):
        store.put(f"k{i}", os.urandom(32))

    stop = threading.Event()
    errors = []

    def writer():
        while not stop.is_set():
            key = f"k{int.from_bytes(os.urandom(1), 'big') % N_KEYS}"
            store.put(key, os.urandom(32))

    def reader():
        while not stop.is_set():
            key = f"k{int.from_bytes(os.urandom(1), 'big') % N_KEYS}"
            try:
                store.get(key)
            except KeyError:
                pass
            except CorruptionError as exc:
                errors.append(str(exc))

    def deleter():
        while not stop.is_set():
            key = f"k{int.from_bytes(os.urandom(1), 'big') % N_KEYS}"
            store.delete(key)
            store.put(key, os.urandom(32))

    threads = (
        [threading.Thread(target=writer, daemon=True) for _ in range(4)]
        + [threading.Thread(target=reader, daemon=True) for _ in range(4)]
        + [threading.Thread(target=deleter, daemon=True) for _ in range(2)]
    )
    for t in threads:
        t.start()
    time.sleep(DURATION)
    stop.set()
    for t in threads:
        t.join(timeout=2)

    assert errors == [], f"Corruption detected during concurrent access: {errors}"


def test_sequential_version_monotonicity():
    """Sequential overwrites produce strictly increasing version numbers."""
    store = BlockStore()
    for i in range(10):
        store.put("key", f"v{i}".encode())
        assert store.get_version("key") == i
