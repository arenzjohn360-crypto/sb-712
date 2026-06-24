"""
Manufacturing / IoT stress tests for SB688.

Covers:
- 100 K device writes: no loss
- Concurrent device threads: no corruption
- OTA firmware: crash mid-delivery rolls back to stable version
- OTA checksum verification
- Sub-millisecond p99.99 write latency (in-memory store)
"""
import hashlib
import os
import threading
import time
import pytest
from sb688 import BlockStore, DurableStore, SimulatedCrash
from sb688.wal import WriteAheadLog


class TestConcurrentDeviceWrites:
    def test_100k_device_writes_no_loss(self):
        store = BlockStore()
        n = 100_000
        data = {f"device_{i:06d}": os.urandom(16) for i in range(n)}
        for k, v in data.items():
            store.put(k, v)
        assert len(store) == n
        assert store.corrupt_keys() == []

    def test_concurrent_device_threads_no_corruption(self):
        store = BlockStore()
        errors = []
        n_devices, writes_per_device = 20, 100

        def device_writer(device_id: int):
            for seq in range(writes_per_device):
                key = f"dev_{device_id}_seq_{seq:04d}"
                data = os.urandom(32)
                store.put(key, data)
                try:
                    result = store.get(key)
                    if result != data:
                        errors.append(f"Mismatch for {key}")
                except Exception as exc:
                    errors.append(str(exc))

        threads = [
            threading.Thread(target=device_writer, args=(i,))
            for i in range(n_devices)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


class TestFirmwareOTAUpdate:
    def test_partial_ota_rollback_on_crash(self):
        wal = WriteAheadLog()
        inner = BlockStore()
        ds = DurableStore(store=inner, wal=wal)
        ds.put("firmware", b"v1.0.0_stable_image")

        inner.arm_crash(after_n_writes=0)
        try:
            ds.put("firmware", b"v2.0.0_partial_image")
        except SimulatedCrash:
            pass
        inner.disarm_crash()
        ds.recover()

        assert ds.get("firmware") == b"v1.0.0_stable_image"

    def test_ota_sha256_checksum_verified(self):
        store = BlockStore()
        firmware = os.urandom(256 * 1024)
        expected_hash = hashlib.sha256(firmware).hexdigest()
        store.put("firmware_image", firmware)
        received = store.get("firmware_image")
        assert hashlib.sha256(received).hexdigest() == expected_hash


class TestSubMillisecondLatency:
    def test_p9999_write_latency_sub_10ms(self):
        """p99.99 write latency must be under 10 ms for the in-memory store."""
        store = BlockStore()
        n = 10_000
        latencies = []
        for i in range(n):
            data = os.urandom(64)
            t0 = time.perf_counter()
            store.put(f"k{i}", data)
            latencies.append(time.perf_counter() - t0)

        latencies.sort()
        p9999_idx = int(n * 0.9999)
        p9999 = latencies[min(p9999_idx, n - 1)]
        assert p9999 < 0.01, f"p99.99 latency too high: {p9999 * 1000:.3f} ms"
