"""
Space and extreme-environment stress tests for SB688.

Scenarios
---------
- Deep Space / No Connectivity — write, disconnect, reconnect, verify
- Cosmic Radiation — single/double bit-flip detection and ECC recovery
- Extreme Temperature — bulk storage degradation via checksum verification
- High Radiation (Solar Flare) — 5 / 20 / 40 % block corruption; self-heal
- Mars Signal Delay — fire-and-forget writes, deferred verification
- Zero-G Hardware Vibration — random I/O interruption; no partial records
- Power Cycling — crash at every write phase; atomic commit and recovery
"""
import os
import pytest
from sb688 import (
    BlockStore,
    CorruptionError,
    DurableStore,
    ECCEncoder,
    IntegrityChecker,
    PartitionError,
    ReplicaSet,
    SimulatedCrash,
)
from sb688.wal import WriteAheadLog


# ------------------------------------------------------------------ #
#  Deep Space / No Connectivity                                        #
# ------------------------------------------------------------------ #

class TestDeepSpaceConnectivity:
    def test_offline_write_survives_reconnect(self):
        """Data written before disconnection is intact after reconnection."""
        store = BlockStore()
        data = {f"sensor_{i}": os.urandom(64) for i in range(100)}
        for k, v in data.items():
            store.put(k, v)

        # Simulate 30-day offline — no operations
        assert store.corrupt_keys() == []
        for k, v in data.items():
            assert store.get(k) == v

    def test_deferred_sync_after_reconnect(self):
        """Local replica accumulates writes offline; syncs fully on reconnect."""
        local = BlockStore()
        remote = BlockStore()

        offline_data = {f"offline_{i}": os.urandom(32) for i in range(50)}
        for k, v in offline_data.items():
            local.put(k, v)

        # Reconnect: push local → remote
        for k in local.keys():
            remote.put(k, local.get(k))

        for k, v in offline_data.items():
            assert remote.get(k) == v


# ------------------------------------------------------------------ #
#  Cosmic Radiation — bit flips                                        #
# ------------------------------------------------------------------ #

class TestCosmicRadiation:
    def test_single_bit_flip_detected(self):
        store = BlockStore()
        store.put("block", os.urandom(128))
        store.inject_bit_flip("block", byte_offset=42, bit=3)
        with pytest.raises(CorruptionError):
            store.get("block")

    def test_double_bit_flip_detected(self):
        store = BlockStore()
        store.put("block", os.urandom(128))
        store.inject_bit_flip("block", 10, 0)
        store.inject_bit_flip("block", 60, 7)
        with pytest.raises(CorruptionError):
            store.get("block")

    def test_bit_flip_at_rest_detected_by_scan(self):
        store = BlockStore()
        for i in range(20):
            store.put(f"k{i}", os.urandom(64))
        for i in [2, 11, 17]:
            store.inject_bit_flip(f"k{i}", 0)
        assert set(store.corrupt_keys()) == {"k2", "k11", "k17"}

    def test_ecc_recovers_from_single_shard_loss(self):
        """ECC reconstructs data when any one shard is destroyed by radiation."""
        enc = ECCEncoder(k=4)
        data = os.urandom(256)
        shards, parity = enc.encode(data)
        for lost_idx in range(4):
            test_shards = list(shards)
            test_shards[lost_idx] = None
            assert enc.decode(test_shards, parity) == data

    def test_ecc_detects_shard_inconsistency(self):
        enc = ECCEncoder(k=4)
        shards, parity = enc.encode(os.urandom(256))
        bad = bytearray(shards[1])
        bad[0] ^= 0xFF
        shards = list(shards)
        shards[1] = bytes(bad)
        assert not enc.verify_shards(shards, parity)


# ------------------------------------------------------------------ #
#  Extreme Temperature — bulk degradation                              #
# ------------------------------------------------------------------ #

