"""
SB688 Replication — N-replica set with quorum writes.

ReplicaSet manages N in-process BlockStore replicas and enforces a
configurable quorum for writes.  Network partitions are simulated by
marking replica indices as unreachable; sync() heals divergent replicas
after a partition resolves.
"""
import threading
from typing import Dict, List, Optional, Set

from .store import BlockStore, CorruptionError


class PartitionError(Exception):
    """Raised when fewer replicas than the quorum threshold are reachable."""


class ReplicaSet:
    """
    Simulates a distributed replica set with quorum writes, partition
    injection, and self-healing sync.
    """

    def __init__(self, n: int = 3, quorum: Optional[int] = None) -> None:
        if n < 1:
            raise ValueError("n must be >= 1")
        self._replicas: List[BlockStore] = [BlockStore() for _ in range(n)]
        self._n = n
        self._quorum: int = quorum if quorum is not None else (n // 2 + 1)
        self._partitioned: Set[int] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Partition simulation                                                #
    # ------------------------------------------------------------------ #

    def partition(self, replica_indices: List[int]) -> None:
        """Mark replicas unreachable."""
        with self._lock:
            self._partitioned.update(replica_indices)

    def heal_partition(self) -> None:
        """Restore all replicas to reachable."""
        with self._lock:
            self._partitioned.clear()

    def _reachable(self) -> List[int]:
        with self._lock:
            return [i for i in range(self._n) if i not in self._partitioned]

    # ------------------------------------------------------------------ #
    #  Core API                                                            #
    # ------------------------------------------------------------------ #

    def put(self, key: str, data: bytes) -> int:
        """
        Write to all reachable replicas.  Raises PartitionError if
        fewer than quorum replicas are reachable.
        Returns the number of replicas written.
        """
        reachable = self._reachable()
        if len(reachable) < self._quorum:
            raise PartitionError(
                f"Only {len(reachable)} replica(s) reachable; "
                f"need {self._quorum} for quorum"
            )
        for i in reachable:
            self._replicas[i].put(key, data)
        return len(reachable)

    def get(self, key: str) -> bytes:
        """Return value from the first reachable, non-corrupt replica."""
        reachable = self._reachable()
        last_exc: Exception = KeyError(key)
        for i in reachable:
            try:
                return self._replicas[i].get(key)
            except (KeyError, CorruptionError) as exc:
                last_exc = exc
        raise last_exc

    def delete(self, key: str) -> None:
        for i in self._reachable():
            self._replicas[i].delete(key)

    # ------------------------------------------------------------------ #
    #  Self-healing                                                        #
    # ------------------------------------------------------------------ #

    def sync(self) -> Dict[str, int]:
        """
        Synchronise all replicas: replicate any missing or corrupt key
        from a healthy replica.  Returns {key: num_replicas_repaired}.
        """
        all_keys: Set[str] = set()
        for r in self._replicas:
            all_keys.update(r.keys())

        healed: Dict[str, int] = {}
        for key in all_keys:
            good_data: Optional[bytes] = None
            for r in self._replicas:
                if key in r:
                    try:
                        good_data = r.get(key)
                        break
                    except CorruptionError:
                        continue
            if good_data is None:
                continue
            count = 0
            for r in self._replicas:
                needs_repair = key not in r
                if not needs_repair:
                    try:
                        r.get(key)
                    except CorruptionError:
                        needs_repair = True
                if needs_repair:
                    r.put(key, good_data)
                    count += 1
            if count:
                healed[key] = count
        return healed

    # ------------------------------------------------------------------ #
    #  Fault injection                                                     #
    # ------------------------------------------------------------------ #

    def corrupt_replica(
        self, replica_idx: int, key: str, byte_offset: int = 0
    ) -> None:
        """Inject a bit flip into a specific replica."""
        self._replicas[replica_idx].inject_bit_flip(key, byte_offset)

    def kill_replicas(self, indices: List[int]) -> None:
        """Simulate total failure of replicas by clearing all their data."""
        for i in indices:
            for key in self._replicas[i].keys():
                self._replicas[i].delete(key)

    # ------------------------------------------------------------------ #
    #  Inspection helpers                                                  #
    # ------------------------------------------------------------------ #

    @property
    def replica_count(self) -> int:
        return self._n

    def get_replica(self, idx: int) -> BlockStore:
        return self._replicas[idx]

    def quorum_consistent(self, key: str) -> bool:
        """True if a quorum of replicas agree on the value of *key*."""
        counts: Dict[bytes, int] = {}
        for r in self._replicas:
            if key in r:
                try:
                    val = r.get(key)
                    counts[val] = counts.get(val, 0) + 1
                except CorruptionError:
                    pass
        if not counts:
            return False
        return max(counts.values()) >= self._quorum
