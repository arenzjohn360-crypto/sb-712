"""
SB688 — Universal Data Integrity System.

Provides atomic storage, crash recovery, checksumming, encryption,
replication, erasure coding, and logical-clock ordering.
"""
from .store import Block, BlockStore, CorruptionError, SimulatedCrash
from .wal import DurableStore, WriteAheadLog, WALCorruptionError
from .integrity import IntegrityChecker, IntegrityEvent
from .crypto import EncryptedStore, EncryptionError
from .merkle import MerkleTree
from .replica import ReplicaSet, PartitionError
from .ecc import ECCEncoder
from .clock import LamportClock, VectorClock, TimestampedRecord

__version__ = "0.1.0"

__all__ = [
    "Block",
    "BlockStore",
    "CorruptionError",
    "SimulatedCrash",
    "DurableStore",
    "WriteAheadLog",
    "WALCorruptionError",
    "IntegrityChecker",
    "IntegrityEvent",
    "EncryptedStore",
    "EncryptionError",
    "MerkleTree",
    "ReplicaSet",
    "PartitionError",
    "ECCEncoder",
    "LamportClock",
    "VectorClock",
    "TimestampedRecord",
]
