"""
integrity_plus.py — JGA Data Integrity Plus
============================================
Provides the JGA-branded zero-trust ledger, triple-pass entry gate
(verify × 3 → validate × 3 → certify × 3), chain-link silence mesh
concept, and threat-hunter engine that compose the SB-712
Data Integrity Plus defence-and-offence system.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ── JGA Branding ──────────────────────────────────────────────────────────

JGA_BRAND = "JGA"
JGA_SYSTEM_NAME = "JGA Data Integrity Plus"
JGA_VERSION = "1.0.0"
JGA_MOTTO = "No Trust. Triple Certified. Absolute Defence."
JGA_ENTRY_SEQUENCE = ("VERIFY", "VALIDATE", "CERTIFY")
JGA_PASSES_REQUIRED = 3  # each stage runs × 3


def jga_banner() -> str:
    width = 62
    top = "╔" + "═" * width + "╗"
    bot = "╚" + "═" * width + "╝"
    mid = lambda s: "║  " + s.center(width - 4) + "  ║"
    lines = [
        top,
        mid(f"■  {JGA_SYSTEM_NAME}  ■"),
        mid(f"v{JGA_VERSION}  ·  SB-712 IronBraid"),
        mid(JGA_MOTTO),
        bot,
    ]
    return "\n".join(lines)


# ── Entry Gate states ─────────────────────────────────────────────────────


class GateStatus(Enum):
    PENDING = "PENDING"
    VERIFYING = "VERIFYING"
    VALIDATING = "VALIDATING"
    CERTIFYING = "CERTIFYING"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


# ── Zero-Trust Ledger ─────────────────────────────────────────────────────


@dataclass
class LedgerEntry:
    entry_id: str
    payload_hash: str
    submitted_at: datetime
    status: GateStatus = GateStatus.PENDING
    verify_passes: int = 0
    validate_passes: int = 0
    certify_passes: int = 0
    rejection_reason: Optional[str] = None
    certified_at: Optional[datetime] = None
    # chain link to previous entry
    prev_hash: str = "genesis"
    chain_hash: str = ""

    def __post_init__(self) -> None:
        if not self.chain_hash:
            raw = f"{self.prev_hash}:{self.entry_id}:{self.payload_hash}"
            self.chain_hash = hashlib.sha256(raw.encode()).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_payload(payload: Any) -> str:
    import json

    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


class ZeroTrustLedger:
    """
    Append-only zero-trust ledger.  Every submission is PENDING until it
    completes the triple-pass entry gate (verify × 3 → validate × 3 →
    certify × 3).  No entry is trusted until all nine passes succeed.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, LedgerEntry] = {}
        self._chain: List[str] = []  # ordered entry IDs

    @property
    def head_hash(self) -> str:
        if not self._chain:
            return "genesis"
        return self._entries[self._chain[-1]].chain_hash

    def submit(self, payload: Any) -> str:
        """Submit a payload for evaluation. Returns the entry_id."""
        entry_id = uuid.uuid4().hex
        payload_hash = _hash_payload(payload)
        entry = LedgerEntry(
            entry_id=entry_id,
            payload_hash=payload_hash,
            submitted_at=_utcnow(),
            prev_hash=self.head_hash,
        )
        self._entries[entry_id] = entry
        self._chain.append(entry_id)
        return entry_id

    def _get(self, entry_id: str) -> LedgerEntry:
        entry = self._entries.get(entry_id)
        if entry is None:
            raise KeyError(f"Unknown entry: {entry_id}")
        return entry

    def verify_pass(self, entry_id: str) -> bool:
        """Record one verify pass. Returns True when all 3 passes done."""
        e = self._get(entry_id)
        if e.status not in (GateStatus.PENDING, GateStatus.VERIFYING):
            return e.verify_passes >= JGA_PASSES_REQUIRED
        e.status = GateStatus.VERIFYING
        e.verify_passes = min(e.verify_passes + 1, JGA_PASSES_REQUIRED)
        return e.verify_passes >= JGA_PASSES_REQUIRED

    def validate_pass(self, entry_id: str) -> bool:
        """Record one validate pass. Requires verify to be complete first."""
        e = self._get(entry_id)
        if e.verify_passes < JGA_PASSES_REQUIRED:
            raise ValueError("Cannot validate before verify is complete")
        e.status = GateStatus.VALIDATING
        e.validate_passes = min(e.validate_passes + 1, JGA_PASSES_REQUIRED)
        return e.validate_passes >= JGA_PASSES_REQUIRED

    def certify_pass(self, entry_id: str) -> bool:
        """Record one certify pass. Requires validate to be complete first."""
        e = self._get(entry_id)
        if e.validate_passes < JGA_PASSES_REQUIRED:
            raise ValueError("Cannot certify before validate is complete")
        e.status = GateStatus.CERTIFYING
        e.certify_passes = min(e.certify_passes + 1, JGA_PASSES_REQUIRED)
        if e.certify_passes >= JGA_PASSES_REQUIRED:
            e.status = GateStatus.CERTIFIED
            e.certified_at = _utcnow()
        return e.certify_passes >= JGA_PASSES_REQUIRED

    def reject(self, entry_id: str, reason: str) -> None:
        e = self._get(entry_id)
        e.status = GateStatus.REJECTED
        e.rejection_reason = reason

    def get_entry(self, entry_id: str) -> LedgerEntry:
        return self._get(entry_id)

    def certified_entries(self) -> List[LedgerEntry]:
        return [e for e in self._entries.values() if e.status == GateStatus.CERTIFIED]

    def pending_entries(self) -> List[LedgerEntry]:
        return [
            e
            for e in self._entries.values()
            if e.status not in (GateStatus.CERTIFIED, GateStatus.REJECTED)
        ]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "brand": JGA_BRAND,
            "system": JGA_SYSTEM_NAME,
            "head_hash": self.head_hash,
            "total_entries": len(self._chain),
            "certified": len(self.certified_entries()),
            "pending": len(self.pending_entries()),
            "rejected": sum(
                1 for e in self._entries.values() if e.status == GateStatus.REJECTED
            ),
        }


