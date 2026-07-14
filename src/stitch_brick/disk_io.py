"""
Disk persistence helpers for checkpoints and quarantine.

CheckpointDiskManager  — saves/loads ProtectedSpine snapshots to /checkpoints/
QuarantineDiskManager  — logs quarantined fault records to /quarantine/

Each checkpoint file is wrapped in an envelope that stores a SHA-256 seal of
the data payload, so load_latest() can silently skip corrupted files and fall
back to the next-most-recent healthy checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional


class CheckpointDiskManager:
    """Saves and loads ProtectedSpine snapshots to/from *root*/checkpoints/."""

    def __init__(self, root: Path) -> None:
        self._dir = root / "checkpoints"
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------

    def save(self, project_id: str, snapshot: dict) -> Path:
        """
        Persist *snapshot* to disk wrapped in an integrity envelope.
        File name: <project_id>_<epoch_ms>.json
        """
        ts = int(time.time() * 1000)
        path = self._dir / f"{project_id}_{ts}.json"
        data_json = json.dumps(snapshot, indent=2)
        file_seal = hashlib.sha256(data_json.encode()).hexdigest()
        envelope = {"seal": file_seal, "data": snapshot}
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        return path

    def load_latest(self, project_id: str) -> Optional[dict]:
        """
        Return the most-recent checkpoint whose envelope seal is valid.
        Returns None if no valid checkpoint is found.
        """
        for path in self._sorted_candidates(project_id):
            data = self._load_verified(path)
            if data is not None:
                return data
        return None

    def load_latest_raw(self, project_id: str) -> Optional[dict]:
        """Load the most-recent checkpoint without seal verification (for testing)."""
        candidates = self._sorted_candidates(project_id)
        if not candidates:
            return None
        try:
            envelope = json.loads(candidates[0].read_text(encoding="utf-8"))
            return envelope.get("data")
        except (json.JSONDecodeError, KeyError):
            return None

    # ------------------------------------------------------------------

    def _sorted_candidates(self, project_id: str) -> list:
        return sorted(
            self._dir.glob(f"{project_id}_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def _load_verified(self, path: Path) -> Optional[dict]:
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            data: dict = envelope["data"]
            stored_seal: str = envelope["seal"]
            actual_seal = hashlib.sha256(
                json.dumps(data, indent=2).encode()
            ).hexdigest()
            if actual_seal == stored_seal:
                return data
        except (json.JSONDecodeError, KeyError, OSError):
            pass
        return None


class QuarantineDiskManager:
    """Logs quarantined fault records to *root*/quarantine/."""

    def __init__(self, root: Path) -> None:
        self._dir = root / "quarantine"
        self._dir.mkdir(parents=True, exist_ok=True)

    def log(self, fault_id: str, data: dict) -> Path:
        ts = int(time.time() * 1000)
        path = self._dir / f"quarantine_{fault_id}_{ts}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def count(self) -> int:
        return len(list(self._dir.glob("quarantine_*.json")))
