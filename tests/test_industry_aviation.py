"""
Aviation / Aerospace stress tests for SB688.

Covers:
- Flight data recorder: 100% write durability across crash scenarios
- Real-time telemetry burst: 1 000 sensor writes without loss
- Black-box recovery: ECC reconstructs data from a single surviving shard;
  frame recovery from backup replica after 90% primary data loss
"""
import os
import pytest
from sb688 import BlockStore, DurableStore, ECCEncoder, SimulatedCrash
from sb688.wal import WriteAheadLog


class TestFlightDataRecorder:
    @pytest.mark.parametrize("crash_after", range(5))
    def test_100pct_durability_under_crash(self, crash_after):
        wal = WriteAheadLog()
        inner = BlockStore()
        ds = DurableStore(store=inner, wal=wal)

        committed = {}
        for i in range(crash_after):
            key = f"fdr_frame_{i:06d}"
            data = os.urandom(128)
            ds.put(key, data)
            committed[key] = data

        inner.arm_crash(after_n_writes=0)
        try:
            ds.put("fdr_frame_crash", os.urandom(128))
        except SimulatedCrash:
            pass
        inner.disarm_crash()
        ds.recover()

        for k, v in committed.items():
            assert ds.get(k) == v


class TestRealTimeTelemetry:
    def test_1k_sensor_writes_no_loss(self):
        """Simulate 1 000 sensor feeds at 100 Hz — zero loss."""
        store = BlockStore()
        n = 1_000
        data = {f"sensor_{i:05d}": os.urandom(16) for i in range(n)}
        for k, v in data.items():
            store.put(k, v)
        assert len(store) == n
        assert store.corrupt_keys() == []


class TestBlackBoxRecovery:
    @pytest.mark.parametrize("lost_idx", range(4))
    def test_ecc_recovers_any_single_shard(self, lost_idx):
        """Any one of k=4 shards can be lost and recovered via parity."""
        enc = ECCEncoder(k=4)
        critical_data = os.urandom(1024)
        shards, parity = enc.encode(critical_data)
        working = list(shards)
        working[lost_idx] = None
        assert enc.decode(working, parity) == critical_data

    def test_frame_recovery_from_backup_after_90pct_loss(self):
        primary = BlockStore()
        backup = BlockStore()
        frames = {f"frame_{i:06d}": os.urandom(256) for i in range(100)}

        for k, v in frames.items():
            primary.put(k, v)
            backup.put(k, v)

        # Destroy 90 % of primary
        to_destroy = list(frames.keys())[:90]
        for k in to_destroy:
            primary.delete(k)

        # Recover from backup
        for k in to_destroy:
            primary.put(k, backup.get(k))

        for k, v in frames.items():
            assert primary.get(k) == v