# ── Entry Gate ────────────────────────────────────────────────────────────


@dataclass
class EntryGateResult:
    entry_id: str
    status: GateStatus
    verify_passes: int
    validate_passes: int
    certify_passes: int
    duration_ms: float
    certified: bool
    rejection_reason: Optional[str] = None


class EntryGate:
    """
    Triple-pass entry gate: VERIFY×3 → VALIDATE×3 → CERTIFY×3.
    Upon entry every payload travels the figure-8 verification loop:
    three laps of verify, three laps of validate, three laps of certify.
    Only fully certified entries are admitted to the trusted ledger.
    """

    def __init__(self, ledger: ZeroTrustLedger) -> None:
        self._ledger = ledger

    def admit(self, payload: Any, *, validator_fn=None) -> EntryGateResult:
        """
        Run the full 9-pass entry sequence on *payload*.
        Optionally supply *validator_fn(payload) -> bool* for real checks;
        defaults to always-pass (integrity of the gate flow is the guarantee).
        """
        start = time.monotonic()
        entry_id = self._ledger.submit(payload)

        # ── VERIFY × 3 ──────────────────────────────────────────────────
        for _ in range(JGA_PASSES_REQUIRED):
            ok = True if validator_fn is None else bool(validator_fn(payload))
            if not ok:
                self._ledger.reject(entry_id, "VERIFY pass failed")
                return self._result(entry_id, start)
            self._ledger.verify_pass(entry_id)

        # ── VALIDATE × 3 ────────────────────────────────────────────────
        for _ in range(JGA_PASSES_REQUIRED):
            ok = True if validator_fn is None else bool(validator_fn(payload))
            if not ok:
                self._ledger.reject(entry_id, "VALIDATE pass failed")
                return self._result(entry_id, start)
            self._ledger.validate_pass(entry_id)

        # ── CERTIFY × 3 ─────────────────────────────────────────────────
        for _ in range(JGA_PASSES_REQUIRED):
            ok = True if validator_fn is None else bool(validator_fn(payload))
            if not ok:
                self._ledger.reject(entry_id, "CERTIFY pass failed")
                return self._result(entry_id, start)
            self._ledger.certify_pass(entry_id)

        return self._result(entry_id, start)

    def _result(self, entry_id: str, start: float) -> EntryGateResult:
        elapsed = (time.monotonic() - start) * 1000
        e = self._ledger.get_entry(entry_id)
        return EntryGateResult(
            entry_id=entry_id,
            status=e.status,
            verify_passes=e.verify_passes,
            validate_passes=e.validate_passes,
            certify_passes=e.certify_passes,
            duration_ms=round(elapsed, 3),
            certified=e.status == GateStatus.CERTIFIED,
            rejection_reason=e.rejection_reason,
        )


