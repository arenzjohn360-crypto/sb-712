"""
Agriculture / Environmental monitoring stress tests for SB688.

Covers:
- Months offline: sensor node accumulates 5 000 reads; syncs without drift
- No data gap: sequential time-series fully present after sync
- Corrupted calibration data raises CorruptionError
- Valid calibration reads back correctly
- Self-heal calibration from backup replica
"""
import os
import pytest
from sb688 import BlockStore, CorruptionError, IntegrityChecker


class TestLongDurationSensorLogs:
    def test_months_offline_sync_completeness(self):
        sensor_node = BlockStore()
        central = BlockStore()

        baseline = {f"baseline_{i}": os.urandom(16) for i in range(50)}
        for k, v in baseline.items():
            sensor_node.put(k, v)
            central.put(k, v)

        offline_readings = {f"reading_{i:06d}": os.urandom(16) for i in range(5_000)}
        for k, v in offline_readings.items():
            sensor_node.put(k, v)

        for k in sensor_node.keys():
            if k not in central:
                central.put(k, sensor_node.get(k))

        for k, v in offline_readings.items():
            assert central.get(k) == v

        for k, v in baseline.items():
            assert central.get(k) == v

    def test_no_data_gap_in_sequential_time_series(self):
        store = BlockStore()
        n = 1_000
        for i in range(n):
            store.put(f"ts_{i:08d}", i.to_bytes(4, "big"))
        for i in range(n):
            val = store.get(f"ts_{i:08d}")
            assert int.from_bytes(val, "big") == i


class TestSensorDriftDetection:
    def test_corrupted_calibration_detected(self):
        store = BlockStore()
        calibration = b"offset=0.0025;gain=1.001;temp_coeff=0.0001"
        store.put("sensor_calibration", calibration)
        store.inject_bit_flip("sensor_calibration", 5)
        with pytest.raises(CorruptionError):
            store.get("sensor_calibration")

    def test_valid_calibration_readable(self):
        store = BlockStore()
        calibration = b"offset=0.0025;gain=1.001;temp_coeff=0.0001"
        store.put("sensor_calibration", calibration)
        assert store.get("sensor_calibration") == calibration

    def test_self_heal_calibration_from_backup(self):
        primary = BlockStore()
        backup = BlockStore()
        calibration = b"offset=0.0025;gain=1.001"
        primary.put("cal", calibration)
        backup.put("cal", calibration)
        primary.inject_bit_flip("cal", 0)

        checker = IntegrityChecker(primary, repair_source=backup)
        results = checker.scan_and_heal()

        assert results.get("cal") is True
        assert primary.get("cal") == calibration
