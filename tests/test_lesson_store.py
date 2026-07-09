"""Tests for sb_712.lesson_store."""
import os
import json
import tempfile

import pytest

from sb_712.incident import IncidentStudyRecord, IncidentType, SourceType, Severity
from sb_712.lesson_store import LessonStore


def make_incident(**kwargs):
    defaults = dict(
        project_id="PRJ-LS-001",
        incident_type=IncidentType.FILE_CORRUPTION,
        source=SourceType.CLIENT_UPLOAD,
        severity=Severity.HIGH,
    )
    defaults.update(kwargs)
    return IncidentStudyRecord(**defaults)


@pytest.fixture
def store(tmp_path):
    return LessonStore(root_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# Basic write / read
# ---------------------------------------------------------------------------

def test_record_creates_lessons_dir(tmp_path):
    store = LessonStore(root_dir=str(tmp_path))
    assert os.path.isdir(os.path.join(str(tmp_path), "lessons"))


def test_record_writes_file(store, tmp_path):
    incident = make_incident()
    path = store.record(incident, "REPORT CONTENT")
    assert os.path.exists(path)
    with open(path) as f:
        assert f.read() == "REPORT CONTENT"


def test_load_lesson_returns_text(store):
    incident = make_incident()
    store.record(incident, "LESSON TEXT")
    text = store.load_lesson(incident.incident_id)
    assert text == "LESSON TEXT"


def test_load_lesson_unknown_id_returns_none(store):
    assert store.load_lesson("does-not-exist") is None


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def test_index_file_created(tmp_path):
    LessonStore(root_dir=str(tmp_path))
    index_path = os.path.join(str(tmp_path), "lessons", "index.json")
    assert os.path.exists(index_path)
    with open(index_path) as f:
        assert json.load(f) == []


def test_record_updates_index(store):
    incident = make_incident()
    store.record(incident, "text")
    entries = store.all_index_entries()
    assert len(entries) == 1
    assert entries[0]["incident_id"] == incident.incident_id
    assert entries[0]["incident_type"] == "FILE_CORRUPTION"


def test_count_tracks_lessons(store):
    assert store.count() == 0
    for _ in range(3):
        store.record(make_incident(), "r")
    assert store.count() == 3


def test_reprocessing_same_incident_does_not_duplicate(store):
    incident = make_incident()
    store.record(incident, "v1")
    store.record(incident, "v2")
    assert store.count() == 1
    assert store.load_lesson(incident.incident_id) == "v2"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def test_entries_for_type_filters_correctly(store):
    inc_corr = make_incident(incident_type=IncidentType.FILE_CORRUPTION)
    inc_ledger = make_incident(incident_type=IncidentType.LEDGER_DRIFT)
    store.record(inc_corr, "a")
    store.record(inc_ledger, "b")

    results = store.entries_for_type("FILE_CORRUPTION")
    assert len(results) == 1
    assert results[0]["incident_id"] == inc_corr.incident_id


def test_entries_for_type_returns_empty_for_unknown(store):
    assert store.entries_for_type("NONEXISTENT") == []