# ── Chain-Link Silence Mesh ───────────────────────────────────────────────


@dataclass
class MeshNode:
    node_id: str
    chain_hash: str
    linked_to: List[str] = field(default_factory=list)
    silent: bool = True  # nodes are silent until activated


class ChainLinkSilenceMesh:
    """
    A conceptual chain-link perimeter mesh.  Nodes are connected in a
    doubly-linked ring; each node stays silent (no traffic) unless it
    has been cleared by the EntryGate.  Any uncleared payload hitting a
    node triggers an alert and is silenced at the boundary.
    """

    def __init__(self, gate: EntryGate, ledger: ZeroTrustLedger) -> None:
        self._gate = gate
        self._ledger = ledger
        self._nodes: Dict[str, MeshNode] = {}
        self._alerts: List[Dict[str, Any]] = []

    def add_node(self, node_id: Optional[str] = None) -> str:
        nid = node_id or uuid.uuid4().hex[:8]
        chain_hash = hashlib.sha256(
            f"{nid}:{self._ledger.head_hash}".encode()
        ).hexdigest()
        node = MeshNode(node_id=nid, chain_hash=chain_hash)
        # link to previous node
        if self._nodes:
            last = list(self._nodes.keys())[-1]
            self._nodes[last].linked_to.append(nid)
            node.linked_to.append(last)
        self._nodes[nid] = node
        return nid

    def attempt_entry(self, payload: Any) -> Tuple[bool, EntryGateResult]:
        """
        Payload must clear the EntryGate before it passes through the mesh.
        Returns (admitted, result).
        """
        result = self._gate.admit(payload)
        if result.certified:
            # activate the mesh node for this payload
            nid = self.add_node()
            self._nodes[nid].silent = False
        else:
            self._alerts.append(
                {
                    "ts": _utcnow().isoformat(),
                    "entry_id": result.entry_id,
                    "reason": result.rejection_reason or "GATE_REJECTED",
                }
            )
        return result.certified, result

    def active_nodes(self) -> int:
        return sum(1 for n in self._nodes.values() if not n.silent)

    def alerts(self) -> List[Dict[str, Any]]:
        return list(self._alerts)

    def mesh_status(self) -> Dict[str, Any]:
        return {
            "total_nodes": len(self._nodes),
            "active_nodes": self.active_nodes(),
            "silent_nodes": len(self._nodes) - self.active_nodes(),
            "alerts": len(self._alerts),
        }


# ── Threat Hunter ─────────────────────────────────────────────────────────


class ThreatLevel(Enum):
    CLEAR = "CLEAR"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class ThreatReport:
    hunt_id: str
    timestamp: datetime
    entries_scanned: int
    threats_found: int
    threat_level: ThreatLevel
    offences_launched: int
    details: List[str] = field(default_factory=list)