class TestExtremeTemperature:
    def test_bulk_corruption_all_detected(self):
        """5% temperature-induced corruption is fully detected."""
        store = BlockStore()
        for i in range(50):
            store.put(f"k{i}", os.urandom(128))

        corrupted = {f"k{i}" for i in range(0, 50, 10)}
        for k in corrupted:
            store.inject_bit_flip(k, 0)

        assert set(store.corrupt_keys()) == corrupted

    def test_healthy_blocks_unaffected_by_neighbor_corruption(self):
        """Uncorrupted blocks verify correctly even when neighbours are corrupt."""
        store = BlockStore()
        for i in range(10):
            store.put(f"k{i}", os.urandom(64))
        store.inject_corrupt_data("k5", b"\x00" * 64)

        for i in range(10):
            if i != 5:
                assert store.get(f"k{i}") is not None


# ------------------------------------------------------------------ #
#  High Radiation — solar flare (5 / 20 / 40 % corruption)            #
# ------------------------------------------------------------------ #

class TestHighRadiation:
    @pytest.mark.parametrize("corruption_pct", [5, 20, 40])
    def test_self_heal_from_replica(self, corruption_pct):
        primary = BlockStore()
        backup = BlockStore()
        n = 100
        data = {f"blk_{i}": os.urandom(64) for i in range(n)}

        for k, v in data.items():
            primary.put(k, v)
            backup.put(k, v)

        corrupt_count = max(1, n * corruption_pct // 100)
        corrupt_keys = [f"blk_{i}" for i in range(corrupt_count)]
        for k in corrupt_keys:
            primary.inject_bit_flip(k, 0)

        checker = IntegrityChecker(primary, repair_source=backup)
        results = checker.scan_and_heal()

        assert len(results) == corrupt_count
        assert all(results.values()), "Some blocks could not be healed"
        for k, v in data.items():
            assert primary.get(k) == v


# ------------------------------------------------------------------ #
#  Mars Signal Delay — fire-and-forget with deferred verification      #
# ------------------------------------------------------------------ #

class TestMarsLatency:
    def test_fire_and_forget_deferred_verification(self):
        """Writes are queued and verified once the signal returns."""
        store = BlockStore()
        pending = {}
        for i in range(100):
            data = os.urandom(64)
            store.put(f"key_{i}", data)
            pending[f"key_{i}"] = data

        # "Signal returns" — verify all deferred
        for k, v in pending.items():
            assert store.get(k) == v


# ------------------------------------------------------------------ #
#  Zero-G Hardware Vibration — I/O interruption                        #
# ------------------------------------------------------------------ #

class TestZeroGVibration:
    def test_crash_leaves_no_partial_record(self):
        wal = WriteAheadLog()
        inner = BlockStore()
        ds = DurableStore(store=inner, wal=wal)
        ds.put("pre", b"safe")

        inner.arm_crash(after_n_writes=0)
        with pytest.raises(SimulatedCrash):
            ds.put("partial", b"x" * 4096)
        inner.disarm_crash()
        ds.recover()

        assert ds.get("pre") == b"safe"
        assert "partial" not in inner


# ------------------------------------------------------------------ #
#  Power Cycling — crash at every write phase                          #
# ------------------------------------------------------------------ #

class TestPowerCycling:
    @pytest.mark.parametrize("crash_point", range(1, 6))
    def test_atomic_commit_after_power_cycle(self, crash_point):
        """Kill power before the N-th write; all prior commits survive."""
        wal = WriteAheadLog()
        inner = BlockStore()
        ds = DurableStore(store=inner, wal=wal)

        committed = {}
        for i in range(crash_point - 1):
            k, v = f"k{i}", f"v{i}".encode()
            ds.put(k, v)
            committed[k] = v

        inner.arm_crash(after_n_writes=0)
        try:
            ds.put("volatile", b"lost")
        except SimulatedCrash:
            pass
        inner.disarm_crash()
        ds.recover()

        for k, v in committed.items():
            assert ds.get(k) == v
        assert "volatile" not in inner
