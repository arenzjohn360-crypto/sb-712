"""
SB688 Block Store — atomic writes with SHA-256 checksums.

Every block is stored together with the SHA-256 digest of its payload.
Any bit-level corruption is therefore detected on the next read.
Crash simulation (arm_crash / disarm_crash) allows the test suite to
model power-off events at arbitrary write boundaries.
"""
import hashlib
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional


class SimulatedCrash(Exception):
    """Raised to simulate a power-off or system crash during a write."""


class CorruptionError(Exception):
    """Raised when a block fails its SHA-256 integrity check."""


@dataclass
class Block:
    key: str
    data: bytes
    checksum: bytes  # 32-byte SHA-256 digest of `data`
    version: int = 0

    @classmethod
    def create(cls, key: str, data: bytes, version: int = 0) -> "Block":
        return cls(
            key=key,
            data=data,
            checksum=hashlib.sha256(data).digest(),
            version=version,
        )

    def verify(self) -> bool:
        return hashlib.sha256(self.data).digest() == self.checksum

    def with_bit_flip(self, byte_offset: int, bit: int = 0) -> "Block":
        """Return a new Block with one bit flipped (simulates cosmic-ray / EMP)."""
        buf = bytearray(self.data)
        buf[byte_offset % len(buf)] ^= 1 << (bit % 8)
        return Block(
            key=self.key,
            data=bytes(buf),
            checksum=self.checksum,  # intentionally stale — will fail verify()
            version=self.version,
        )


class BlockStore:
    """
    Thread-safe, in-memory key-value block store with SHA-256 integrity checking.

    Supports:
    - Atomic puts (lock-protected) with version tracking.
    - Crash simulation via arm_crash() / disarm_crash().
    - Fault injection (bit flips, arbitrary data replacement).
    - Bulk verification via verify_all() / corrupt_keys().
    - Snapshot / restore for crash-recovery testing.
    """

    def __init__(self) -> None:
        self._blocks: Dict[str, Block] = {}
        self._lock = threading.Lock()
        self._write_counter = 0
        self._crash_after: Optional[int] = None

    # ------------------------------------------------------------------ #
    #  Crash simulation                                                    #
    # ------------------------------------------------------------------ #

    def arm_crash(self, after_n_writes: int) -> None:
        """Raise SimulatedCrash on the (after_n_writes + 1)-th put call."""
        with self._lock:
            self._crash_after = after_n_writes
            self._write_counter = 0

    def disarm_crash(self) -> None:
        with self._lock:
            self._crash_after = None
            self._write_counter = 0

    # ------------------------------------------------------------------ #
    #  Core API                                                            #
    # ------------------------------------------------------------------ #

    def put(self, key: str, data: bytes) -> "Block":
        with self._lock:
            if self._crash_after is not None:
                if self._write_counter >= self._crash_after:
                    raise SimulatedCrash(
                        f"Simulated crash after {self._crash_after} write(s)"
                    )
                self._write_counter += 1
            version = (
                self._blocks[key].version + 1 if key in self._blocks else 0
            )
            block = Block.create(key, data, version)
            self._blocks[key] = block
            return block

    def get(self, key: str) -> bytes:
        with self._lock:
            block = self._blocks[key]  # raises KeyError if missing
        if not block.verify():
            raise CorruptionError(
                f"Integrity check failed for block {key!r}"
            )
        return block.data

    def get_version(self, key: str) -> int:
        with self._lock:
            return self._blocks[key].version

    def delete(self, key: str) -> None:
        with self._lock:
            self._blocks.pop(key, None)

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._blocks.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._blocks)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._blocks

    # ------------------------------------------------------------------ #
    #  Fault injection (test helpers)                                      #
    # ------------------------------------------------------------------ #

    def inject_bit_flip(
        self, key: str, byte_offset: int = 0, bit: int = 0
    ) -> None:
        """Flip one bit in a stored block without updating the checksum."""
        with self._lock:
            self._blocks[key] = self._blocks[key].with_bit_flip(
                byte_offset, bit
            )

    def inject_corrupt_data(self, key: str, corrupt_data: bytes) -> None:
        """Replace block data with arbitrary bytes without updating the checksum."""
        with self._lock:
            b = self._blocks[key]
            self._blocks[key] = Block(
                key=b.key,
                data=corrupt_data,
                checksum=b.checksum,
                version=b.version,
            )

    # ------------------------------------------------------------------ #
    #  Verification helpers                                                #
    # ------------------------------------------------------------------ #

    def verify_all(self) -> Dict[str, bool]:
        with self._lock:
            return {k: v.verify() for k, v in self._blocks.items()}

    def corrupt_keys(self) -> List[str]:
        return [k for k, ok in self.verify_all().items() if not ok]

    def snapshot(self) -> Dict[str, bytes]:
        """Return a copy of all non-corrupt blocks keyed by their key."""
        with self._lock:
            return {
                k: v.data for k, v in self._blocks.items() if v.verify()
            }

    def restore_from_snapshot(self, snapshot: Dict[str, bytes]) -> None:
        """Overwrite store contents with the given snapshot."""
        with self._lock:
            for key, data in snapshot.items():
                version = (
                    self._blocks[key].version if key in self._blocks else 0
                )
                self._blocks[key] = Block.create(key, data, version)
