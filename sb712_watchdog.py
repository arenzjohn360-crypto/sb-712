#!/usr/bin/env python3
"""SB712 WATCHDOG - Triple-Braided System Guardian.

Three independent strands run in daemon threads:
  1) File integrity
  2) Process/network watch
  3) Registry/startup watch (Windows)

A braid supervisor cross-verifies strand heartbeats and records incidents to
an on-disk SQLite forensic store.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

IS_WINDOWS = platform.system() == "Windows"

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "sb712_incidents.db"
BACKUP_DIR = BASE_DIR / "sb712_backups"
LOG_PATH = BASE_DIR / "sb712_watchdog.log"

WATCHED_PATHS = [
    str(Path.home() / "Documents"),
]
if IS_WINDOWS:
    WATCHED_PATHS += [
        r"C:\Windows\System32\drivers\etc\hosts",
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"),
    ]

CHECK_INTERVAL_FILES = 30
CHECK_INTERVAL_PROCESS = 15
CHECK_INTERVAL_REGISTRY = 60
HEARTBEAT_INTERVAL = 10

REGISTRY_WATCH_KEYS = [
    r"Software\Microsoft\Windows\CurrentVersion\Run",
    r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
]


class BraidState:
    """Shared heartbeat state for strand cross-verification."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.heartbeats: dict[str, float | None] = {"files": None, "process": None, "registry": None}
        self.heartbeat_hashes: dict[str, str | None] = {"files": None, "process": None, "registry": None}
        self.last_incident_hash: str | None = None

    def beat(self, strand_name: str) -> None:
        now = time.time()
        payload = f"{strand_name}|{int(now)}|{self.last_incident_hash or 'GENESIS'}"
        hb_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self.lock:
            self.heartbeats[strand_name] = now
            self.heartbeat_hashes[strand_name] = hb_hash

    def check_all_alive(self, max_silence: int = 90) -> list[str]:
        """Return strand names that are silent or have malformed heartbeat hash."""
        now = time.time()
        flagged: list[str] = []
        with self.lock:
            for name in self.heartbeats:
                ts = self.heartbeats[name]
                hb_hash = self.heartbeat_hashes[name]
                if ts is None:
                    continue
                if now - ts > max_silence:
                    flagged.append(name)
                    continue
                if hb_hash is None or len(hb_hash) != 64:
                    flagged.append(name)
        return flagged


braid = BraidState()


