"""
SB-712 Lesson Store
===================

Persists every lesson the LearningNode derives to disk so that knowledge
survives process restarts.

Layout (relative to the configured root):

    lessons/
        index.json                     ← JSON index of all lessons
        <incident_id>.txt              ← full report for each incident

The index tracks: incident_id, incident_type, severity, recorded_at.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .incident import IncidentStudyRecord


class LessonStore:
    """
    Writes lesson reports to disk and maintains a JSON index.

    Parameters
    ----------
    root_dir : str
        Directory where the ``lessons/`` folder will be created.
        Defaults to the current working directory.
    """

    def __init__(self, root_dir: str = ".") -> None:
        self._lessons_dir = os.path.join(root_dir, "lessons")
        self._index_path = os.path.join(self._lessons_dir, "index.json")
        os.makedirs(self._lessons_dir, exist_ok=True)
        if not os.path.exists(self._index_path):
            self._write_index([])

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, record: IncidentStudyRecord, report_text: str) -> str:
        """
        Persist *report_text* for *record* and update the index.

        Returns the path to the written file.
        """
        file_path = os.path.join(self._lessons_dir, f"{record.incident_id}.txt")
        with open(file_path, "w", encoding="utf-8") as fh:
            fh.write(report_text)

        entry: Dict[str, Any] = {
            "incident_id": record.incident_id,
            "incident_type": record.incident_type.value,
            "severity": record.severity.value,
            "source": record.source.value,
            "project_id": record.project_id,
            "repeat_risk": record.repeat_risk,
            "root_cause": record.root_cause,
            "prevention_rule": record.prevention_rule_added,
            "recorded_at": datetime.now(tz=timezone.utc).isoformat(),
            "file": file_path,
        }
        index = self._load_index()
        # Replace existing entry if the same incident was reprocessed.
        index = [e for e in index if e.get("incident_id") != record.incident_id]
        index.append(entry)
        self._write_index(index)
        return file_path

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_lesson(self, incident_id: str) -> Optional[str]:
        """Return the full lesson report text for *incident_id*, or None."""
        file_path = os.path.join(self._lessons_dir, f"{incident_id}.txt")
        if not os.path.exists(file_path):
            return None
        with open(file_path, encoding="utf-8") as fh:
            return fh.read()

    def all_index_entries(self) -> List[Dict[str, Any]]:
        """Return all index entries (does not read individual report files)."""
        return self._load_index()

    def entries_for_type(self, incident_type_value: str) -> List[Dict[str, Any]]:
        """Filter index entries by incident_type string value."""
        return [
            e for e in self._load_index()
            if e.get("incident_type") == incident_type_value
        ]

    def count(self) -> int:
        """Number of lessons recorded so far."""
        return len(self._load_index())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_index(self) -> List[Dict[str, Any]]:
        try:
            with open(self._index_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return []

    def _write_index(self, index: List[Dict[str, Any]]) -> None:
        with open(self._index_path, "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=2)