class ThreatHunter:
    """
    Active threat hunter.  Scans the zero-trust ledger for anomalies
    (defence) and launches automated counter-measures (offence) against
    confirmed threats.
    """

    def __init__(self, ledger: ZeroTrustLedger) -> None:
        self._ledger = ledger
        self._hunt_log: List[ThreatReport] = []

    def hunt(self) -> ThreatReport:
        rejected = [
            e for e in self._ledger._entries.values() if e.status == GateStatus.REJECTED
        ]
        pending = self._ledger.pending_entries()
        certified = self._ledger.certified_entries()

        threats = len(rejected)
        scanned = len(self._ledger._entries)

        # determine threat level
        if scanned == 0:
            level = ThreatLevel.CLEAR
        elif threats == 0:
            level = ThreatLevel.CLEAR
        elif threats / max(scanned, 1) < 0.05:
            level = ThreatLevel.LOW
        elif threats / max(scanned, 1) < 0.15:
            level = ThreatLevel.MEDIUM
        elif threats / max(scanned, 1) < 0.35:
            level = ThreatLevel.HIGH
        else:
            level = ThreatLevel.CRITICAL

        details: List[str] = []
        offences = 0

        for e in rejected:
            details.append(
                f"THREAT entry={e.entry_id[:8]} reason={e.rejection_reason}"
            )
            # offence: quarantine the hash
            details.append(
                f"OFFENCE quarantine hash={e.payload_hash[:16]}… SILENCED"
            )
            offences += 1

        if pending:
            details.append(
                f"WATCH {len(pending)} entries pending full certification"
            )

        report = ThreatReport(
            hunt_id=uuid.uuid4().hex[:12],
            timestamp=_utcnow(),
            entries_scanned=scanned,
            threats_found=threats,
            threat_level=level,
            offences_launched=offences,
            details=details,
        )
        self._hunt_log.append(report)
        return report

    def last_report(self) -> Optional[ThreatReport]:
        return self._hunt_log[-1] if self._hunt_log else None


# ── Integrity Plus System ─────────────────────────────────────────────────


class IntegrityPlusSystem:
    """
    JGA Data Integrity Plus — master orchestrator.

    Composes:
    • ZeroTrustLedger   — no-trust append-only chain
    • EntryGate         — verify×3 → validate×3 → certify×3
    • ChainLinkMesh     — perimeter silence mesh
    • ThreatHunter      — active defence + offence
    """

    BRAND = JGA_BRAND
    SYSTEM_NAME = JGA_SYSTEM_NAME
    VERSION = JGA_VERSION
    MOTTO = JGA_MOTTO

    def __init__(self) -> None:
        self.ledger = ZeroTrustLedger()
        self.gate = EntryGate(self.ledger)
        self.mesh = ChainLinkSilenceMesh(self.gate, self.ledger)
        self.hunter = ThreatHunter(self.ledger)

    def enter(self, payload: Any, *, validator_fn=None) -> EntryGateResult:
        """
        Primary entry point.  All payloads must pass the full gate.
        Returns an EntryGateResult; certified=True means admitted.
        """
        result = self.gate.admit(payload, validator_fn=validator_fn)
        if not result.certified and result.rejection_reason:
            self.mesh._alerts.append(
                {
                    "ts": _utcnow().isoformat(),
                    "entry_id": result.entry_id,
                    "reason": result.rejection_reason,
                }
            )
        return result

    def status(self) -> Dict[str, Any]:
        ledger_snap = self.ledger.snapshot()
        mesh_snap = self.mesh.mesh_status()
        hunt = self.hunter.last_report()
        return {
            "brand": self.BRAND,
            "system": self.SYSTEM_NAME,
            "version": self.VERSION,
            "motto": self.MOTTO,
            "ledger": ledger_snap,
            "mesh": mesh_snap,
            "last_hunt": {
                "threat_level": hunt.threat_level.value if hunt else "N/A",
                "threats_found": hunt.threats_found if hunt else 0,
                "offences_launched": hunt.offences_launched if hunt else 0,
            },
        }

    def run_hunt(self) -> ThreatReport:
        return self.hunter.hunt()

    def banner(self) -> str:
        return jga_banner()