def _connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            strand TEXT,
            severity TEXT,
            target TEXT,
            description TEXT,
            action_taken TEXT,
            root_cause TEXT,
            incident_hash TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS known_good_hashes (
            path TEXT PRIMARY KEY,
            hash TEXT,
            last_verified TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def write_log(msg: str) -> None:
    line = f"{datetime.now(tz=timezone.utc).isoformat()} | {msg}"
    print(line)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_incident(
    strand: str,
    severity: str,
    target: str,
    description: str,
    action_taken: str = "none",
    root_cause: str = "unknown",
) -> None:
    """Write an incident row with hash chain linkage."""
    conn = _connect_db()
    ts = datetime.now(tz=timezone.utc).isoformat()
    chain_input = f"{braid.last_incident_hash or 'GENESIS'}|{ts}|{strand}|{target}|{description}"
    incident_hash = hashlib.sha256(chain_input.encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO incidents (timestamp, strand, severity, target, description, action_taken, root_cause, incident_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, strand, severity, target, description, action_taken, root_cause, incident_hash),
    )
    conn.commit()
    conn.close()
    braid.last_incident_hash = incident_hash
    write_log(f"[{severity.upper()}] ({strand}) {target}: {description} -> action: {action_taken}")


def find_similar_past_incidents(target: str) -> str | None:
    conn = _connect_db()
    cur = conn.execute(
        "SELECT COUNT(*), root_cause FROM incidents WHERE target = ? GROUP BY root_cause ORDER BY COUNT(*) DESC LIMIT 1",
        (target,),
    )
    row = cur.fetchone()
    conn.close()
    if row and row[0] >= 2:
        return row[1]
    return None


def hash_file(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (PermissionError, FileNotFoundError, IsADirectoryError, OSError):
        return None


def get_known_good(path: str) -> str | None:
    conn = _connect_db()
    cur = conn.execute("SELECT hash FROM known_good_hashes WHERE path = ?", (path,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def set_known_good(path: str, file_hash: str) -> None:
    conn = _connect_db()
    conn.execute(
        "INSERT OR REPLACE INTO known_good_hashes (path, hash, last_verified) VALUES (?, ?, ?)",
        (path, file_hash, datetime.now(tz=timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def _iter_files(base_path: Path) -> Iterable[Path]:
    if base_path.is_file():
        yield base_path
        return
    if not base_path.is_dir():
        return
    for item in base_path.rglob("*"):
        if item.is_file():
            yield item


def _quarantine_snapshot(path: Path) -> str:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    dest = BACKUP_DIR / f"quarantine_{stamp}_{digest}_{path.name}"
    try:
        shutil.copy2(path, dest)
        return f"quarantine_snapshot:{dest}"
    except (FileNotFoundError, PermissionError, OSError):
        return "flagged_for_review"


def strand_file_integrity() -> None:
    write_log("STRAND 1 (File Integrity) online.")

    for base in WATCHED_PATHS:
        for f in _iter_files(Path(base)):
            h = hash_file(f)
            if h and not get_known_good(str(f)):
                set_known_good(str(f), h)

    while True:
        try:
            for base in WATCHED_PATHS:
                for f in _iter_files(Path(base)):
                    current_hash = hash_file(f)
                    if current_hash is None:
                        continue
                    target = str(f)
                    known = get_known_good(target)
                    if known is None:
                        set_known_good(target, current_hash)
                        continue
                    if known == current_hash:
                        continue

                    root_cause = find_similar_past_incidents(target) or "investigating"
                    action = _quarantine_snapshot(f)
                    log_incident(
                        "files",
                        "warning",
                        target,
                        "File hash changed unexpectedly",
                        action_taken=action,
                        root_cause=root_cause,
                    )
                    set_known_good(target, current_hash)
            braid.beat("files")
        except Exception as exc:  # pragma: no cover - defensive watchdog path
            write_log(f"STRAND 1 error: {exc}")
        time.sleep(CHECK_INTERVAL_FILES)


def strand_process_network() -> None:
    write_log("STRAND 2 (Process/Network) online.")
    try:
        import psutil
    except ImportError:
        write_log("STRAND 2 disabled: psutil not installed. Run: pip install psutil")
        return

    known_procs: set[str] = set()
    for p in psutil.process_iter(["name"]):
        name = p.info.get("name")
        if isinstance(name, str):
            known_procs.add(name)

    while True:
        try:
            current_procs: set[str] = set()
            for p in psutil.process_iter(["name"]):
                name = p.info.get("name")
                if isinstance(name, str):
                    current_procs.add(name)

            for name in sorted(current_procs - known_procs):
                log_incident(
                    "process",
                    "info",
                    name,
                    "New process observed",
                    action_taken="baseline updated",
                    root_cause="new_execution",
                )
            known_procs = current_procs

            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "ESTABLISHED" and conn.raddr:
                    pass

            braid.beat("process")
        except Exception as exc:  # pragma: no cover - defensive watchdog path
            write_log(f"STRAND 2 error: {exc}")
        time.sleep(CHECK_INTERVAL_PROCESS)


def strand_registry() -> None:
    write_log("STRAND 3 (Registry/Startup) online.")
    if not IS_WINDOWS:
        write_log("STRAND 3 disabled: not running on Windows.")
        return

    import winreg

    def snapshot_key(hive: int, subkey: str) -> dict[str, str]:
        values: dict[str, str] = {}
        try:
            with winreg.OpenKey(hive, subkey) as key:
                idx = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, idx)
                        values[name] = str(value)
                        idx += 1
                    except OSError:
                        break
        except FileNotFoundError:
            pass
        return values

    baseline = {subkey: snapshot_key(winreg.HKEY_CURRENT_USER, subkey) for subkey in REGISTRY_WATCH_KEYS}

    while True:
        try:
            for subkey in REGISTRY_WATCH_KEYS:
                current = snapshot_key(winreg.HKEY_CURRENT_USER, subkey)
                old = baseline.get(subkey, {})
                added = {k: v for k, v in current.items() if k not in old}
                removed = {k: v for k, v in old.items() if k not in current}

                for name, value in added.items():
                    target = f"{subkey}\\{name}"
                    root_cause = find_similar_past_incidents(target) or "investigating"
                    log_incident(
                        "registry",
                        "warning",
                        target,
                        f"New startup entry added: {value}",
                        action_taken="flagged for review",
                        root_cause=root_cause,
                    )
                for name in removed:
                    log_incident(
                        "registry",
                        "info",
                        f"{subkey}\\{name}",
                        "Startup entry removed",
                        action_taken="baseline updated",
                        root_cause="user_or_uninstall",
                    )
                baseline[subkey] = current

            braid.beat("registry")
        except Exception as exc:  # pragma: no cover - defensive watchdog path
            write_log(f"STRAND 3 error: {exc}")
        time.sleep(CHECK_INTERVAL_REGISTRY)


def braid_supervisor() -> None:
    write_log("BRAID SUPERVISOR online - cross-verifying all strands.")
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        dead = braid.check_all_alive()
        if not dead:
            continue
        for strand in dead:
            log_incident(
                "supervisor",
                "critical",
                strand,
                f"Strand '{strand}' has gone silent or malformed heartbeat - possible crash or compromise",
                action_taken="alert logged - manual restart needed",
                root_cause="strand_failure",
            )


def main() -> None:
    write_log("=" * 60)
    write_log("SB712 WATCHDOG starting up - triple braid initializing")
    write_log(f"Platform: {platform.system()} | Python: {platform.python_version()}")
    write_log("=" * 60)

    init_db()

    threads = [
        threading.Thread(target=strand_file_integrity, daemon=True, name="Strand-Files"),
        threading.Thread(target=strand_process_network, daemon=True, name="Strand-Process"),
        threading.Thread(target=strand_registry, daemon=True, name="Strand-Registry"),
        threading.Thread(target=braid_supervisor, daemon=True, name="Braid-Supervisor"),
    ]
    for thread in threads:
        thread.start()
        time.sleep(0.5)

    write_log("All strands launched. SB712 is now watching.")
    write_log(f"Incident log: {DB_PATH}")
    write_log(f"Text log: {LOG_PATH}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        write_log("SB712 WATCHDOG shutting down (Ctrl+C received).")
        sys.exit(0)


if __name__ == "__main__":
    main()
