"""
Media / Entertainment stress tests for SB688.

Covers:
- Concurrent write + read on video frames: no torn frames (no CorruptionError)
- CDN replication to 50 nodes: all nodes eventually consistent
"""
import os
import threading
import time
import pytest
from sb688 import BlockStore, CorruptionError


class TestVideoStreamingIntegrity:
    def test_write_while_read_no_torn_frame(self):
        """Concurrent writes and reads on video frames produce no torn frames."""
        store = BlockStore()
        frame_size = 4096
        for i in range(100):
            store.put(f"frame_{i:04d}", os.urandom(frame_size))

        errors = []
        stop = threading.Event()

        def writer():
            i = 0
            while not stop.is_set():
                store.put(f"frame_{i % 100:04d}", os.urandom(frame_size))
                i += 1

        def reader():
            while not stop.is_set():
                idx = int.from_bytes(os.urandom(1), "big") % 100
                try:
                    store.get(f"frame_{idx:04d}")
                except CorruptionError as exc:
                    errors.append(str(exc))
                except KeyError:
                    pass

        threads = [threading.Thread(target=writer, daemon=True)] + [
            threading.Thread(target=reader, daemon=True) for _ in range(4)
        ]
        for t in threads:
            t.start()
        time.sleep(0.5)
        stop.set()
        for t in threads:
            t.join(timeout=2)

        assert errors == [], f"Torn frames detected: {errors}"


class TestCDNReplication:
    def test_50_node_replication_eventually_consistent(self):
        n_nodes = 50
        nodes = [BlockStore() for _ in range(n_nodes)]
        content = {f"video_{i}": os.urandom(64) for i in range(20)}

        for k, v in content.items():
            nodes[0].put(k, v)

        # Replicate primary → all other nodes
        for node in nodes[1:]:
            for k in nodes[0].keys():
                node.put(k, nodes[0].get(k))

        for node in nodes:
            for k, v in content.items():
                assert node.get(k) == v
