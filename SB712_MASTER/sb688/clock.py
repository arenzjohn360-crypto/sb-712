"""
SB688 Logical Clocks — causality tracking across distributed nodes.

LamportClock provides a monotonically increasing logical timestamp for
a single node.  VectorClock tracks per-node counters so that happens-
before relationships and concurrent events can be detected across a
cluster even in the presence of clock skew.
"""
import threading
from dataclasses import dataclass, field
from typing import Dict, List


class LamportClock:
    """
    Monotonically increasing logical clock (Lamport, 1978).

    tick()        — advance the clock for a local event; return new time.
    update(recv)  — receive a remote timestamp; advance past it; return new time.
    """

    def __init__(self, initial: int = 0) -> None:
        self._time = initial
        self._lock = threading.Lock()

    def tick(self) -> int:
        with self._lock:
            self._time += 1
            return self._time

    def update(self, received: int) -> int:
        with self._lock:
            self._time = max(self._time, received) + 1
            return self._time

    @property
    def time(self) -> int:
        with self._lock:
            return self._time


class VectorClock:
    """
    Vector clock for multi-node causality detection.

    tick()          — advance this node's component; return snapshot.
    update(remote)  — merge a remote vector clock; advance; return snapshot.
    happens_before(v1, v2)  — True if v1 → v2.
    concurrent(v1, v2)      — True if neither happens before the other.
    """

    def __init__(self, node_id: str, nodes: List[str]) -> None:
        self._node_id = node_id
        self._clock: Dict[str, int] = {n: 0 for n in nodes}
        self._lock = threading.Lock()

    def tick(self) -> Dict[str, int]:
        with self._lock:
            self._clock[self._node_id] += 1
            return dict(self._clock)

    def update(self, received: Dict[str, int]) -> Dict[str, int]:
        with self._lock:
            for node, t in received.items():
                if node in self._clock:
                    self._clock[node] = max(self._clock[node], t)
            self._clock[self._node_id] += 1
            return dict(self._clock)

    @staticmethod
    def happens_before(v1: Dict[str, int], v2: Dict[str, int]) -> bool:
        all_nodes = set(v1) | set(v2)
        return (
            all(v1.get(n, 0) <= v2.get(n, 0) for n in all_nodes)
            and v1 != v2
        )

    @staticmethod
    def concurrent(v1: Dict[str, int], v2: Dict[str, int]) -> bool:
        return (
            not VectorClock.happens_before(v1, v2)
            and not VectorClock.happens_before(v2, v1)
        )

    @property
    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._clock)


@dataclass
class TimestampedRecord:
    key: str
    data: bytes
    lamport: int
    vector: Dict[str, int] = field(default_factory=dict)
    node_id: str = ""
