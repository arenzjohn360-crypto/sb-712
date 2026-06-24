"""
SB688 Write-Ahead Log (WAL) and DurableStore.

Every mutation is logged before it reaches the BlockStore.  On crash
(SimulatedCrash), call DurableStore.recover() to replay only committed
entries and bring the store back to the last consistent state.

WAL entry layout
----------------
Each entry carries its own SHA-256 checksum so corruption of the WAL
itself is detected at recovery time.

Commit protocol
---------------
1. wal.log_put(key, data)   — append intent
2. store.put(key, data)     — apply to store
3. wal.commit(key)          — mark as durable

If the process crashes between steps 1–2 or 2–3 the entry has no
matching COMMIT and is silently skipped during recovery.
"""
import hashlib
import threading
from base64 import b64decode, b64encode
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class WALOp(str, Enum):
    PUT = "put"
    DELETE = "delete"
    COMMIT = "commit"
    CHECKPOINT = "checkpoint"


class WALCorruptionError(Exception):
    """Raised when a WAL entry fails its own checksum during recovery."""


@dataclass
class WALEntry:
    op: str
    key: str
    data_b64: Optional[str]  # base64-encoded payload; None for non-data ops
    seq: int
    checksum: str  # hex SHA-256 of the entry fields

    @classmethod
    def create(
        cls,
        op: WALOp,
        key: str,
        data: Optional[bytes],
        seq: int,
    ) -> "WALEntry":
        data_b64 = b64encode(data).decode() if data is not None else None
        payload = f"{op.value}|{key}|{data_b64 or ''}|{seq}"
        checksum = hashlib.sha256(payload.encode()).hexdigest()
        return cls(
            op=op.value, key=key, data_b64=data_b64, seq=seq, checksum=checksum
        )

    def verify(self) -> bool:
        payload = f"{self.op}|{self.key}|{self.data_b64 or ''}|{self.seq}"
        return hashlib.sha256(payload.encode()).hexdigest() == self.checksum

    @property
    def data(self) -> Optional[bytes]:
        return b64decode(self.data_b64) if self.data_b64 is not None else None


class WriteAheadLog:
    """
    In-memory WAL.  Thread-safe via an internal lock.
    """

    def __init__(self) -> None:
        self._entries: List[WALEntry] = []
        self._lock = threading.Lock()
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def log_put(self, key: str, data: bytes) -> WALEntry:
        with self._lock:
            entry = WALEntry.create(WALOp.PUT, key, data, self._next_seq())
            self._entries.append(entry)
            return entry

    def log_delete(self, key: str) -> WALEntry:
        with self._lock:
            entry = WALEntry.create(WALOp.DELETE, key, None, self._next_seq())
            self._entries.append(entry)
            return entry

    def commit(self, key: str) -> WALEntry:
        with self._lock:
            entry = WALEntry.create(WALOp.COMMIT, key, None, self._next_seq())
            self._entries.append(entry)
            return entry

    def checkpoint(self) -> None:
        """Truncate the log after recording a checkpoint marker."""
        with self._lock:
            entry = WALEntry.create(
                WALOp.CHECKPOINT, "__checkpoint__", None, self._next_seq()
            )
            self._entries = [entry]

    def recover(self, store) -> int:
        """
        Replay committed entries into *store*.  Returns count of entries
        replayed.  Raises WALCorruptionError if any entry checksum fails.

        Recovery rule: for each key, scan its WAL entries in sequence order
        and track a state machine: a pending mutation (PUT or DELETE) becomes
        committed only when an immediately following COMMIT entry appears
        before the next mutation for that key.  Only the last committed
        mutation per key is applied.
        """
        with self._lock:
            entries = list(self._entries)

        # Verify all entry checksums first
        for entry in entries:
            if not entry.verify():
                raise WALCorruptionError(
                    f"WAL entry seq={entry.seq} failed checksum"
                )

        # Build per-key ordered entry list (preserving sequence order)
        from collections import defaultdict

        key_entries: dict = defaultdict(list)
        for entry in entries:
            if entry.key == "__checkpoint__":
                continue
            key_entries[entry.key].append(entry)

        replayed = 0
        for key, ops in key_entries.items():
            # State machine: track the last fully committed operation
            committed_entry: object = None
            pending_entry: object = None
            for entry in ops:
                if entry.op in (WALOp.PUT, WALOp.DELETE):
                    pending_entry = entry  # new mutation pending
                elif entry.op == WALOp.COMMIT:
                    if pending_entry is not None:
                        committed_entry = pending_entry
                        pending_entry = None  # consumed by this commit

            if committed_entry is None:
                continue
            if committed_entry.op == WALOp.PUT and committed_entry.data is not None:
                store.put(key, committed_entry.data)
                replayed += 1
            elif committed_entry.op == WALOp.DELETE:
                store.delete(key)
                replayed += 1
        return replayed

    def verify_all(self) -> bool:
        with self._lock:
            return all(e.verify() for e in self._entries)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class DurableStore:
    """
    BlockStore wrapped with a WAL for crash recovery.

    ``put`` follows the three-phase commit protocol:
    log → apply → commit.  ``recover`` replays the WAL into the
    underlying store after a crash.
    """

    def __init__(self, store=None, wal=None) -> None:
        from .store import BlockStore

        self._store = store if store is not None else BlockStore()
        self._wal = wal if wal is not None else WriteAheadLog()

    def put(self, key: str, data: bytes) -> None:
        self._wal.log_put(key, data)
        self._store.put(key, data)  # may raise SimulatedCrash
        self._wal.commit(key)

    def get(self, key: str) -> bytes:
        return self._store.get(key)

    def delete(self, key: str) -> None:
        self._wal.log_delete(key)
        self._store.delete(key)
        self._wal.commit(key)

    def recover(self) -> int:
        return self._wal.recover(self._store)

    @property
    def store(self):
        return self._store

    @property
    def wal(self):
        return self._wal
