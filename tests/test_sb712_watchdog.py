from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import sb712_watchdog as watchdog


def _configure_paths(tmp_path: Path) -> None:
    watchdog.DB_PATH = tmp_path / "incidents.db"
    watchdog.BACKUP_DIR = tmp_path / "backups"
    watchdog.LOG_PATH = tmp_path / "watchdog.log"


def test_init_db_creates_required_tables(tmp_path):
    _configure_paths(tmp_path)
    watchdog.init_db()

    conn = sqlite3.connect(watchdog.DB_PATH)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()

    assert "incidents" in tables
    assert "known_good_hashes" in tables


def test_log_incident_updates_hash_chain(tmp_path):
    _configure_paths(tmp_path)
    watchdog.braid = watchdog.BraidState()
    watchdog.init_db()

    watchdog.log_incident("files", "warning", "/tmp/a", "changed")
    first_hash = watchdog.braid.last_incident_hash
    watchdog.log_incident("files", "warning", "/tmp/b", "changed")
    second_hash = watchdog.braid.last_incident_hash

    assert isinstance(first_hash, str) and len(first_hash) == 64
    assert isinstance(second_hash, str) and len(second_hash) == 64
    assert first_hash != second_hash


def test_known_good_hash_round_trip(tmp_path):
    _configure_paths(tmp_path)
    watchdog.init_db()

    target = str(tmp_path / "target.txt")
    watchdog.set_known_good(target, "abc123")

    assert watchdog.get_known_good(target) == "abc123"


def test_braid_state_flags_silent_and_malformed_heartbeat():
    state = watchdog.BraidState()
    now = time.time()
    with state.lock:
        state.heartbeats["files"] = now - 200
        state.heartbeat_hashes["files"] = "a" * 64
        state.heartbeats["process"] = now
        state.heartbeat_hashes["process"] = "bad"

    flagged = set(state.check_all_alive(max_silence=90))
    assert "files" in flagged
    assert "process" in flagged
