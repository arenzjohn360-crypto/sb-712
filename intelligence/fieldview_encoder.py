"""
fieldview_encoder.py — SB-712 IronBraid Radiant Core

Watches RAM usage, disk state, file hashes, ledger rhythm, and mutation
rate to produce a real-time field snapshot used by the Forecast Node and
Mask Evaluator.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class FieldSnapshot:
    """Point-in-time view of system health indicators."""

    timestamp: float = field(default_factory=time.time)
    file_hashes: Dict[str, str] = field(default_factory=dict)
    mutation_count: int = 0
    disk_read_errors: int = 0
    ledger_sequence: int = 0
    fault_events: List[str] = field(default_factory=list)


def hash_file(path: Path, algorithm: str = "sha256") -> Optional[str]:
    """Return hex digest of *path* or ``None`` if the file is unreadable."""
    h = hashlib.new(algorithm)
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def hash_string(data: str, algorithm: str = "sha256") -> str:
    """Return hex digest of a UTF-8 encoded string."""
    return hashlib.new(algorithm, data.encode()).hexdigest()


class FieldViewEncoder:
    """
    Encodes the current field state by scanning watched paths and
    tracking mutations relative to a previous snapshot.

    Usage::

        encoder = FieldViewEncoder(watch_paths=[Path("spine"), Path("ledger")])
        snapshot = encoder.capture()
    """

    def __init__(
        self,
        watch_paths: Optional[List[Path]] = None,
        ledger_sequence: int = 0,
    ) -> None:
        self.watch_paths: List[Path] = watch_paths or []
        self.ledger_sequence = ledger_sequence
        self._previous_hashes: Dict[str, str] = {}

    def capture(self) -> FieldSnapshot:
        """Scan watched paths and return a fresh :class:`FieldSnapshot`."""
        snapshot = FieldSnapshot(ledger_sequence=self.ledger_sequence)
        for base in self.watch_paths:
            for root, _dirs, files in os.walk(base):
                for name in files:
                    fpath = Path(root) / name
                    digest = hash_file(fpath)
                    key = str(fpath)
                    if digest is None:
                        snapshot.disk_read_errors += 1
                        snapshot.fault_events.append(f"READ_ERROR:{key}")
                    else:
                        snapshot.file_hashes[key] = digest
                        if key in self._previous_hashes:
                            if self._previous_hashes[key] != digest:
                                snapshot.mutation_count += 1
                                snapshot.fault_events.append(f"MUTATION:{key}")
        self._previous_hashes = dict(snapshot.file_hashes)
        return snapshot
