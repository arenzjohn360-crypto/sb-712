"""
vera_gate.py — SB-712 IronBraid Radiant Core

VERA (Verification Enforcement and Risk Arbitration) is the central gate
that approves or denies actions before they reach the Spine, Ledger, or
any protected node.

VERA enforces triple-certification: an action must carry a hash check,
a validation pass, and a certification mark to be approved.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CertificationBundle:
    """Three-mark bundle required for VERA approval."""

    hash_check: bool = False
    validation_pass: bool = False
    certification_mark: bool = False

    @property
    def is_triple_certified(self) -> bool:
        """Return True only when all three marks are present."""
        return self.hash_check and self.validation_pass and self.certification_mark


@dataclass
class VERADecision:
    """Decision record returned by the VERA gate."""

    action: str
    target: str
    approved: bool
    reason: str
    timestamp: float = field(default_factory=time.time)
    audit_trail: List[str] = field(default_factory=list)


class VERAGate:
    """
    Evaluates an action against the triple-certification doctrine and
    returns an immutable :class:`VERADecision`.

    All decisions are appended to an internal audit log accessible via
    :attr:`audit_log`.

    Usage::

        gate = VERAGate()
        bundle = CertificationBundle(hash_check=True, validation_pass=True,
                                     certification_mark=True)
        decision = gate.evaluate("write", "spine/root_manifest.json", bundle)
        assert decision.approved
    """

    def __init__(self) -> None:
        self.audit_log: List[VERADecision] = []

    def evaluate(
        self,
        action: str,
        target: str,
        bundle: CertificationBundle,
        context: Optional[Dict[str, Any]] = None,
    ) -> VERADecision:
        """
        Evaluate whether *action* on *target* may proceed.

        Parameters
        ----------
        action:
            Requested operation (e.g. ``write``, ``delete``, ``activate``).
        target:
            Resource identifier.
        bundle:
            The certification evidence supplied by the caller.
        context:
            Optional metadata attached to the audit record.
        """
        trail: List[str] = [
            f"hash_check={'PASS' if bundle.hash_check else 'FAIL'}",
            f"validation_pass={'PASS' if bundle.validation_pass else 'FAIL'}",
            f"certification_mark={'PASS' if bundle.certification_mark else 'FAIL'}",
        ]
        if context:
            trail.append(f"context={context}")

        if bundle.is_triple_certified:
            decision = VERADecision(
                action=action,
                target=target,
                approved=True,
                reason="Triple-certification passed.",
                audit_trail=trail,
            )
        else:
            missing = [
                m
                for m, ok in [
                    ("hash_check", bundle.hash_check),
                    ("validation_pass", bundle.validation_pass),
                    ("certification_mark", bundle.certification_mark),
                ]
                if not ok
            ]
            decision = VERADecision(
                action=action,
                target=target,
                approved=False,
                reason=f"Triple-certification failed. Missing: {missing}",
                audit_trail=trail,
            )

        self.audit_log.append(decision)
        return decision

    def last_decision(self) -> Optional[VERADecision]:
        """Return the most recent decision, or ``None`` if the log is empty."""
        return self.audit_log[-1] if self.audit_log else None
