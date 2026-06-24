"""
SB688 Integrity Checker and self-healing coordinator.

The IntegrityChecker scans a BlockStore for corrupt blocks and attempts
to heal them from a supplied repair source (another BlockStore or a
callable returning bytes for a given key).

The audit log records every integrity event and chains each entry to
the previous one via SHA-256 so that any tampering with the log itself
is detectable via verify_audit_chain().
"""
import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Union


@dataclass
class IntegrityEvent:
    timestamp: float
    key: str
    event_type: str   # corruption_detected | repair_attempted | repair_success | repair_failed
    details: str = ""


RepairSource = Union["BlockStore", Callable[[str], bytes]]  # type: ignore[name-defined]


class IntegrityChecker:
    """
    Scans a BlockStore, detects corrupt blocks, and heals them from a
    repair source.  Maintains a tamper-evident chained audit log.
    """

    def __init__(self, store, repair_source: Optional[RepairSource] = None) -> None:
        self._store = store
        self._repair_source = repair_source
        self._audit_log: List[IntegrityEvent] = []
        self._audit_chain: List[str] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Internal audit-log helpers                                          #
    # ------------------------------------------------------------------ #

    def _log(self, key: str, event_type: str, details: str = "") -> None:
        event = IntegrityEvent(
            timestamp=time.monotonic(),
            key=key,
            event_type=event_type,
            details=details,
        )
        with self._lock:
            prev_hash = self._audit_chain[-1] if self._audit_chain else "genesis"
            entry_str = (
                f"{event.timestamp}|{key}|{event_type}|{details}|{prev_hash}"
            )
            chain_hash = hashlib.sha256(entry_str.encode()).hexdigest()
            self._audit_log.append(event)
            self._audit_chain.append(chain_hash)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def scan(self) -> List[str]:
        """Scan all blocks; log and return list of corrupt keys."""
        corrupt = self._store.corrupt_keys()
        for key in corrupt:
            self._log(key, "corruption_detected")
        return corrupt

    def heal(self, key: str) -> bool:
        """Attempt to heal *key* from repair_source.  Returns True on success."""
        if self._repair_source is None:
            self._log(key, "repair_failed", "no repair source configured")
            return False
        self._log(key, "repair_attempted")
        try:
            if callable(self._repair_source):
                good_data = self._repair_source(key)
            else:
                good_data = self._repair_source.get(key)
            self._store.put(key, good_data)
            self._log(key, "repair_success")
            return True
        except Exception as exc:
            self._log(key, "repair_failed", str(exc))
            return False

    def scan_and_heal(self) -> Dict[str, bool]:
        """Scan then heal all corrupt blocks.  Returns {key: healed}."""
        corrupt = self.scan()
        return {key: self.heal(key) for key in corrupt}

    def verify_audit_chain(self) -> bool:
        """Return True if the audit log chain has not been tampered with."""
        prev_hash = "genesis"
        with self._lock:
            events = list(self._audit_log)
            chain = list(self._audit_chain)
        for event, expected in zip(events, chain):
            entry_str = (
                f"{event.timestamp}|{event.key}|{event.event_type}"
                f"|{event.details}|{prev_hash}"
            )
            if hashlib.sha256(entry_str.encode()).hexdigest() != expected:
                return False
            prev_hash = expected
        return True

    def is_idempotent_repair(self, key: str) -> bool:
        """Return True if healing *key* twice yields the same data."""
        if self._repair_source is None:
            return False
        try:
            if callable(self._repair_source):
                d1 = self._repair_source(key)
                d2 = self._repair_source(key)
            else:
                d1 = self._repair_source.get(key)
                d2 = self._repair_source.get(key)
            return d1 == d2
        except Exception:
            return False

    @property
    def audit_log(self) -> List[IntegrityEvent]:
        with self._lock:
            return list(self._audit_log)
